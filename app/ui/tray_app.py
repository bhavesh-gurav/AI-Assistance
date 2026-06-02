"""Full-screen neural-network UI for JARVIS (CustomTkinter + Canvas).

Combines two visual ideas into one immersive, full-screen scene:

* a big **layered neural network** whose nodes light up as pulses of
  "information" flow left-to-right through it, and
* a central **orbiting core orb** (rotating satellite nodes + pulsing halo) that
  the network appears to converge into.

Colour, speed and pulse density react to the assistant's state:

    idle      -> dim blue, slow trickle
    listening -> cyan, steady flow
    wake      -> bright white burst
    thinking  -> purple, dense fast flow
    speaking  -> green, lively flow
    error     -> red

Controls (status, transcript, text box, buttons) float as overlays on top of
the canvas. Background-thread updates are marshalled onto the Tk main loop
through a thread-safe queue polled with ``after``.
"""

from __future__ import annotations

import math
import queue
import random
import threading
from typing import Any

from app.config.logger import get_logger
from app.config.settings import settings
from app.core.assistant import Assistant
from app.core.voice_engine import VoiceEngine

logger = get_logger(__name__)

try:
    import customtkinter as ctk
    import tkinter as tk
except Exception:  # pragma: no cover
    ctk = None  # type: ignore[assignment]
    tk = None  # type: ignore[assignment]


# state -> (bright core RGB, dim node RGB, base flow speed, active pulse count, orbit rotation)
STATE_STYLE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], float, int, float]] = {
    "idle":      ((90, 120, 200),  (26, 36, 66),   0.010, 26, 0.004),
    "listening": ((0, 217, 255),   (10, 60, 80),   0.020, 46, 0.010),
    "wake":      ((255, 255, 255), (120, 200, 230), 0.045, 80, 0.022),
    "thinking":  ((180, 90, 240),  (45, 25, 70),   0.040, 80, 0.030),
    "speaking":  ((0, 255, 160),   (10, 70, 55),   0.028, 64, 0.014),
    "error":     ((255, 80, 80),   (70, 25, 25),   0.012, 20, 0.004),
}

LAYER_SIZES = [6, 9, 13, 9, 5]   # deep feed-forward network
BG = (7, 11, 22)                 # canvas background #070b16
ORBIT_NODES = 10


def _hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, int(v))) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[float, float, float]:
    t = max(0.0, min(1.0, t))
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


