"""
window_monitor.py
------------------
TabGuard AI — Active Window Tracker.

Polls the OS for the currently focused window title on a background
thread at a configurable rate (default ~30Hz) and forwards each change
to a callback along with its hazard classification. Uses pygetwindow
(cross-platform wrapper) so the same code path works on Windows/macOS;
Linux support depends on the pygetwindow backend available (Xlib/wmctrl).
"""

import platform
import threading
import time
from typing import Callable, Optional

from hazard_classifier import HazardClassifier, HazardMatch

try:
    import pygetwindow as gw
except Exception:
    # ImportError if the package isn't installed; some versions raise
    # NotImplementedError at import time on unsupported platforms (e.g.
    # Linux without an Xlib backend) instead of failing gracefully.
    gw = None


class WindowMonitor:
    def __init__(
        self,
        classifier: HazardClassifier,
        on_update: Callable[[str, HazardMatch], None],
        poll_hz: int = 30,
    ):
        self.classifier = classifier
        self.on_update = on_update
        self.poll_interval = 1.0 / poll_hz
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_title: Optional[str] = None
        self.platform = platform.system()
        self.backend_available = gw is not None

    def _get_active_title(self) -> Optional[str]:
        if gw is None:
            return None
        try:
            win = gw.getActiveWindow()
            return win.title if win else None
        except Exception:
            # Some backends throw on minimized/no-focus states; fail soft.
            return None

    def _loop(self) -> None:
        while self._running:
            title = self._get_active_title()
            if title != self._last_title:
                self._last_title = title
                match = self.classifier.classify(title or "")
                self.on_update(title or "", match)
            time.sleep(self.poll_interval)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
