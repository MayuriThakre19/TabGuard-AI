"""
main.py
-------
TabGuard AI — Entry point.

Wires together:
  - HazardClassifier   (hazard_classifier.py)  -> semantic keyword scoring
  - WindowMonitor       (window_monitor.py)     -> background title polling
  - OverlayWindow        (overlay.py)            -> intercept canvas
  - TabGuardApp (this file)                      -> control dashboard + tray

Run:  python main.py
"""

import queue
import threading
import tkinter as tk

from hazard_classifier import HazardClassifier, HazardMatch
from window_monitor import WindowMonitor
from overlay import OverlayWindow

try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except Exception:
    # ImportError if not installed; pystray can also raise other errors
    # (e.g. ValueError) when no supported tray backend is present on the
    # desktop (some minimal Linux setups without AppIndicator/GTK).
    TRAY_AVAILABLE = False

try:
    import pygetwindow as gw
except Exception:
    # Same rationale as window_monitor.py — catch NotImplementedError too.
    gw = None

# A window is treated as a "notification toast" (region-blur target) rather
# than a real application window (fullscreen target) if it's smaller than
# this on both axes. Tuned around real-world toast sizes: Windows Action
# Center ~360x160, Slack popup ~380x120, macOS banners ~360x80.
NOTIFICATION_MAX_WIDTH = 420
NOTIFICATION_MAX_HEIGHT = 280
NOTIFICATION_SCAN_MS = 120  # ~8Hz — enumerating *all* windows is heavier
                            # than polling the single active window, so this
                            # runs on its own, slower cadence.


def _iter_all_windows():
    """
    Yield every visible top-level window on the desktop (not just the
    focused one) — required to catch notification toasts, which almost
    never take keyboard focus and so are invisible to the active-window
    poll alone.
    """
    if gw is None:
        return
    try:
        windows = gw.getAllWindows()
    except AttributeError:
        # Older pygetwindow builds on some backends only expose title-based
        # lookup rather than a direct getAllWindows().
        windows = []
        for t in gw.getAllTitles():
            if t:
                windows.extend(gw.getWindowsWithTitle(t))
    for win in windows:
        yield win


def _window_key(win) -> str:
    """A stable-ish identity for a window across polls."""
    handle = getattr(win, "_hWnd", None)
    if handle is not None:
        return f"hwnd:{handle}"
    return f"geom:{win.title}:{win.left}:{win.top}:{win.width}:{win.height}"


class TabGuardApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TabGuard AI — Control Dashboard")
        self.root.geometry("480x600")
        self.root.minsize(440, 560)
        self.root.configure(bg="#111721")
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        self.classifier = HazardClassifier()
        self.overlay = OverlayWindow(self.root)
        self.event_queue: "queue.Queue" = queue.Queue()
        self.monitor = WindowMonitor(self.classifier, self._on_window_update, poll_hz=30)

        self.monitoring_enabled = True
        self.current_risk = 0
        self.smoothed_risk = 0.0

        self.tray_icon = None

        self._build_ui()
        if not self.monitor.backend_available:
            self._warn_no_backend()

        self._poll_queue()
        self.monitor.start()

        if gw is not None:
            self.root.after(NOTIFICATION_SCAN_MS, self._scan_notification_windows)

        if TRAY_AVAILABLE:
            self._setup_tray()

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        header = tk.Frame(self.root, bg="#111721")
        header.pack(fill="x", pady=(18, 6), padx=20)
        tk.Label(header, text="\U0001F6E1 TabGuard AI", font=("Segoe UI", 20, "bold"),
                 bg="#111721", fg="#3ddc97").pack(anchor="w")
        tk.Label(header, text="On-device Semantic Buffer Interceptor",
                 font=("Segoe UI", 10), bg="#111721", fg="#9aa5b1").pack(anchor="w")

        status_frame = tk.Frame(self.root, bg="#1b2432", padx=14, pady=12)
        status_frame.pack(fill="x", padx=20, pady=10)
        self.status_label = tk.Label(status_frame, text="\u25CF Monitoring Active",
                                      font=("Segoe UI", 11, "bold"), bg="#1b2432", fg="#3ddc97")
        self.status_label.pack(anchor="w")
        self.title_label = tk.Label(status_frame, text="Active window: \u2014",
                                     font=("Segoe UI", 9), bg="#1b2432", fg="#9aa5b1",
                                     wraplength=420, justify="left")
        self.title_label.pack(anchor="w", pady=(4, 0))

        risk_frame = tk.Frame(self.root, bg="#111721")
        risk_frame.pack(fill="x", padx=20, pady=(10, 0))
        tk.Label(risk_frame, text="Live Hazard Risk Meter", font=("Segoe UI", 10, "bold"),
                 bg="#111721", fg="#ffffff").pack(anchor="w")
        self.risk_canvas = tk.Canvas(risk_frame, height=22, bg="#1b2432", highlightthickness=0)
        self.risk_canvas.pack(fill="x", pady=6)
        self.risk_pct_label = tk.Label(risk_frame, text="0%", font=("Segoe UI", 9),
                                        bg="#111721", fg="#9aa5b1")
        self.risk_pct_label.pack(anchor="e")

        kw_frame = tk.Frame(self.root, bg="#111721")
        kw_frame.pack(fill="both", expand=True, padx=20, pady=(10, 0))
        tk.Label(kw_frame, text="Custom Hazard Keywords", font=("Segoe UI", 10, "bold"),
                 bg="#111721", fg="#ffffff").pack(anchor="w")

        entry_row = tk.Frame(kw_frame, bg="#111721")
        entry_row.pack(fill="x", pady=6)
        self.kw_entry = tk.Entry(entry_row, bg="#1b2432", fg="#ffffff",
                                  insertbackground="#ffffff", relief="flat")
        self.kw_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))
        self.kw_entry.bind("<Return>", lambda e: self._add_keyword())
        tk.Button(entry_row, text="Add", command=self._add_keyword,
                  bg="#3ddc97", fg="#0b0f14", relief="flat", padx=10).pack(side="left")

        list_row = tk.Frame(kw_frame, bg="#111721")
        list_row.pack(fill="both", expand=True)
        self.kw_listbox = tk.Listbox(list_row, bg="#1b2432", fg="#ffffff", relief="flat",
                                      selectbackground="#3ddc97", selectforeground="#0b0f14")
        self.kw_listbox.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_row, command=self.kw_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.kw_listbox.config(yscrollcommand=scrollbar.set)
        self._refresh_keyword_list()

        tk.Button(kw_frame, text="Remove Selected", command=self._remove_keyword,
                  bg="#e05263", fg="#ffffff", relief="flat").pack(anchor="w", pady=6)

        ctrl_frame = tk.Frame(self.root, bg="#111721")
        ctrl_frame.pack(fill="x", padx=20, pady=(6, 16))
        self.toggle_btn = tk.Button(ctrl_frame, text="Pause Monitoring",
                                     command=self._toggle_monitoring,
                                     bg="#1b2432", fg="#ffffff", relief="flat", padx=10, pady=6)
        self.toggle_btn.pack(side="left")
        tk.Button(ctrl_frame, text="Test Overlay", command=lambda: self.overlay.show(),
                  bg="#1b2432", fg="#ffffff", relief="flat", padx=10, pady=6).pack(side="left", padx=8)
        tk.Button(ctrl_frame, text="Hide Overlay", command=self._hide_all_overlays,
                  bg="#1b2432", fg="#ffffff", relief="flat", padx=10, pady=6).pack(side="left")

        ctrl_frame2 = tk.Frame(self.root, bg="#111721")
        ctrl_frame2.pack(fill="x", padx=20, pady=(0, 16))
        tk.Button(ctrl_frame2, text="Test Region Blur (bottom-right toast)",
                  command=self._test_region_overlay,
                  bg="#1b2432", fg="#ffffff", relief="flat", padx=10, pady=6).pack(side="left")

        self._draw_risk_bar(0)

    def _hide_all_overlays(self):
        self.overlay.hide()
        self.overlay.hide_all_regions()

    def _test_region_overlay(self):
        """Simulates a notification toast at a typical bottom-right position."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 360, 140
        x, y = sw - w - 24, sh - h - 60
        self.overlay.show_region("demo-toast", x, y, w, h, triggers="demo notification")
        self.root.after(4000, lambda: self.overlay.hide_region("demo-toast"))

    def _warn_no_backend(self):
        self.status_label.config(
            text="\u26A0 No window backend found — install pygetwindow", fg="#e05263"
        )

    def _draw_risk_bar(self, pct: int):
        self.risk_canvas.delete("all")
        w = self.risk_canvas.winfo_width() or 420
        h = 22
        color = "#3ddc97" if pct < 40 else "#f2c14e" if pct < 75 else "#e05263"
        self.risk_canvas.create_rectangle(0, 0, w, h, fill="#1b2432", outline="")
        self.risk_canvas.create_rectangle(0, 0, int(w * pct / 100), h, fill=color, outline="")
        self.risk_pct_label.config(text=f"{pct}%")

    def _refresh_keyword_list(self):
        self.kw_listbox.delete(0, "end")
        for kw, score in sorted(self.classifier.keywords.items(), key=lambda x: -x[1]):
            self.kw_listbox.insert("end", f"{kw}  (severity {score})")

    def _add_keyword(self):
        kw = self.kw_entry.get().strip()
        if kw:
            self.classifier.add_keyword(kw)
            self.kw_entry.delete(0, "end")
            self._refresh_keyword_list()

    def _remove_keyword(self):
        sel = self.kw_listbox.curselection()
        if not sel:
            return
        text = self.kw_listbox.get(sel[0])
        kw = text.split("  (")[0]
        self.classifier.remove_keyword(kw)
        self._refresh_keyword_list()

    def _toggle_monitoring(self):
        self.monitoring_enabled = not self.monitoring_enabled
        if self.monitoring_enabled:
            self.toggle_btn.config(text="Pause Monitoring")
            self.status_label.config(text="\u25CF Monitoring Active", fg="#3ddc97")
        else:
            self.toggle_btn.config(text="Resume Monitoring")
            self.status_label.config(text="\u25CF Monitoring Paused", fg="#f2c14e")
            self.overlay.hide()
            self.overlay.hide_all_regions()

    # --------------------------------------------- background -> UI bridge --
    def _on_window_update(self, title: str, match: HazardMatch):
        # Called from the monitor's background thread — never touch Tk here.
        self.event_queue.put((title, match))

    def _poll_queue(self):
        try:
            while True:
                title, match = self.event_queue.get_nowait()
                self._handle_update(title, match)
        except queue.Empty:
            pass

        self.smoothed_risk += (self.current_risk - self.smoothed_risk) * 0.3
        self._draw_risk_bar(int(self.smoothed_risk))
        self.root.after(66, self._poll_queue)  # ~15 UI fps for the meter/log

    def _handle_update(self, title: str, match: HazardMatch):
        display_title = title if len(title) < 80 else title[:77] + "..."
        self.title_label.config(text=f"Active window: {display_title or '-'}")
        self.current_risk = match.score if match.matched else max(0, self.current_risk - 20)

        if not self.monitoring_enabled:
            return

        if match.matched:
            self.overlay.show(triggers=", ".join(match.triggers))
            self.status_label.config(
                text=f"\u26A0 Hazard Intercepted: {', '.join(match.triggers)}", fg="#e05263"
            )
        else:
            self.overlay.hide()
            self.status_label.config(text="\u25CF Monitoring Active", fg="#3ddc97")

    # ------------------------------------------ notification sniping scan --
    def _scan_notification_windows(self):
        """
        Runs on the Tk main thread via root.after (safe to touch overlays
        directly — no queue needed here, unlike the background-thread
        active-window monitor). Enumerates every top-level window, finds
        ones that are (a) a hazard match and (b) small enough to be a
        notification toast rather than a real app window, and positions a
        tightly-cropped overlay over each one's exact bounding box.
        """
        if self.monitoring_enabled and gw is not None:
            active_keys = set()
            try:
                active_win = gw.getActiveWindow()
                active_title = active_win.title if active_win else None

                for win in _iter_all_windows():
                    title = getattr(win, "title", "") or ""
                    if not title or title == active_title:
                        continue  # no title, or it's the focused window —
                                  # that case is already handled as fullscreen
                    if getattr(win, "visible", True) is False:
                        continue
                    if win.width <= 0 or win.height <= 0:
                        continue
                    if win.width > NOTIFICATION_MAX_WIDTH or win.height > NOTIFICATION_MAX_HEIGHT:
                        continue  # too big to be a toast — leave it alone

                    match = self.classifier.classify(title)
                    if not match.matched:
                        continue

                    key = _window_key(win)
                    active_keys.add(key)
                    self.overlay.show_region(
                        key, win.left, win.top, win.width, win.height,
                        triggers=", ".join(match.triggers),
                    )
                    self.current_risk = max(self.current_risk, match.score)
            except Exception:
                # Any transient OS/window-enumeration error should never
                # crash the monitor loop — just skip this tick.
                pass

            self.overlay.hide_stale_regions(active_keys)
        else:
            self.overlay.hide_all_regions()

        self.root.after(NOTIFICATION_SCAN_MS, self._scan_notification_windows)

    # --------------------------------------------------------- system tray --
    def _make_tray_image(self):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.polygon([(32, 4), (58, 16), (58, 34), (32, 60), (6, 34), (6, 16)],
                   fill=(61, 220, 151, 255))
        d.polygon([(32, 12), (50, 20), (50, 33), (32, 52), (14, 33), (14, 20)],
                   fill=(11, 15, 20, 255))
        return img

    def _setup_tray(self):
        image = self._make_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Show Dashboard", self._show_window, default=True),
            pystray.MenuItem("Pause/Resume", lambda icon=None, item=None: self.root.after(0, self._toggle_monitoring)),
            pystray.MenuItem("Quit", self._quit_app),
        )
        self.tray_icon = pystray.Icon("TabGuardAI", image, "TabGuard AI", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _show_window(self, icon=None, item=None):
        self.root.after(0, self.root.deiconify)

    def minimize_to_tray(self):
        if TRAY_AVAILABLE:
            self.root.withdraw()
        else:
            self._quit_app()

    def _quit_app(self, icon=None, item=None):
        self.monitor.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = TabGuardApp()
    app.run()