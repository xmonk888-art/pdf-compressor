"""Physical-pixel placement for the preview's related windows."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import sys


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self):
        return self.x + self.w

    @property
    def bottom(self):
        return self.y + self.h

    def overlaps(self, other):
        return self.x < other.right and self.right > other.x and self.y < other.bottom and self.bottom > other.y


def dock_box(parent, size, work, occupied, gap, near_toolbar=False):
    """Try the right, left, lower and upper sides in that order."""
    w, h = size
    if w > work.w or h > work.h:
        return None
    y = max(work.y, min(parent.y, work.bottom - h))
    x = max(work.x, min(parent.x, work.right - w))
    # New rows/columns use the visible edges of already-placed panels.
    right = [parent.right + gap] + sorted({b.right + gap for b in occupied if b.x >= parent.right})
    left = [parent.x - gap - w] + sorted({b.x - gap - w for b in occupied if b.right <= parent.x}, reverse=True)
    below = [parent.bottom + gap] + sorted({b.bottom + gap for b in occupied if b.y >= parent.bottom})
    above = [parent.y - gap - h] + sorted({b.y - gap - h for b in occupied if b.bottom <= parent.y}, reverse=True)
    side_y = [y] + sorted({b.bottom + gap for b in occupied if b.y >= y})
    bottom_x = [x] + sorted({b.right + gap for b in occupied if b.x >= x})
    candidates = ([(cx, cy) for side in (right, left) for cy in side_y for cx in side]
                  + [(cx, cy) for side in (below, above) for cx in bottom_x for cy in side])
    if near_toolbar:
        candidates = [(x, below[0]), (x, above[0])] + candidates
    for cx, cy in candidates:
        trial = Box(cx, cy, w, h)
        if (work.x <= cx and trial.right <= work.right and work.y <= cy
                and trial.bottom <= work.bottom and not any(trial.overlaps(b) for b in occupied)):
            return trial
    return None


if sys.platform == 'win32':
    _user = ctypes.WinDLL('user32', use_last_error=True)
    _user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user.GetAncestor.restype = wintypes.HWND
    _user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user.MonitorFromWindow.restype = wintypes.HANDLE
    _user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]

    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD)]

    _user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]


def native_handle(window):
    return _user.GetAncestor(window.winfo_id(), 2)


def window_box(window):
    if sys.platform == 'win32':
        rect = wintypes.RECT()
        if _user.GetWindowRect(native_handle(window), ctypes.byref(rect)):
            return Box(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    return Box(window.winfo_x(), window.winfo_y(), window.winfo_width(), window.winfo_height())


def monitor_work(window):
    if sys.platform == 'win32':
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if _user.GetMonitorInfoW(_user.MonitorFromWindow(native_handle(window), 2), ctypes.byref(info)):
            r = info.work
            return Box(r.left, r.top, r.right - r.left, r.bottom - r.top)
    return Box(0, 0, window.winfo_screenwidth(), window.winfo_screenheight())


def move_window(window, x, y, size=None):
    if sys.platform == 'win32':
        flags = 0x4 | 0x10  # Keep stacking and focus.
        if size is None:
            flags |= 0x1
        _user.SetWindowPos(native_handle(window), None, x, y, *(size or (0, 0)), flags)
    elif size is None:
        window.geometry(f'{x:+d}{y:+d}')


class DockLayout:
    def __init__(self, root):
        self.root = root
        self.panels = []
        self.pending = None
        self.root.bind('<Configure>', self.request, add='+')

    def request(self, event=None):
        if event is not None and event.widget is not self.root:
            return
        if self.pending is None:
            self.pending = self.root.after_idle(self.reflow)

    def add(self, panel):
        if panel not in self.panels:
            self.panels.append(panel)

    def remove(self, panel):
        if panel in self.panels:
            self.panels.remove(panel)
            self.request()

    def reflow(self, opening=False):
        if self.pending is not None:
            self.root.after_cancel(self.pending)
            self.pending = None
        if self.root.state() != 'normal':
            return
        main = window_box(self.root)
        work = monitor_work(self.root)
        gap = max(6, round(8 * self.root._get_window_scaling()))
        sizes = []
        for panel in self.panels:
            scale = panel.window._get_window_scaling()
            w, h = panel.dock_size
            sizes.append((panel, (min(round(w * scale), work.w), min(round(h * scale), work.h))))

        def plan(anchor):
            placed = {self.root: anchor}
            for panel, size in sizes:
                parent = placed.get(panel.return_to, anchor)
                target = dock_box(parent, size, work, tuple(placed.values()), gap, near_toolbar=panel.popover)
                if target is None:
                    return None
                placed[panel.window] = target
            return placed

        placed = plan(main)
        if placed is None and opening:
            # Keep a large newly opened panel visible on a smaller monitor.
            xs = (main.x, work.x + gap, work.right - gap - main.w)
            ys = (main.y, work.y + gap, work.bottom - gap - main.h)
            candidates = sorted((Box(x, y, main.w, main.h) for x in xs for y in ys),
                                key=lambda b: abs(b.x - main.x) + abs(b.y - main.y))
            for anchor in candidates:
                if work.x <= anchor.x and work.y <= anchor.y and anchor.right <= work.right and anchor.bottom <= work.bottom:
                    placed = plan(anchor)
                    if placed is not None:
                        move_window(self.root, anchor.x, anchor.y)
                        break
        if placed is None:
            # A screen can be smaller than the combined windows. Favor
            # keeping the whole panel on screen in that case.
            placed = {self.root: main}
            for panel, size in sizes:
                parent = placed.get(panel.return_to, main)
                w, h = size
                placed[panel.window] = dock_box(
                    parent, size, work, tuple(placed.values()), gap, near_toolbar=panel.popover) or Box(
                    max(work.x, min(parent.right + gap, work.right - w)),
                    max(work.y, min(parent.y, work.bottom - h)), w, h)
        for panel, _ in sizes:
            target = placed[panel.window]
            current = window_box(panel.window)
            if current != target:
                size = target.w, target.h
                resize = size if (current.w, current.h) != size else None
                move_window(panel.window, target.x, target.y, resize)