class FlowNetwork:
    """Layered flow network + central orbiting core, sized to the canvas."""

    def __init__(self, canvas: "tk.Canvas", width: int, height: int) -> None:
        self.canvas = canvas
        self.state = "idle"
        self.frame = 0
        self.angle = 0.0
        self.sizes = LAYER_SIZES
        self.n_layers = len(self.sizes)
        self._orbit_offsets = [i * (2 * math.pi / ORBIT_NODES) for i in range(ORBIT_NODES)]
        self.pulses = [self._new_pulse(layer=0) for _ in range(80)]
        self.recompute(width, height)

    # -- layout -------------------------------------------------------------
    def recompute(self, width: int, height: int) -> None:
        self.w = max(640, width)
        self.h = max(400, height)
        margin_x = self.w * 0.07
        margin_y = self.h * 0.12
        usable_w = self.w - 2 * margin_x

        self.nodes: list[list[tuple[float, float]]] = []
        for li, count in enumerate(self.sizes):
            x = margin_x + (usable_w * li / (self.n_layers - 1))
            layer = []
            for ni in range(count):
                y = self.h / 2 if count == 1 else margin_y + (self.h - 2 * margin_y) * ni / (count - 1)
                layer.append((x, y))
            self.nodes.append(layer)

        self.edges: list[tuple[float, float, float, float]] = []
        for li in range(self.n_layers - 1):
            for (x1, y1) in self.nodes[li]:
                for (x2, y2) in self.nodes[li + 1]:
                    self.edges.append((x1, y1, x2, y2))

        self.activation = [[0.0] * c for c in self.sizes]
        self.center = (self.w / 2, self.h / 2)
        self.orbit_r = min(self.w, self.h) * 0.16

    def _new_pulse(self, layer: int) -> dict:
        return {"layer": layer, "src": random.randrange(self.sizes[layer]),
                "dst": random.randrange(self.sizes[layer + 1]),
                "t": random.random(), "sp": 0.6 + random.random() * 0.9}

    def set_state(self, state: str) -> None:
        if state in STATE_STYLE:
            self.state = state

    # -- animation ----------------------------------------------------------
    def tick(self) -> None:
        core, dim_node, base_speed, active_count, rot = STATE_STYLE.get(self.state, STATE_STYLE["idle"])
        self.frame += 1
        self.angle += rot
        c = self.canvas
        c.delete("all")

        edge_color = _hex(_lerp(BG, core, 0.14))
        for li in range(self.n_layers):
            row = self.activation[li]
            for ni in range(len(row)):
                row[ni] *= 0.86

        for (x1, y1, x2, y2) in self.edges:
            c.create_line(x1, y1, x2, y2, fill=edge_color, width=1)

        self._draw_pulses(c, core, base_speed, active_count)
        self._draw_nodes(c, core, dim_node)
        self._draw_core(c, core)

    def _draw_pulses(self, c, core, base_speed, active_count) -> None:
        trail_color = _hex(_lerp(BG, core, 0.7))
        head_color = _hex(core)
        for idx, p in enumerate(self.pulses):
            if idx >= active_count:
                continue
            p["t"] += base_speed * p["sp"]
            while p["t"] >= 1.0:
                p["t"] -= 1.0
                arrived = p["layer"] + 1
                self.activation[arrived][p["dst"]] = 1.0
                if arrived < self.n_layers - 1:
                    p["layer"] = arrived
                    p["src"] = p["dst"]
                    p["dst"] = random.randrange(self.sizes[arrived + 1])
                else:
                    p["layer"] = 0
                    p["src"] = random.randrange(self.sizes[0])
                    p["dst"] = random.randrange(self.sizes[1])
                self.activation[p["layer"]][p["src"]] = max(self.activation[p["layer"]][p["src"]], 0.7)

            x1, y1 = self.nodes[p["layer"]][p["src"]]
            x2, y2 = self.nodes[p["layer"] + 1][p["dst"]]
            t = p["t"]
            px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
            tt = max(0.0, t - 0.12)
            tx, ty = x1 + (x2 - x1) * tt, y1 + (y2 - y1) * tt
            c.create_line(tx, ty, px, py, fill=trail_color, width=2)
            c.create_oval(px - 3, py - 3, px + 3, py + 3, fill=head_color, outline="")

    def _draw_nodes(self, c, core, dim_node) -> None:
        for li in range(self.n_layers):
            for ni, (x, y) in enumerate(self.nodes[li]):
                act = self.activation[li][ni]
                base_glow = 0.12 + 0.06 * math.sin(self.frame * 0.05 + li + ni)
                level = max(base_glow, act)
                color = _hex(_lerp(dim_node, core, level))
                r = 6 + 6 * act
                if act > 0.25:
                    hr = r + 5 + 5 * act
                    c.create_oval(x - hr, y - hr, x + hr, y + hr, outline=_hex(_lerp(BG, core, 0.4)), width=1)
                c.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=_hex(_lerp(dim_node, core, 0.5)))

    def _draw_core(self, c, core) -> None:
        cx, cy = self.center
        ring = _hex(_lerp(BG, core, 0.5))
        # Orbiting satellite nodes (from the original orb design).
        orbit_pts = []
        for off in self._orbit_offsets:
            a = self.angle + off
            r = self.orbit_r + 6 * math.sin(self.frame * 0.08 + off * 1.7)
            x = cx + r * math.cos(a)
            y = cy + (r * 0.6) * math.sin(a)
            orbit_pts.append((x, y))
        for i, (x, y) in enumerate(orbit_pts):
            c.create_line(cx, cy, x, y, fill=ring, width=1)
            nx, ny = orbit_pts[(i + 1) % len(orbit_pts)]
            c.create_line(x, y, nx, ny, fill=ring, width=1)
        for (x, y) in orbit_pts:
            c.create_oval(x - 5, y - 5, x + 5, y + 5, fill=_hex(core), outline=ring)
        # Pulsing halo + core.
        pulse = 0.5 + 0.5 * math.sin(self.frame * 0.10)
        for k in range(4, 0, -1):
            rr = 30 + k * 10 + pulse * 8
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=_hex(_lerp(BG, core, 0.18 * k)), width=1)
        core_r = 24 + 4 * pulse
        c.create_oval(cx - core_r, cy - core_r, cx + core_r, cy + core_r, fill=_hex(core), outline=ring, width=2)


