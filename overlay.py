"""
overlay.py
----------
TabGuard AI — Visual Intercept Overlay.

Two intercept modes, both borderless / always-on-top / semi-transparent:

1. FULLSCREEN  — the original behavior. Covers the whole screen when the
   currently *focused* window itself is a hazard (e.g. WhatsApp Desktop is
   your active app).

2. REGION      — "Notification Sniping". Covers only the exact bounding
   box of a small, non-focused hazard window (e.g. a WhatsApp Web toast or
   a Slack notification popup) without touching anything else on screen.
   Multiple region overlays can be active simultaneously, each tracked by
   a stable key (window handle / id) supplied by the caller.

Nothing about the fullscreen path changes — show()/hide()/is_visible keep
their original signatures so existing call sites keep working untouched.
"""

import tkinter as tk

# Small buffer (px) added around a detected notification's bounding box so
# antialiased/shadowed toast edges never peek out from under the overlay.
REGION_PADDING = 4


class OverlayWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.top: tk.Toplevel | None = None            # fullscreen overlay
        self._trigger_label: tk.Label | None = None
        self._fullscreen_failsafe_job = None
        self.region_overlays: dict[str, tk.Toplevel] = {}   # key -> Toplevel
        self._region_failsafe_jobs: dict[str, object] = {}

    # ------------------------------------------------------------ fullscreen --
    def show(
        self,
        message: str = "TabGuard AI: Stream Paused Dynamically due to Security Protocol.",
        triggers: str = "",
    ) -> None:
        if self.top is not None:
            # Already showing — just refresh the trigger text.
            if triggers and self._trigger_label is not None:
                self._trigger_label.config(text=f"Detected signal: {triggers}")
            return

        self.top = tk.Toplevel(self.root)
        self.top.overrideredirect(True)          # borderless
        self.top.attributes("-topmost", True)     # always on top
        try:
            self.top.attributes("-alpha", 0.96)    # semi-transparent (Win/macOS)
        except tk.TclError:
            pass  # not supported on some Linux window managers — stays opaque

        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        self.top.geometry(f"{sw}x{sh}+0+0")
        self.top.configure(bg="#0b0f14")

        # --- Escape hatches: never let this overlay be undismissable -------
        self.top.bind("<Escape>", lambda e: self.hide())
        self.top.bind("<Button-1>", lambda e: self.hide())
        self.top.focus_force()
        # Hard failsafe: even if something above misfires, auto-clear after
        # 20s so a bug here can never lock up someone's screen indefinitely.
        self._fullscreen_failsafe_job = self.top.after(20000, self.hide)

        frame = tk.Frame(self.top, bg="#0b0f14")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        icon = tk.Label(frame, text="\U0001F6E1", font=("Segoe UI Emoji", 54),
                         bg="#0b0f14", fg="#3ddc97")
        icon.pack(pady=(0, 18))

        title = tk.Label(frame, text="TabGuard AI", font=("Segoe UI", 30, "bold"),
                          bg="#0b0f14", fg="#ffffff")
        title.pack()

        sub = tk.Label(frame, text=message, font=("Segoe UI", 14),
                        bg="#0b0f14", fg="#9aa5b1", wraplength=720, justify="center")
        sub.pack(pady=(12, 0))

        self._trigger_label = tk.Label(
            frame,
            text=f"Detected signal: {triggers}" if triggers else "",
            font=("Segoe UI", 10),
            bg="#0b0f14", fg="#e05263",
        )
        self._trigger_label.pack(pady=(16, 0))

        hint = tk.Label(frame, text="Press ESC or click anywhere to dismiss",
                          font=("Segoe UI", 9), bg="#0b0f14", fg="#5b6472")
        hint.pack(pady=(20, 0))

    def hide(self) -> None:
        if self.top is not None:
            if self._fullscreen_failsafe_job is not None:
                try:
                    self.top.after_cancel(self._fullscreen_failsafe_job)
                except Exception:
                    pass
                self._fullscreen_failsafe_job = None
            self.top.destroy()
            self.top = None
            self._trigger_label = None

    @property
    def is_visible(self) -> bool:
        return self.top is not None

    # ------------------------------------------------- region / notification --
    def show_region(
        self,
        key: str,
        x: int,
        y: int,
        width: int,
        height: int,
        triggers: str = "",
    ) -> None:
        """
        Snap a semi-transparent patch over exactly (x, y, width, height) —
        the bounding box of a detected notification toast — instead of the
        whole screen. `key` should be stable per source window (e.g. its
        native handle) so repeated calls for the same toast move/resize
        the existing patch rather than stacking duplicates.
        """
        x -= REGION_PADDING
        y -= REGION_PADDING
        width += REGION_PADDING * 2
        height += REGION_PADDING * 2

        win = self.region_overlays.get(key)
        if win is not None:
            # Toast moved (e.g. stacking notifications shifting) — reposition.
            win.geometry(f"{width}x{height}+{x}+{y}")
            return

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.configure(bg="#0b0f14")

        # Escape hatches, same as fullscreen: click to dismiss, and a hard
        # failsafe timeout so a stuck toast-overlay can't linger forever.
        win.bind("<Button-1>", lambda e, k=key: self.hide_region(k))
        self._region_failsafe_jobs[key] = win.after(15000, lambda k=key: self.hide_region(k))

        # Compact content — a toast is small, so scale text/icon down and
        # drop anything that would overflow at very small sizes.
        show_icon = height >= 70
        show_subtitle = width >= 220 and height >= 110

        frame = tk.Frame(win, bg="#0b0f14")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        if show_icon:
            tk.Label(frame, text="\U0001F6E1", font=("Segoe UI Emoji", 16),
                      bg="#0b0f14", fg="#3ddc97").pack()

        tk.Label(frame, text="Blocked", font=("Segoe UI", 11, "bold"),
                  bg="#0b0f14", fg="#ffffff").pack()

        if show_subtitle:
            tk.Label(frame, text=triggers or "TabGuard AI", font=("Segoe UI", 8),
                      bg="#0b0f14", fg="#9aa5b1", wraplength=max(width - 24, 40),
                      justify="center").pack(pady=(2, 0))

        self.region_overlays[key] = win

    def hide_region(self, key: str) -> None:
        win = self.region_overlays.pop(key, None)
        job = self._region_failsafe_jobs.pop(key, None)
        if job is not None and win is not None:
            try:
                win.after_cancel(job)
            except Exception:
                pass
        if win is not None:
            win.destroy()

    def hide_stale_regions(self, active_keys: set) -> None:
        """Destroy any region overlay whose source toast is no longer present."""
        for key in list(self.region_overlays.keys()):
            if key not in active_keys:
                self.hide_region(key)

    def hide_all_regions(self) -> None:
        for key in list(self.region_overlays.keys()):
            self.hide_region(key)

    @property
    def active_region_keys(self) -> set:
        return set(self.region_overlays.keys())