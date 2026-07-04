"""
Singleton host that runs pywebview (WebView2 / EdgeChromium) in a background
STA daemon thread.

pywebview.start() guards against non-main threads by checking
threading.current_thread().name != 'MainThread', but WebView2 / WinForms only
requires a COM STA (Single Threaded Apartment) thread – not specifically the
OS process main thread.  We:
  1. Mark the background thread as STA via CoInitializeEx.
  2. Rename the background thread to 'MainThread' so pywebview's guard passes.
Qt owns its own Win32 message loop on the main thread; WinForms runs its own
loop on the STA thread – the two coexist without conflict.
"""
from __future__ import annotations

import ctypes
import logging
import threading

logger = logging.getLogger(__name__)

_COINIT_APARTMENTTHREADED = 0x2

_host: "_WebviewHost | None" = None
_host_lock = threading.Lock()


class _WebviewHost:
    def __init__(self):
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="WebviewHost"
        )
        self._thread.start()
        if not self._ready.wait(timeout=30):
            logger.error("WebviewHost: timed out waiting for WebView2 to start")
        else:
            logger.debug("WebviewHost: WebView2 ready")

    def _run(self):
        # Make this thread a COM STA thread (required by WinForms / WebView2).
        ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)

        import webview

        # ---- bypass pywebview's main-thread guard -------------------------
        # pywebview does:
        #   if threading.current_thread().name != 'MainThread': raise
        # Renaming this thread makes the guard pass on any thread.
        threading.current_thread().name = "MainThread"

        def _on_ready():
            self._ready.set()

        try:
            # webview.start() requires at least one window to already exist
            # (it indexes windows[0]) - create a hidden master window to
            # satisfy that before entering the GUI loop. Real per-session
            # windows are created later by TerminalPanel.load_session().
            webview.create_window("neoterm-host", html="", hidden=True)
            webview.start(func=_on_ready, gui="edgechromium", debug=False)
        except Exception as exc:
            logger.error("WebviewHost: webview.start() failed: %s", exc)
        finally:
            ctypes.windll.ole32.CoUninitialize()


def get_webview_host() -> _WebviewHost:
    """Return (and lazily start) the singleton WebviewHost."""
    global _host
    if _host is None:
        with _host_lock:
            if _host is None:
                _host = _WebviewHost()
    return _host