class JarvisApp:
    """Full-screen CustomTkinter front-end with the combined visualizer."""

    def __init__(self) -> None:
        if ctk is None:
            raise RuntimeError("customtkinter is not installed. Run `pip install customtkinter`.")

        self.assistant = Assistant()
        self._ui_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self.voice = VoiceEngine(
            self.assistant,
            on_status=lambda s: self._ui_queue.put(("status", s)),
            on_transcript=lambda role, text: self._ui_queue.put(("transcript", (role, text))),
            on_state=lambda st: self._ui_queue.put(("state", st)),
        )

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.root = ctk.CTk()
        self.root.title(f"{settings.assistant_name} — Neural Assistant")
        self.root.configure(fg_color="#070b16")
        self._fullscreen = True
        self.root.attributes("-fullscreen", True)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry(f"{sw}x{sh}+0+0")

        self._build_widgets(sw, sh)
        self.root.bind("<Escape>", lambda _e: self._toggle_fullscreen())
        self.root.after(100, self._drain_queue)
        self.root.after(40, self._animate)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- layout -------------------------------------------------------------
    def _build_widgets(self, sw: int, sh: int) -> None:
        # Full-screen canvas as the background.
        self.canvas = tk.Canvas(self.root, width=sw, height=sh, bg="#070b16", highlightthickness=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.viz = FlowNetwork(self.canvas, sw, sh)

        # Title (top center overlay).
        self.title_label = ctk.CTkLabel(
            self.root, text=f"◉  {settings.assistant_name.upper()}",
            font=ctk.CTkFont(family="Consolas", size=34, weight="bold"), text_color="#00d9ff",
            fg_color="#070b16",
        )
        self.title_label.place(relx=0.5, rely=0.04, anchor="center")

        self.status_var = ctk.StringVar(value="Press Activate Voice — then just speak.")
        self.status_label = ctk.CTkLabel(
            self.root, textvariable=self.status_var,
            font=ctk.CTkFont(family="Consolas", size=15), text_color="#7fe9ff", fg_color="#070b16",
        )
        self.status_label.place(relx=0.5, rely=0.095, anchor="center")

        # Bottom overlay panel: transcript + entry + buttons.
        panel = ctk.CTkFrame(self.root, fg_color="#0a1020", border_color="#1d2747", border_width=1, corner_radius=14)
        panel.place(relx=0.5, rely=0.99, anchor="s", relwidth=0.7)

        self.log = ctk.CTkTextbox(
            panel, height=170, wrap="word", fg_color="#0c1326", text_color="#cfe8ff",
            border_color="#1d2747", border_width=1, font=ctk.CTkFont(family="Consolas", size=13),
        )
        self.log.pack(padx=14, pady=(14, 8), fill="both", expand=True)
        self.log.configure(state="disabled")

        entry_row = ctk.CTkFrame(panel, fg_color="transparent")
        entry_row.pack(fill="x", padx=14, pady=(0, 8))
        self.entry = ctk.CTkEntry(entry_row, placeholder_text="Type a command and press Enter...",
                                  fg_color="#0c1326", border_color="#1d2747")
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda _e: self._send_text())
        ctk.CTkButton(entry_row, text="Send", width=80, command=self._send_text,
                      fg_color="#1d3a8a", hover_color="#274ec0").pack(side="right")

        button_row = ctk.CTkFrame(panel, fg_color="transparent")
        button_row.pack(fill="x", padx=14, pady=(0, 14))
        self.listen_btn = ctk.CTkButton(
            button_row, text="🎙  Activate Voice", command=self._toggle_voice,
            fg_color="#0a7d5a", hover_color="#0fa377", height=40, font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.listen_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self.ptt_btn = ctk.CTkButton(
            button_row, text="🔘  Listen Now", command=self._push_to_talk, width=130, height=40,
            fg_color="#1d3a8a", hover_color="#274ec0", font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.ptt_btn.pack(side="left", padx=(0, 8))
        ctk.CTkButton(button_row, text="Clear", width=70, command=self._clear_log,
                      fg_color="#33203a", hover_color="#4a2e57").pack(side="left", padx=(0, 8))
        ctk.CTkButton(button_row, text="✕ Exit", width=70, command=self._on_close,
                      fg_color="#5a1d1d", hover_color="#7a2727").pack(side="right")

        if not settings.is_configured:
            self._append("system", "⚠ GEMINI_API_KEY not set. Local commands work; AI answers need a key.")

    def _on_canvas_resize(self, event) -> None:  # noqa: ANN001
        if event.width > 100 and event.height > 100:
            self.viz.recompute(event.width, event.height)

    # -- actions ------------------------------------------------------------
    def _toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        self.root.attributes("-fullscreen", self._fullscreen)

    def _toggle_voice(self) -> None:
        if self.voice.running:
            self.voice.stop()
            self.listen_btn.configure(text="🎙  Activate Voice", fg_color="#0a7d5a", hover_color="#0fa377")
            self.status_var.set("Stopped.")
            self.viz.set_state("idle")
        else:
            self.voice.start()
            self.listen_btn.configure(text="⏹  Stop Listening", fg_color="#8a1d1d", hover_color="#b02727")

    def _push_to_talk(self) -> None:
        self.assistant.on_speak = self.voice.speak
        threading.Thread(target=self.voice.listen_once, daemon=True).start()

    def _send_text(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._append("user", text)
        self.assistant.on_speak = self.voice.speak

        def worker() -> None:
            self._ui_queue.put(("state", "thinking"))
            result = self.assistant.process_text(text)
            speech = result.get("speech", "")
            if speech:
                self._ui_queue.put(("transcript", ("assistant", speech)))
            self._ui_queue.put(("state", "listening" if self.voice.running else "idle"))

        threading.Thread(target=worker, daemon=True).start()

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # -- queue / rendering --------------------------------------------------
    def _drain_queue(self) -> None:
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "state":
                    self.viz.set_state(str(payload))
                elif kind == "transcript":
                    role, text = payload
                    self._append(role, text)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def _animate(self) -> None:
        try:
            self.viz.tick()
        except Exception:
            logger.debug("viz tick failed", exc_info=True)
        self.root.after(40, self._animate)

    def _append(self, role: str, text: str) -> None:
        prefix = {"user": "You", "assistant": settings.assistant_name, "system": "System"}.get(role, role.title())
        self.log.configure(state="normal")
        self.log.insert("end", f"❯ {prefix}: {text}\n\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        self.voice.stop()
        try:
            self.voice.tts.shutdown()
        except Exception:
            pass
        self.assistant.shutdown()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
