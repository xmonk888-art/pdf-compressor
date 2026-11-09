"""Native Windows file drops for this application's own Tk windows only.

References: Microsoft WM_DROPFILES, DragQueryFileW and SetWindowLongPtrW docs.
No hooks into other processes; no file moves or copies are performed on drop.
"""
from __future__ import annotations

from pathlib import Path
import ctypes
from ctypes import wintypes
import queue
import sys


def expand_dropped_paths(names):
    """Accept files plus direct PDF children of dropped folders; deduplicate."""
    results, seen = [], set()
    for name in names:
        path = Path(name)
        try:
            candidates = sorted(path.iterdir(), key=lambda p: p.name.casefold()) if path.is_dir() else [path]
            for candidate in candidates:
                if not candidate.is_file() or candidate.suffix.casefold() != '.pdf':
                    continue
                candidate = candidate.resolve()
                key = str(candidate).casefold() if sys.platform == 'win32' else str(candidate)
                if key not in seen:
                    seen.add(key)
                    results.append(str(candidate))
        except OSError:
            continue
    return results


class WindowsFileDrop:
    """Receive file drops and dispatch them later through the Tk event loop."""
    WM_DROPFILES = 0x0233
    GWLP_WNDPROC = -4
    GA_ROOT = 2

    def __init__(self, root, callback):
        self.root, self.callback = root, callback
        self.enabled, self.closed = False, False
        self.pending = queue.SimpleQueue()
        self.originals = {}
        self.timer = None
        if sys.platform != 'win32':
            return
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.shell32 = ctypes.WinDLL('shell32', use_last_error=True)
        result = ctypes.c_ssize_t
        self.proc_type = ctypes.WINFUNCTYPE(result, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.enum_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user32.GetAncestor.restype = wintypes.HWND
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.IsWindow.restype = wintypes.BOOL
        self.user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        self.user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        self.user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        self.user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user32.CallWindowProcW.restype = result
        self.user32.EnumChildWindows.argtypes = [wintypes.HWND, self.enum_type, wintypes.LPARAM]
        self.user32.EnumChildWindows.restype = wintypes.BOOL
        self.shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        self.shell32.DragAcceptFiles.restype = None
        self.shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        self.shell32.DragQueryFileW.restype = wintypes.UINT
        self.shell32.DragFinish.argtypes = [wintypes.HANDLE]
        self.shell32.DragFinish.restype = None
        self.native_proc = self.proc_type(self._window_proc)
        self.native_address = ctypes.cast(self.native_proc, ctypes.c_void_p).value
        self.root.update_idletasks()
        self.hwnd = self.user32.GetAncestor(self.root.winfo_id(), self.GA_ROOT)
        if not self.hwnd:
            raise RuntimeError('无法定位程序自身窗口')
        handles = [self.hwnd]

        @self.enum_type
        def collect(hwnd, unused):
            handles.append(hwnd)
            return True

        self.user32.EnumChildWindows(self.hwnd, collect, 0)
        try:
            for hwnd in dict.fromkeys(handles):
                ctypes.set_last_error(0)
                old = self.user32.SetWindowLongPtrW(hwnd, self.GWLP_WNDPROC, self.native_address)
                if not old:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.originals[hwnd] = old
                self.shell32.DragAcceptFiles(hwnd, True)
            self.enabled = True
            self.timer = self.root.after(60, self._drain)
        except Exception:
            self.close()
            raise

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == self.WM_DROPFILES:
            try:
                count = self.shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                names = []
                for index in range(count):
                    length = self.shell32.DragQueryFileW(wparam, index, None, 0)
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    self.shell32.DragQueryFileW(wparam, index, buffer, length + 1)
                    names.append(buffer.value)
                self.pending.put(names)
            finally:
                self.shell32.DragFinish(wparam)
            return 0
        old = self.originals.get(hwnd)
        if old:
            return self.user32.CallWindowProcW(old, hwnd, message, wparam, lparam)
        return 0

    def _drain(self):
        if self.closed:
            return
        try:
            while True:
                self.callback(self.pending.get_nowait())
        except queue.Empty:
            pass
        self.timer = self.root.after(60, self._drain)

    def close(self):
        if self.closed:
            return
        self.closed, self.enabled = True, False
        if self.timer:
            try:
                self.root.after_cancel(self.timer)
            except Exception:
                pass
        for hwnd, old in list(self.originals.items()):
            if self.user32.IsWindow(hwnd):
                self.shell32.DragAcceptFiles(hwnd, False)
                if self.user32.GetWindowLongPtrW(hwnd, self.GWLP_WNDPROC) == self.native_address:
                    self.user32.SetWindowLongPtrW(hwnd, self.GWLP_WNDPROC, old)
        self.originals.clear()
