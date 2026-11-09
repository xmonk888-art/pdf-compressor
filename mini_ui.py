"""Compact presentation layer. Compression stays in app.worker_batch and engine.py."""
from pathlib import Path
import ctypes
import sys

import customtkinter as ctk
from PIL import Image, ImageDraw

from engine import PRESETS, format_size
from drop_support import WindowsFileDrop
from ui_shell import RoundedHost, main_backdrop, apply_application_icon
from dock_layout import DockLayout, monitor_work, move_window, window_box
from unified_panels import install_panels


def install_mini_ui(Window, tk, ttk, filedialog, messagebox):
    def icon(kind, color='#545454'):
        im = Image.new('RGBA', (64, 64))
        d = ImageDraw.Draw(im)
        def line(points):
            d.line([(x * 3, y * 3) for x, y in points], fill=color, width=5)
        if kind == 'add':
            line([(10, 3), (10, 17)]); line([(3, 10), (17, 10)])
        elif kind == 'queue':
            for y in (5, 10, 15):
                line([(7, y), (18, y)])
                d.ellipse((6, y*3-2, 10, y*3+2), fill=color)
        elif kind == 'folder':
            line([(2, 6), (2, 17), (18, 17), (18, 6), (10, 6), (8, 3), (2, 3), (2, 6)])
        return ctk.CTkImage(im, size=(17, 17))

    def init(self):
        if sys.platform == 'win32':
            shell = ctypes.WinDLL('shell32')
            shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
            shell.SetCurrentProcessExplicitAppUserModelID('LocalTools.PDFCompressor.UnifiedUI.2.1')
        ctk.set_default_color_theme(str(Path(getattr(sys, '_MEIPASS', Path(__file__).parent / 'assets')) / 'monochrome.json'))
        ctk.set_appearance_mode('light')
        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.title('PDF 高清压缩 2.4.1')
        self.main_height = 150
        self.root.geometry(f'320x{self.main_height}')
        self.root.resizable(False, False)
        self.root.overrideredirect(True)
        self.root.configure(fg_color='#fafafa')
        self.rounded = RoundedHost(self.root)
        self.dock = DockLayout(self.root)
        apply_application_icon(self.root, default=True)
        self.files, self.results = {}, {}
        self.process = self.stop = self.events = None
        self.busy, self.completed, self.total = False, 0, 0
        self.output_folder = tk.StringVar()
        self.preset = tk.StringVar(value='hd')
        self.mode_name = tk.StringVar(value=PRESETS['hd'].name)
        self.status = tk.StringVar()
        self.folder_label = tk.StringVar(value='原文件旁的「压缩输出」文件夹')
        self.progress = tk.DoubleVar()
        self.drop_handler = self.queue_drop = None
        self.profile_buttons = []
        self._drag_origin = None
        self._tooltip = self._tooltip_timer = None
        self._minimized = False

        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('Treeview', rowheight=32, background='white', fieldbackground='white', borderwidth=0)
        style.configure('Treeview.Heading', background='#f0f0f0', padding=(7, 8))
        style.configure('TButton', padding=(10, 6))

        self.surface = ctk.CTkFrame(self.root, corner_radius=0, fg_color='#fafafa')
        self.surface.pack(fill='both', expand=True)
        self.backdrop_images = {height: main_backdrop(height) for height in (150, 176)}
        self.backdrop = ctk.CTkLabel(self.surface, text='', image=self.backdrop_images[self.main_height])
        self.backdrop.place(x=0, y=0)
        self.toolbar = ctk.CTkFrame(self.surface, corner_radius=0, fg_color='#f0f0f0', width=300, height=28)
        self.toolbar.place(x=10, y=111)
        self.title_label = ctk.CTkLabel(self.surface, text='拖入 PDF 或文件夹', font=('Microsoft YaHei UI', 14, 'bold'), text_color='#242424', height=26)
        self.title_label.place(relx=.5, y=30, anchor='n')
        self.sub_label = ctk.CTkLabel(self.surface, text='点击 ＋ 添加', font=('Microsoft YaHei UI', 10), text_color='#787878', height=19)
        self.sub_label.place(relx=.5, y=58, anchor='n')
        self.close_btn = ctk.CTkButton(self.surface, text='×', width=20, height=20, font=('Segoe UI', 14), fg_color='transparent', hover_color='#e8e8e8', text_color='#8a8a8a', command=self.close)
        self.close_btn.place(relx=1, x=-7, y=5, anchor='ne')
        self.minimize_btn = ctk.CTkButton(self.surface, text='−', width=20, height=20,
            font=('Segoe UI', 14), fg_color='transparent', hover_color='#e8e8e8',
            text_color='#787878', command=self.minimize)
        self.minimize_btn.place(relx=1, x=-31, y=5, anchor='ne')
        self.bind_tip(self.minimize_btn, '最小化')
        arrow = Image.new('RGBA', (32, 24))
        ImageDraw.Draw(arrow).line([(4, 6), (16, 18), (28, 6)], fill='#545454', width=5)
        self.mode_control = ctk.CTkButton(self.toolbar, textvariable=self.mode_name, command=self.show_mode_menu,
            image=ctk.CTkImage(arrow, size=(8, 6)), compound='right',
            width=82, height=28, corner_radius=7, font=('Microsoft YaHei UI', 11), fg_color='#ffffff',
            hover_color='#e8e8e8', text_color='#242424', border_width=1, border_color='#dedede')
        self.mode_control.place(x=0, y=0)
        self.icons = {k: icon(k, '#202020' if k == 'add' else '#545454') for k in ('add', 'queue', 'folder')}
        def tool(x, kind, command):
            b = ctk.CTkButton(self.toolbar, text='', image=self.icons[kind], width=27, height=28, corner_radius=6, fg_color='transparent', hover_color='#e4e4e4', command=command)
            b.place(x=x-10, y=0)
            return b
        self.add_btn = tool(107, 'add', self.show_add)
        self.queue_btn = tool(148, 'queue', self.toggle_queue)
        self.folder_btn = tool(189, 'folder', self.show_folder_menu)
        self.start_btn = ctk.CTkButton(self.toolbar, text='▶ 开始', width=79, height=28, corner_radius=7, font=('Microsoft YaHei UI', 11, 'bold'), fg_color='#202020', hover_color='#383838', command=self.start_or_stop)
        self.start_btn.place(x=220, y=0)
        self.mini_progress = ctk.CTkProgressBar(self.surface, height=3, corner_radius=0, fg_color='#e4e4e4', progress_color='#202020')
        self.mini_progress.set(0)
        self.mini_progress.place(x=10, y=97, relwidth=.9375)
        self.mini_progress.place_forget()

        self.status_display = tk.StringVar()
        self.status_label = ctk.CTkLabel(self.surface, textvariable=self.status_display,
            font=('Microsoft YaHei UI', 10), text_color='#545454',
            anchor='w', justify='left', height=24, width=296)
        self.bind_tip(self.status_label, '双击查看完整状态')
        self.build_queue()

        for widget in (self.surface, self.backdrop, self.title_label, self.sub_label):
            widget.bind('<ButtonPress-1>', self.drag_start)
            widget.bind('<B1-Motion>', self.drag_move)
        self.title_label.bind('<Double-Button-1>', lambda e: self.show_queue())
        self.sub_label.bind('<Double-Button-1>', lambda e: self.show_queue())
        for widget, text in [(self.add_btn, '添加 PDF（Ctrl+O）'), (self.queue_btn, '文件队列（Ctrl+L）'),
                             (self.folder_btn, '保存位置 / 打开输出文件夹'), (self.close_btn, '关闭'),
                             (self.mode_control, '选择压缩模式；沿用原压缩规则')]:
            self.bind_tip(widget, text)
        self.root.bind('<Control-o>', lambda e: self.show_add())
        self.root.bind('<Control-l>', lambda e: self.show_queue())
        self.root.bind('<Alt-F4>', lambda e: self.close())
        self.root.bind('<Map>', self.on_map)
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.status.trace_add('write', lambda *args: self.refresh_summary())
        self.progress.trace_add('write', lambda *args: self.refresh_summary())
        self.add_files(())
        self.root.after(150, self.poll)
        # Initialise CTk's first-show bookkeeping while intentionally hidden.
        # Otherwise CTk.mainloop() withdraws the window again on its first call.
        self.root.update()
        self.setup_native_window()
        self.root.deiconify()
        self.restore_frame()
        self.root.after(180, self.enable_drop)

    def setup_native_window(self):
        # Set taskbar eligibility before showing the custom frame.
        if sys.platform != 'win32': return
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        from ctypes import wintypes
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]; user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]; user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, (style | 0x40000) & ~0x80)

    def enable_drop(self):
        for name, window in [('drop_handler', self.root), ('queue_drop', self.queue_window)]:
            old = getattr(self, name, None)
            if old: old.close()
            try: setattr(self, name, WindowsFileDrop(window, self.accept_drop))
            except Exception as exc:
                setattr(self, name, None)
                self.status.set(f'拖入暂不可用，可点击 ＋ 添加文件：{exc}')

    def refresh_summary(self):
        if not hasattr(self, 'title_label'): return
        message = self.status.get()
        self.status_display.set(message if len(message) <= 25 else message[:24] + '…')
        height = 176 if message else 150
        if height != self.main_height:
            self.main_height = height
            self.backdrop.configure(image=self.backdrop_images[height])
            if message:
                self.status_label.place(x=12, y=151)
                self.queue_status_label.pack(fill='x', pady=(7, 0))
            else:
                self.status_label.place_forget()
                self.queue_status_label.pack_forget()
            if not self._minimized:
                self.root.geometry(f'320x{height}')
        n = len(self.files)
        if self.busy:
            self.title_label.configure(text=f'正在压缩  {self.progress.get():.0f}%')
            self.sub_label.configure(text=message[:28] + ('…' if len(message) > 28 else ''))
            self.mini_progress.place(x=10, y=97, relwidth=.9375)
            self.mini_progress.set(max(0, min(1, self.progress.get()/100)))
        elif self.results:
            saved = sum(r['before_bytes']-r['after_bytes'] for r in self.results.values())
            self.title_label.configure(text=f'完成 {len(self.results)}/{n} · 节省 {format_size(saved)}')
            self.sub_label.configure(text='点击列表查看结果 / 双击完成项打开 PDF')
            self.mini_progress.place_forget()
        elif n:
            self.title_label.configure(text=f'{n} 个 PDF · 等待压缩')
            if message.startswith(('处理结束', '已停止', '拖入暂不可用')):
                self.sub_label.configure(text=message[:28])
            else: self.sub_label.configure(text='点击列表查看文件')
            self.mini_progress.place_forget()
        else:
            self.title_label.configure(text='拖入 PDF 或文件夹')
            self.sub_label.configure(text='点击 ＋ 添加')
            self.mini_progress.place_forget()

    def select_mode(self, value):
        if not self.busy:
            self.preset.set(next(k for k, p in PRESETS.items() if p.name == value))

    def show_queue(self):
        self.hide_tip()
        self.queue_window.deiconify(); self.queue_window.lift(); self.tree.focus_set()
        if not self.queue_drop:
            try: self.queue_drop = WindowsFileDrop(self.queue_window, self.accept_drop)
            except Exception: pass

    def popup(self, menu, widget):
        self.hide_tip()
        try: menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty()+widget.winfo_height()+3)
        finally: menu.grab_release()

    def show_folder_menu(self):
        menu = tk.Menu(self.root, tearoff=0, font=('Microsoft YaHei UI', 10))
        menu.add_command(label=self.folder_label.get(), state='disabled')
        menu.add_separator()
        menu.add_command(label='更改保存位置…', command=self.pick_folder, state='disabled' if self.busy else 'normal')
        menu.add_command(label='恢复默认位置', command=self.default_folder, state='disabled' if self.busy else 'normal')
        menu.add_command(label='打开输出文件夹', command=self.open_folder)
        self.popup(menu, self.folder_btn)

    def set_busy(self, busy):
        self.busy = busy
        for control in (self.add_btn, self.queue_add_btn, self.remove_btn, self.clear_btn, self.default_btn, self.mode_control):
            control.configure(state='disabled' if busy else 'normal')
        self.start_btn.configure(text='■ 停止' if busy else '▶ 开始', state='normal')
        self.cancel_btn.configure(state='normal' if busy else 'disabled')
        self.refresh_summary()

    original_cancel = Window.cancel
    def cancel(self):
        original_cancel(self)
        if self.busy: self.start_btn.configure(text='停止中', state='disabled')

    def start_or_stop(self):
        if self.busy: self.cancel()
        else: self.start()

    def drag_start(self, event):
        box = window_box(self.root)
        self._drag_origin = event.x_root - box.x, event.y_root - box.y

    def drag_move(self, event):
        if self._drag_origin:
            dx, dy = self._drag_origin
            move_window(self.root, event.x_root - dx, event.y_root - dy)
            self.dock.request()

    def minimize(self):
        self.hide_tip()
        self._minimized = True
        for panel in self.dock.panels:
            panel.window.withdraw()
        self.root.overrideredirect(False)
        self.root.iconify()

    def on_map(self, event):
        if event.widget is self.root:
            self.root.after(40, self.restore_frame)

    def restore_frame(self):
        if getattr(self, 'windows_destroyed', False) or self.root.state() != 'normal':
            return
        if self._minimized:
            self._minimized = False
            self.root.withdraw()
            self.root.overrideredirect(True)
            self.root.geometry(f'320x{self.main_height}')
            self.root.update_idletasks()
            self.setup_native_window()
            self.root.deiconify()
            for panel in self.dock.panels:
                panel.window.deiconify()
        self.rounded.apply()
        self.dock.request()

    def hide_tip(self):
        if self._tooltip_timer:
            self.root.after_cancel(self._tooltip_timer); self._tooltip_timer = None
        if self._tooltip:
            self._tooltip.destroy(); self._tooltip = None

    def bind_tip(self, widget, text):
        def show():
            self._tooltip_timer = None
            tip = self._tooltip = tk.Toplevel(self.root)
            tip.overrideredirect(True)
            tip.attributes('-topmost', True)
            tip.geometry(f'+{widget.winfo_rootx()}+{widget.winfo_rooty()+widget.winfo_height()+4}')
            tk.Label(tip, text=text, bg='#242424', fg='white', padx=8, pady=5, font=('Microsoft YaHei UI', 9)).pack()
        def enter(event):
            self.hide_tip(); self._tooltip_timer = self.root.after(550, show)
        widget.bind('<Enter>', enter, add='+')
        widget.bind('<Leave>', lambda e: self.hide_tip(), add='+')
        widget.bind('<ButtonPress-1>', lambda e: self.hide_tip(), add='+')

    def close(self):
        self.hide_tip()
        if self.busy:
            self.cancel(); self.root.after(200, self.close_when_stopped)
        else: self.destroy_windows()

    def close_when_stopped(self):
        if self.process and self.process.is_alive(): self.root.after(200, self.close_when_stopped)
        else: self.destroy_windows()

    def destroy_windows(self):
        for handler in (self.drop_handler, self.queue_drop):
            if handler: handler.close()
        self.root.destroy()

    for name, method in dict(__init__=init, setup_native_window=setup_native_window, enable_drop=enable_drop,
        refresh_summary=refresh_summary, update_empty_hint=refresh_summary, select_mode=select_mode,
        show_queue=show_queue, popup=popup, show_folder_menu=show_folder_menu,
        set_busy=set_busy, cancel=cancel, start_or_stop=start_or_stop, drag_start=drag_start, drag_move=drag_move,
        minimize=minimize, on_map=on_map, restore_frame=restore_frame,
        hide_tip=hide_tip, bind_tip=bind_tip,
        close=close, close_when_stopped=close_when_stopped, destroy_windows=destroy_windows).items():
        setattr(Window, name, method)

    install_panels(Window, tk, ttk, filedialog)
