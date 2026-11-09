"""Opaque, natively clipped windows: no colour-key transparency or stacked corners."""
import ctypes
from ctypes import wintypes
import sys
from pathlib import Path
import customtkinter as ctk
from PIL import Image, ImageDraw

BG = '#fafafa'
BLUE = '#202020'
INK = '#242424'
MUTED = '#787878'


def place_in_work_area(window, x, y):
    """Position in the nearest monitor's usable rectangle, including negative coordinates."""
    window.update_idletasks()
    if sys.platform != 'win32':
        window.geometry(f'+{max(0, x)}+{max(0, y)}')
        return
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user.MonitorFromPoint.restype = wintypes.HANDLE
    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    info = MonitorInfo()
    info.size = ctypes.sizeof(info)
    handle = user.MonitorFromPoint(wintypes.POINT(x, y), 2)
    if not user.GetMonitorInfoW(handle, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    scale = window._get_window_scaling() if hasattr(window, '_get_window_scaling') else 1
    width = max(window.winfo_width(), round(getattr(window, '_current_width', 1) * scale))
    height = max(window.winfo_height(), round(getattr(window, '_current_height', 1) * scale))
    x = max(info.work.left, min(x, info.work.right - width))
    y = max(info.work.top, min(y, info.work.bottom - height - 32))
    hwnd = user.GetAncestor(window.winfo_id(), 2)
    user.SetWindowPos(hwnd, None, x, y, 0, 0, 0x1 | 0x4 | 0x10)


def apply_application_icon(window, default=False):
    """Keep the approved icon after CTk's delayed Windows icon initialization."""
    path = Path(getattr(sys, '_MEIPASS', Path(__file__).parent / 'assets')) / 'app.ico'
    if sys.platform != 'win32' or not path.is_file():
        return
    def apply():
        if window.winfo_exists():
            if default:
                window.iconbitmap(default=str(path))
            window.iconbitmap(str(path))
            user = ctypes.WinDLL('user32', use_last_error=True)
            user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user.GetAncestor.restype = wintypes.HWND
            user.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user.LoadImageW.restype = wintypes.HANDLE
            user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user.SendMessageW.restype = ctypes.c_ssize_t
            user.DestroyIcon.argtypes = [wintypes.HANDLE]
            if not hasattr(window, '_application_icon_handles'):
                window._application_icon_handles = [
                    user.LoadImageW(None, str(path), 1, user.GetSystemMetrics(x), user.GetSystemMetrics(y), 0x10)
                    for x, y in ((49, 50), (11, 12))
                ]
                if not all(window._application_icon_handles):
                    raise ctypes.WinError(ctypes.get_last_error())
                def release(event):
                    if event.widget == window:
                        for handle in window._application_icon_handles:
                            user.DestroyIcon(handle)
                window.bind('<Destroy>', release, add='+')
            hwnd = user.GetAncestor(window.winfo_id(), 2)
            for kind, handle in enumerate(window._application_icon_handles):
                user.SendMessageW(hwnd, 0x80, kind, handle)
    apply()
    window.after(300, apply)


class RoundedHost:
    def __init__(self, window, radius=14, taskbar=False):
        self.window, self.radius, self.taskbar = window, radius, taskbar
        self.last = None
        self.window.bind('<Configure>', self.configured, add='+')
        self.window.after_idle(self.apply)

    def configured(self, event):
        if event.widget == self.window:
            self.apply()

    def apply(self):
        if sys.platform != 'win32' or not self.window.winfo_exists(): return
        user = ctypes.WinDLL('user32', use_last_error=True)
        gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user.GetAncestor.restype = wintypes.HWND
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        user.SetWindowRgn.restype = ctypes.c_int
        gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int]*6
        gdi.CreateRoundRectRgn.restype = wintypes.HRGN
        gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        hwnd = user.GetAncestor(self.window.winfo_id(), 2)
        rect = wintypes.RECT()
        if not user.GetWindowRect(hwnd, ctypes.byref(rect)): return
        width, height = rect.right-rect.left, rect.bottom-rect.top
        if width < 2 or height < 2: return
        scale = self.window._get_window_scaling() if hasattr(self.window, '_get_window_scaling') else 1
        radius = round(self.radius*scale)
        current = (hwnd, width, height, radius)
        if current == self.last: return
        region = gdi.CreateRoundRectRgn(0, 0, width+1, height+1, radius*2, radius*2)
        if not user.SetWindowRgn(hwnd, region, True):
            gdi.DeleteObject(region)
            raise ctypes.WinError(ctypes.get_last_error())
        self.last = current  # Windows owns the region after success.


def main_backdrop(height=176):
    scale = 4
    im = Image.new('RGB', (320*scale, height*scale), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 100*scale, 320*scale, 150*scale), fill='#f0f0f0')
    d.line((0, 100*scale, 320*scale, 100*scale), fill='#dedede', width=scale)
    d.line((0, 150*scale, 320*scale, 150*scale), fill='#e6e6e6', width=scale)
    d.rounded_rectangle((0, 0, 320*scale-1, height*scale-1), radius=14*scale, outline='#dedede', width=scale)
    return ctk.CTkImage(im, size=(320, height))


