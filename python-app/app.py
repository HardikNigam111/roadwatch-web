import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk


BACKGROUND = "#0b1110"
PANEL = "#111918"
PANEL_SOFT = "#151e1c"
LINE = "#27312e"
TEXT = "#f4f5ee"
MUTED = "#89948c"
LIME = "#c4f36b"
AMBER = "#ffb75e"
RED = "#ff9c8d"

CLOSED_EYE_RATIO = 0.20
CLOSED_EYE_DURATION = 1.5
ALERT_COOLDOWN = 8.0
LEFT_EYE = (33, 160, 158, 133, 153, 144)
RIGHT_EYE = (362, 385, 387, 263, 373, 380)
EYE_CONTOURS = (
    (33, 160, 158, 133, 153, 144),
    (362, 385, 387, 263, 373, 380),
)


class RoadwatchApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Roadwatch — Driver Awareness")
        self.root.geometry("1100x760")
        self.root.minsize(820, 660)
        self.root.configure(bg=BACKGROUND)

        self.cv2 = None
        self.np = None
        self.face_mesh = None
        self.camera = None
        self.running = False
        self.closed_eyes_since = None
        self.last_alert_at = 0.0
        self.photo = None
        self.image_item = None
        self.status_level = None
        self.speech_queue = queue.Queue()
        self.voice_events = queue.Queue()

        self._configure_styles()
        self._build_interface()
        self._start_speech_worker()
        self.root.after(100, self._poll_voice_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Roadwatch.Horizontal.TProgressbar",
            troughcolor="#354038",
            background=LIME,
            bordercolor="#354038",
            lightcolor=LIME,
            darkcolor=LIME,
            thickness=4,
        )

    def _build_interface(self):
        shell = tk.Frame(self.root, bg=BACKGROUND)
        shell.pack(fill="both", expand=True, padx=40)

        header = tk.Frame(shell, bg=BACKGROUND, height=68)
        header.pack(fill="x")
        header.pack_propagate(False)
        brand = tk.Frame(header, bg=BACKGROUND)
        brand.pack(side="left", anchor="center")
        tk.Label(
            brand, text="▥", font=("Helvetica", 19, "bold"), fg=LIME, bg=BACKGROUND
        ).pack(side="left", padx=(0, 8))
        tk.Label(
            brand, text="roadwatch", font=("Helvetica", 18, "bold"),
            fg=TEXT, bg=BACKGROUND,
        ).pack(side="left")
        tk.Label(
            header, text="●  ON-DEVICE PROCESSING       BETA 01",
            font=("Menlo", 9), fg="#a3aaa4", bg=BACKGROUND,
        ).pack(side="right", anchor="center")
        tk.Frame(shell, bg="#202927", height=1).pack(fill="x")

        intro = tk.Frame(shell, bg=BACKGROUND)
        intro.pack(fill="x", pady=(34, 24))
        copy = tk.Frame(intro, bg=BACKGROUND)
        copy.pack(side="left", fill="x", expand=True)
        tk.Label(
            copy, text="—  DRIVER AWARENESS SYSTEM",
            font=("Menlo", 9), fg=LIME, bg=BACKGROUND,
        ).pack(anchor="w")
        tk.Label(
            copy, text="Eyes on the road.\nWe’ve got your back.",
            font=("Helvetica", 32, "bold"), fg=TEXT, bg=BACKGROUND,
            justify="left", anchor="w",
        ).pack(anchor="w", pady=(9, 5))
        tk.Label(
            copy, text="Real-time face tracking with voice alerts when your eyes need a break.",
            font=("Helvetica", 11), fg="#99a39c", bg=BACKGROUND,
        ).pack(anchor="w")
        self.session_label = tk.Label(
            intro, text="●  SYSTEM STANDBY", font=("Menlo", 9),
            fg="#9ca59e", bg=PANEL, padx=12, pady=9,
        )
        self.session_label.pack(side="right", anchor="s")

        dashboard = tk.Frame(shell, bg=BACKGROUND)
        dashboard.pack(fill="both", expand=True)
        dashboard.grid_columnconfigure(0, weight=16, uniform="dashboard")
        dashboard.grid_columnconfigure(1, weight=9, uniform="dashboard")
        dashboard.grid_rowconfigure(0, weight=1)

        camera_panel = self._panel(dashboard)
        camera_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        insights = self._panel(dashboard)
        insights.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._build_camera_panel(camera_panel)
        self._build_insights_panel(insights)

        bottom = tk.Frame(shell, bg=BACKGROUND)
        bottom.pack(fill="x", pady=(17, 19))
        tk.Label(
            bottom,
            text="* A helpful driving companion, not a replacement for rest or safe driving.",
            font=("Helvetica", 9), fg=MUTED, bg=BACKGROUND,
        ).pack(side="left")
        tk.Label(
            bottom, text="DEMO EXPERIENCE · NOT A CERTIFIED SAFETY SYSTEM",
            font=("Menlo", 8), fg="#778179", bg=BACKGROUND,
        ).pack(side="right")
        tk.Frame(shell, bg="#202927", height=1).pack(fill="x")
        tk.Label(
            shell, text="ROADWATCH  /  DRIVER AWARENESS",
            font=("Menlo", 8), fg="#647068", bg=BACKGROUND,
        ).pack(anchor="w", pady=10)

    @staticmethod
    def _panel(parent):
        return tk.Frame(
            parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1,
            padx=18, pady=16,
        )

    @staticmethod
    def _heading(parent, kicker, title, right_text=None):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=(0, 15))
        text = tk.Frame(row, bg=PANEL)
        text.pack(side="left")
        tk.Label(
            text, text=kicker, font=("Menlo", 8), fg="#8d9891", bg=PANEL,
        ).pack(anchor="w", pady=(0, 4))
        tk.Label(
            text, text=title, font=("Helvetica", 14, "bold"), fg=TEXT, bg=PANEL,
        ).pack(anchor="w")
        status = tk.Label(
            row, text=right_text or "", font=("Menlo", 8),
            fg="#76817a", bg=PANEL,
        )
        status.pack(side="right", anchor="center")
        return status

    def _build_camera_panel(self, panel):
        self.live_label = self._heading(panel, "LIVE MONITOR", "Driver camera", "●  OFFLINE")
        self.camera_stage = tk.Canvas(
            panel, bg="#0b1110", highlightbackground="#293330",
            highlightthickness=1, bd=0,
        )
        self.camera_stage.pack(fill="both", expand=True)
        self.camera_stage.bind("<Configure>", self._resize_camera_image)
        self.camera_stage.create_text(
            20, 20, text="Your camera view lives here",
            fill="#dce2da", font=("Helvetica", 12, "bold"), anchor="nw",
            tags="placeholder",
        )
        self.camera_stage.create_text(
            20, 44, text="Start a session to enable face tracking.",
            fill="#78837b", font=("Helvetica", 10), anchor="nw",
            tags="placeholder",
        )
        self.camera_stage.create_text(
            12, 0, text="●  LOCAL FEED  /  NO RECORDING",
            fill="#b6c0b8", font=("Menlo", 8), anchor="sw", tags="stamp",
        )
        self.camera_stage.bind("<Configure>", self._position_stamp, add="+")

        controls = tk.Frame(panel, bg=PANEL)
        controls.pack(fill="x", pady=(14, 0))
        self.camera_hint = tk.Label(
            controls, text="Position your face in the frame to begin.",
            font=("Helvetica", 9), fg=MUTED, bg=PANEL, anchor="w",
            wraplength=360, justify="left",
        )
        self.camera_hint.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.start_button = tk.Button(
            controls, text="▶  Start monitoring  ↗",
            command=self.toggle_monitoring, bg=LIME, fg="#15200d",
            activebackground="#d5ff91", activeforeground="#15200d",
            font=("Helvetica", 10, "bold"), relief="flat", bd=0,
            padx=13, pady=9, cursor="hand2",
        )
        self.start_button.pack(side="right")
        self.error_label = tk.Label(
            panel, text="", font=("Helvetica", 9), fg=RED, bg=PANEL,
            anchor="w", justify="left", wraplength=650,
        )
        self.error_label.pack(fill="x", pady=(8, 0))

    def _build_insights_panel(self, panel):
        self._heading(panel, "YOUR STATUS", "Stay sharp", "✳")
        self.status_box = tk.Frame(
            panel, bg="#19251a", highlightbackground="#35432d", highlightthickness=1,
            padx=13, pady=12,
        )
        self.status_box.pack(fill="x", pady=(0, 10))
        row = tk.Frame(self.status_box, bg="#19251a")
        row.pack(fill="x")
        tk.Label(
            row, text="ATTENTION", font=("Menlo", 8), fg="#99a49b",
            bg="#19251a",
        ).pack(side="left")
        self.status_dot = tk.Label(
            row, text="●", font=("Helvetica", 8), fg=LIME, bg="#19251a",
        )
        self.status_dot.pack(side="right")
        self.status_title = tk.Label(
            self.status_box, text="Ready when you are",
            font=("Helvetica", 12, "bold"), fg=TEXT, bg="#19251a", anchor="w",
        )
        self.status_title.pack(fill="x", pady=(9, 3))
        self.status_description = tk.Label(
            self.status_box, text="Start monitoring to see your live status.",
            font=("Helvetica", 9), fg="#9ba49d", bg="#19251a",
            anchor="w", justify="left", wraplength=300,
        )
        self.status_description.pack(fill="x")
        self.attention = ttk.Progressbar(
            self.status_box, style="Roadwatch.Horizontal.TProgressbar",
            maximum=100, value=0,
        )
        self.attention.pack(fill="x", pady=(13, 5))
        scale = tk.Frame(self.status_box, bg="#19251a")
        scale.pack(fill="x")
        tk.Label(
            scale, text="NEEDS ATTENTION", font=("Menlo", 7),
            fg="#737e76", bg="#19251a",
        ).pack(side="left")
        tk.Label(
            scale, text="FOCUSED", font=("Menlo", 7), fg="#737e76",
            bg="#19251a",
        ).pack(side="right")

        self.eye_value = self._metric(panel, "EYE STATUS", "—", "WAITING")
        self.face_value = self._metric(panel, "FACE TRACKING", "Inactive", "OFF")

        voice = tk.Frame(
            panel, bg=PANEL_SOFT, highlightbackground="#29332f", highlightthickness=1,
            padx=9, pady=8,
        )
        voice.pack(fill="x", pady=(12, 0))
        voice_text = tk.Frame(voice, bg=PANEL_SOFT)
        voice_text.pack(side="left", fill="x", expand=True)
        tk.Label(
            voice_text, text="VOICE ALERTS", font=("Menlo", 8),
            fg="#99a49b", bg=PANEL_SOFT,
        ).pack(anchor="w")
        self.voice_status = tk.Label(
            voice_text, text="Preparing voice alerts…",
            font=("Helvetica", 9), fg="#a1aaa2", bg=PANEL_SOFT,
        )
        self.voice_status.pack(anchor="w", pady=(3, 0))
        self.test_button = tk.Button(
            voice, text="TEST", command=lambda: self._speak(
                "This is a Roadwatch voice alert test."
            ),
            bg=PANEL_SOFT, fg="#bac4bb", activebackground="#202a26",
            activeforeground=LIME, font=("Menlo", 8), relief="flat",
            highlightbackground="#3a453f", highlightthickness=1, bd=0,
            padx=8, pady=5, cursor="hand2",
        )
        self.test_button.pack(side="right")
        tk.Label(
            panel, text="▣  Your camera stays on this device. Nothing is saved or sent.",
            font=("Helvetica", 8), fg="#79847c", bg=PANEL, anchor="w",
            wraplength=320, justify="left",
        ).pack(fill="x", pady=(12, 0))

    def _metric(self, panel, label, value, state):
        row = tk.Frame(panel, bg=PANEL, highlightbackground="#252e2b", highlightthickness=1)
        row.pack(fill="x")
        icon = "◉" if label == "EYE STATUS" else "◎"
        tk.Label(
            row, text=icon, font=("Helvetica", 15), fg=LIME, bg=PANEL,
            width=3,
        ).pack(side="left", padx=(3, 6), pady=9)
        text = tk.Frame(row, bg=PANEL)
        text.pack(side="left", fill="x", expand=True, pady=7)
        tk.Label(
            text, text=label, font=("Menlo", 8), fg="#99a49b", bg=PANEL,
        ).pack(anchor="w")
        value_label = tk.Label(
            text, text=value, font=("Helvetica", 9, "bold"),
            fg=TEXT, bg=PANEL,
        )
        value_label.pack(anchor="w", pady=(3, 0))
        state_label = tk.Label(
            row, text=state, font=("Menlo", 7), fg="#748078", bg=PANEL,
        )
        state_label.pack(side="right", padx=8)
        value_label.state_label = state_label
        return value_label

    def _position_stamp(self, event):
        self.camera_stage.coords("stamp", 12, max(12, event.height - 12))

    def _resize_camera_image(self, _event=None):
        if self.photo is not None and self.image_item is not None:
            self.camera_stage.coords(
                self.image_item,
                self.camera_stage.winfo_width() // 2,
                self.camera_stage.winfo_height() // 2,
            )

    def toggle_monitoring(self):
        if self.running:
            self.stop_monitoring()
        else:
            self.start_monitoring()

    def start_monitoring(self):
        self.error_label.configure(text="")
        self.camera_hint.configure(text="Connecting to camera and loading face tracking…")
        self.start_button.configure(state="disabled", text="Connecting…")
        self.root.update_idletasks()
        try:
            import cv2
            import mediapipe as mp
            import numpy as np

            self.cv2 = cv2
            self.np = np
            backend = cv2.CAP_AVFOUNDATION if hasattr(cv2, "CAP_AVFOUNDATION") else cv2.CAP_ANY
            self.camera = cv2.VideoCapture(0, backend)
            if not self.camera.isOpened():
                self.camera.release()
                self.camera = None
                raise RuntimeError("No camera could be opened. Connect a camera and try again.")
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.face_mesh = mp.solutions.face_mesh.FaceMesh(
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.55,
                min_tracking_confidence=0.55,
            )
        except Exception as error:
            if self.camera is not None:
                self.camera.release()
                self.camera = None
            if self.face_mesh is not None:
                self.face_mesh.close()
                self.face_mesh = None
            self.start_button.configure(state="normal", text="▶  Start monitoring  ↗")
            self.camera_hint.configure(text="Check camera access and try again.")
            self.error_label.configure(
                text=f"Could not start monitoring: {error}\n"
                "Install dependencies with: python -m pip install -r requirements.txt"
            )
            return

        self.running = True
        self.closed_eyes_since = None
        self.live_label.configure(text="●  LIVE", fg=LIME)
        self.session_label.configure(text="●  MONITORING", fg=LIME)
        self.start_button.configure(
            state="normal", text="■  Stop monitoring  ×",
            bg="#26312d", fg=TEXT, activebackground="#34413b",
            activeforeground=TEXT,
        )
        self.camera_stage.delete("placeholder")
        self._set_status(
            "Searching for face", "Move into the camera frame to begin.", "missing", 10
        )
        self._camera_tick()

    def stop_monitoring(self):
        self.running = False
        self.closed_eyes_since = None
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        if self.face_mesh is not None:
            self.face_mesh.close()
            self.face_mesh = None
        self.camera_stage.delete("all")
        self.photo = None
        self.image_item = None
        self.camera_stage.create_text(
            20, 20, text="Your camera view lives here",
            fill="#dce2da", font=("Helvetica", 12, "bold"), anchor="nw",
            tags="placeholder",
        )
        self.camera_stage.create_text(
            20, 44, text="Start a session to enable face tracking.",
            fill="#78837b", font=("Helvetica", 10), anchor="nw",
            tags="placeholder",
        )
        self.camera_stage.create_text(
            12, max(12, self.camera_stage.winfo_height() - 12),
            text="●  LOCAL FEED  /  NO RECORDING",
            fill="#b6c0b8", font=("Menlo", 8), anchor="sw", tags="stamp",
        )
        self.live_label.configure(text="●  OFFLINE", fg="#76817a")
        self.session_label.configure(text="●  SYSTEM STANDBY", fg="#9ca59e")
        self.start_button.configure(
            state="normal", text="▶  Start monitoring  ↗",
            bg=LIME, fg="#15200d", activebackground="#d5ff91",
            activeforeground="#15200d",
        )
        self.camera_hint.configure(text="Position your face in the frame to begin.")
        self.eye_value.configure(text="—")
        self.eye_value.state_label.configure(text="WAITING", fg="#748078")
        self.face_value.configure(text="Inactive")
        self.face_value.state_label.configure(text="OFF", fg="#748078")
        self._set_status(
            "Ready when you are", "Start monitoring to see your live status.", "focused", 0
        )

    def _camera_tick(self):
        if not self.running or self.camera is None:
            return
        success, frame = self.camera.read()
        if not success:
            self.stop_monitoring()
            self.error_label.configure(
                text="The camera feed stopped unexpectedly. Check the camera connection and try again."
            )
            return

        frame = self.cv2.flip(frame, 1)
        rgb_frame = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB)
        result = self.face_mesh.process(rgb_frame)
        height, width = frame.shape[:2]
        now = time.monotonic()

        if result.multi_face_landmarks:
            landmarks = result.multi_face_landmarks[0].landmark
            self._draw_face(frame, landmarks, width, height)
            self._update_face_status(landmarks, width, height, now)
        else:
            self.closed_eyes_since = None
            self.eye_value.configure(text="Waiting for face")
            self.eye_value.state_label.configure(text="WAITING", fg="#748078")
            self.face_value.configure(text="Not detected")
            self.face_value.state_label.configure(text="SEARCHING", fg="#748078")
            self.camera_hint.configure(text="Move your face into the camera frame.")
            self._set_status(
                "Face not in view", "Move into the camera frame to resume monitoring.",
                "missing", 12,
            )

        self._show_frame(frame)
        self.root.after(25, self._camera_tick)

    @staticmethod
    def _eye_ratio(landmarks, indices, width, height):
        points = [
            (landmarks[index].x * width, landmarks[index].y * height)
            for index in indices
        ]

        def distance(first, second):
            return math.hypot(first[0] - second[0], first[1] - second[1])

        horizontal = distance(points[0], points[3])
        if horizontal == 0:
            return 1.0
        return (
            distance(points[1], points[5]) + distance(points[2], points[4])
        ) / (2.0 * horizontal)

    def _draw_face(self, frame, landmarks, width, height):
        points = [(int(point.x * width), int(point.y * height)) for point in landmarks]
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        pad_x = int((max(x_values) - min(x_values)) * 0.08)
        pad_y = int((max(y_values) - min(y_values)) * 0.08)
        color = (107, 243, 196)
        self.cv2.rectangle(
            frame,
            (max(0, min(x_values) - pad_x), max(0, min(y_values) - pad_y)),
            (min(width - 1, max(x_values) + pad_x), min(height - 1, max(y_values) + pad_y)),
            color,
            2,
        )
        for contour in EYE_CONTOURS:
            eye_points = [points[index] for index in contour]
            self.cv2.polylines(
                frame,
                [self.cv2.convexHull(self.np.array(eye_points, dtype="int32"))],
                True,
                color,
                1,
            )

    def _update_face_status(self, landmarks, width, height, now):
        left_ratio = self._eye_ratio(landmarks, LEFT_EYE, width, height)
        right_ratio = self._eye_ratio(landmarks, RIGHT_EYE, width, height)
        eyes_closed = (
            left_ratio < CLOSED_EYE_RATIO and right_ratio < CLOSED_EYE_RATIO
        )
        self.face_value.configure(text="Tracking")
        self.face_value.state_label.configure(text="ACTIVE", fg=LIME)
        self.camera_hint.configure(
            text="Face tracked on-device. Look ahead and drive safely."
        )

        if eyes_closed:
            if self.closed_eyes_since is None:
                self.closed_eyes_since = now
            duration = now - self.closed_eyes_since
            if duration >= CLOSED_EYE_DURATION:
                self.eye_value.configure(text="Closed — alert")
                self.eye_value.state_label.configure(text="CHECK IN", fg=AMBER)
                self._set_status(
                    "Eyes closed", "Please open your eyes and focus on the road.",
                    "warning", 88,
                )
                if now - self.last_alert_at >= ALERT_COOLDOWN:
                    self._speak("Please open your eyes and focus on the road.")
                    self.last_alert_at = now
            else:
                self.eye_value.configure(text="Closed")
                self.eye_value.state_label.configure(text="DETECTED", fg=AMBER)
                self._set_status(
                    "Stay focused", "Eyes closed. Alerting if they stay closed.",
                    "warning", 50,
                )
        else:
            self.closed_eyes_since = None
            self.eye_value.configure(text="Open")
            self.eye_value.state_label.configure(text="FOCUSED", fg=LIME)
            self._set_status(
                "Looking good", "Your eyes are open. Keep your attention on the road.",
                "focused", 100,
            )

    def _show_frame(self, frame):
        stage_width = max(1, self.camera_stage.winfo_width())
        stage_height = max(1, self.camera_stage.winfo_height())
        frame_height, frame_width = frame.shape[:2]
        scale = min(stage_width / frame_width, stage_height / frame_height)
        display_width = max(1, int(frame_width * scale))
        display_height = max(1, int(frame_height * scale))
        resized = self.cv2.resize(frame, (display_width, display_height))
        image = Image.fromarray(self.cv2.cvtColor(resized, self.cv2.COLOR_BGR2RGB))
        self.photo = ImageTk.PhotoImage(image)
        center_x, center_y = stage_width // 2, stage_height // 2
        if self.image_item is None:
            self.image_item = self.camera_stage.create_image(
                center_x, center_y, image=self.photo, anchor="center",
            )
        else:
            self.camera_stage.itemconfigure(self.image_item, image=self.photo)
            self.camera_stage.coords(self.image_item, center_x, center_y)

    def _set_status(self, title, description, level, attention):
        background, outline, indicator = {
            "focused": ("#19251a", "#35432d", LIME),
            "warning": ("#292116", "#70563a", AMBER),
            "missing": ("#1d211d", "#4c4036", "#9a8977"),
        }[level]
        self.status_box.configure(bg=background, highlightbackground=outline)
        self.status_dot.configure(bg=background, fg=indicator)
        for widget in self.status_box.winfo_children():
            if isinstance(widget, (tk.Frame, tk.Label)):
                widget.configure(bg=background)
                if isinstance(widget, tk.Frame):
                    for child in widget.winfo_children():
                        if isinstance(child, (tk.Frame, tk.Label)):
                            child.configure(bg=background)
        self.status_title.configure(text=title, bg=background)
        self.status_description.configure(text=description, bg=background)
        self.attention.configure(value=attention)
        if level != self.status_level:
            color = AMBER if level == "warning" else LIME
            ttk.Style().configure(
                "Roadwatch.Horizontal.TProgressbar",
                background=color, lightcolor=color, darkcolor=color,
            )
            self.status_level = level

    def _start_speech_worker(self):
        thread = threading.Thread(target=self._speech_worker, daemon=True)
        thread.start()

    def _speech_worker(self):
        try:
            import pyttsx3

            engine = pyttsx3.init()
            self.voice_events.put(("status", "Ready to speak"))
        except Exception as error:
            self.voice_events.put(("error", f"Voice alerts unavailable: {error}"))
            return

        while True:
            message = self.speech_queue.get()
            if message is None:
                return
            try:
                engine.say(message)
                engine.runAndWait()
                self.voice_events.put(("status", "Ready to speak"))
            except Exception as error:
                self.voice_events.put(("error", f"Could not play voice alert: {error}"))

    def _poll_voice_events(self):
        while True:
            try:
                kind, message = self.voice_events.get_nowait()
            except queue.Empty:
                break
            if kind == "error":
                self.voice_status.configure(text=message, fg=RED)
            else:
                self.voice_status.configure(text=message, fg="#a1aaa2")
        if self.root.winfo_exists():
            self.root.after(100, self._poll_voice_events)

    def _speak(self, message):
        self.voice_status.configure(text="Speaking alert…", fg=LIME)
        self.speech_queue.put(message)

    def close(self):
        self.stop_monitoring()
        self.speech_queue.put(None)
        self.root.destroy()


def main():
    root = tk.Tk()
    RoadwatchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