def label(parent, text='', size=12, bold=False, color=INK, **kwargs):
    return ctk.CTkLabel(parent, text=text, font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'), text_color=color, **kwargs)


def button(parent, text, command, primary=False, danger=False, width=90, **kwargs):
    return ctk.CTkButton(parent, text=text, command=command, width=width, height=30,
        corner_radius=7, font=('Microsoft YaHei UI', 11),
        fg_color=BLUE if primary else '#faeeee' if danger else '#ffffff',
        text_color='white' if primary else '#a94e55' if danger else '#545454',
        hover_color='#383838' if primary else '#f3dddd' if danger else '#ededed',
        border_width=0 if primary else 1, border_color='#e9cdcf' if danger else '#dedede', **kwargs)


class Panel:
    def __init__(self, owner, title, width, height, key, on_close=None, popover=False):
        self.owner, self.key = owner, key
        self.dock_size = (width, height)
        self.window = ctk.CTkToplevel(owner.root)
        self.window.withdraw()
        apply_application_icon(self.window)
        self.window.title('PDF 压缩 · '+title)
        self.window.geometry(f'{width}x{height}')
        self.window.resizable(False, False)
        self.window.overrideredirect(True)
        self.window.configure(fg_color=BG)
        self.window.transient(owner.root)
        self.rounded = RoundedHost(self.window)
        self.frame = ctk.CTkFrame(self.window, fg_color=BG, corner_radius=14, border_width=1, border_color='#dedede')
        self.frame.pack(fill='both', expand=True)
        self.on_close = on_close or self.hide
        self.header = ctk.CTkFrame(self.frame, height=43, fg_color='transparent')
        self.header.pack(fill='x', padx=14, pady=(4, 0)); self.header.pack_propagate(False)
        self.title = label(self.header, title, 13, True)
        self.title.pack(side='left')
        button(self.header, '×', self.on_close, width=26).pack(side='right')
        ctk.CTkFrame(self.frame, height=1, fg_color='#e4e4e4').pack(fill='x', padx=1)
        self.footer = ctk.CTkFrame(self.frame, fg_color='transparent', height=38)
        self.footer.pack(side='bottom', fill='x', padx=15, pady=(6, 12))
        self.body = ctk.CTkFrame(self.frame, fg_color='transparent')
        self.body.pack(fill='both', expand=True, padx=16, pady=(12, 0))
        if key == 'queue':
            grip = label(self.frame, '◢', size=11, color=MUTED, width=18, height=18, cursor='size_nw_se')
            grip.place(relx=1, rely=1, x=-3, y=-3, anchor='se')
            grip.bind('<ButtonPress-1>', self.begin_resize)
            grip.bind('<B1-Motion>', self.resize_queue)
        self.window.protocol('WM_DELETE_WINDOW', self.on_close)
        self.window.bind('<Escape>', self.on_escape)
        self.popover = popover
        self.anchor = None
        self.return_to = None
        self.drop = None

    def on_escape(self, event):
        if not self.owner.dismiss_popovers():
            self.on_close()
        return 'break'

    def begin_resize(self, event):
        self.resize_start = (event.x_root, event.y_root, *self.dock_size)

    def resize_queue(self, event):
        if hasattr(self, 'resize_start'):
            x, y, w, h = self.resize_start
            scale = self.window._get_window_scaling()
            self.dock_size = (max(700, min(1600, round(w + (event.x_root-x)/scale))),
                              max(330, min(950, round(h + (event.y_root-y)/scale))))
            self.owner.dock.request()

    def show(self, anchor=None):
        self.anchor = anchor
        if self not in self.owner.dock.panels:
            source = anchor or self.owner.root.focus_get()
            parent = source.winfo_toplevel() if source is not None else self.owner.root
            self.return_to = parent if parent in [p.window for p in self.owner.dock.panels] else self.owner.root
            if self.key == 'queue':
                self.return_to = self.owner.root
        self.owner.hide_tip()
        for other in self.owner.panels.values():
            if other is not self and other.popover: other.hide()
        self.window.update_idletasks()
        self.owner.dock.add(self)
        self.owner.dock.reflow(opening=True)
        self.window.deiconify(); self.window.lift(); self.window.focus_force()
        self.owner.dock.request()
        self.rounded.apply()

    def hide(self):
        visible = self.window.state() != 'withdrawn'
        try: self.window.grab_release()
        except Exception: pass
        self.window.withdraw()
        self.owner.dock.remove(self)
        if visible and not self.popover and self.return_to is not None:
            if self.return_to.winfo_exists() and self.return_to.state() == 'normal':
                self.return_to.lift(); self.return_to.focus_force()

    def destroy(self):
        self.owner.dock.remove(self)
        if self.drop: self.drop.close(); self.drop = None
        self.window.destroy()
