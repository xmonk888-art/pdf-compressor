"""Consistent panels and dialogs for the compact PDF compressor."""
import csv
import os
from pathlib import Path
import customtkinter as ctk
from ui_shell import Panel, label, button, BG, BLUE, INK, MUTED
from engine import PRESETS, format_size
from drop_support import WindowsFileDrop, expand_dropped_paths


def install_panels(Window, tk, ttk, filedialog):
    original = {name: getattr(Window, name) for name in (
        'start', 'remove_files', 'clear_files', 'destroy_windows', 'refresh_summary', 'set_busy')}

    def new_panel(self, key, title, width, height, popover=False, toggle=False):
        old = self.panels.get(key)
        if old and old in self.dock.panels:
            if toggle:
                old.hide()
            else:
                old.window.lift()
                old.window.focus_force()
            return None
        if old:
            old.destroy()
        panel = Panel(self, title, width, height, key, popover=popover)
        self.panels[key] = panel
        return panel

    def show_notice(self, title, text, action=None, action_text='确定'):
        notice = self.panels.get('notice')
        content = title, text
        if notice in self.dock.panels and notice.content != content:
            notice.hide()
        p = self.new_panel('notice', title, 400, 210, toggle=True)
        if p is None: return
        p.content = content
        label(p.body, text, 12, color=MUTED, wraplength=360, justify='left').pack(anchor='w', fill='x', pady=8)
        def done():
            p.hide()
            if action: action()
        button(p.footer, action_text, done, primary=True).pack(side='right')
        p.show()

    def confirm(self, title, text, action, positive, danger=True):
        p = self.new_panel('confirm', title, 400, 205)
        if p is None: return
        label(p.body, text, 12, color=MUTED, wraplength=365, justify='left').pack(anchor='w', fill='x', pady=7)
        def accept():
            p.hide()
            action()
        self.confirm_accept = button(p.footer, positive, accept, danger=danger)
        self.confirm_accept.pack(side='left')
        self.confirm_cancel = button(p.footer, '取消' if positive != '停止并退出' else '继续压缩', p.hide, primary=True)
        self.confirm_cancel.pack(side='right')
        p.show(); p.window.grab_set()

    def build_queue(self):
        self.panels = {}
        self.root.bind_all('<ButtonPress-1>', self.dismiss_popovers, add='+')
        self.root.bind('<Escape>', lambda e: self.dismiss_popovers())
        p = self.new_panel('queue', '文件队列', 820, 460)
        self.queue_window = p.window
        self.queue_window.title('PDF 高清压缩 · 文件队列')
        self.queue_count = tk.StringVar(value='0 个文件')
        label(p.header, size=10, color=MUTED, textvariable=self.queue_count).pack(side='left', padx=12)
        bar = ctk.CTkFrame(p.body, fg_color='transparent')
        bar.pack(fill='x', pady=(0, 8))
        self.queue_add_btn = button(bar, '＋ 添加', lambda: self.show_add(self.queue_add_btn), width=70)
        self.queue_add_btn.pack(side='left')
        self.remove_btn = button(bar, '移除所选', self.remove_files, width=80)
        self.remove_btn.pack(side='left', padx=6)
        self.clear_btn = button(bar, '清空', self.clear_files, width=55)
        self.clear_btn.pack(side='left')
        self.retry_btn = button(bar, '重试失败项', self.retry_failed, width=92)
        self.retry_btn.pack(side='left', padx=(10, 6))
        self.resume_btn = button(bar, '继续未完成', self.resume_incomplete, width=92)
        self.resume_btn.pack(side='left')
        self.history_btn = button(bar, '历史记录', self.open_history, width=80)
        self.history_btn.pack(side='right', padx=(6, 0))
        self.report_btn = button(bar, '导出记录', self.save_record, width=80)
        self.report_btn.pack(side='right')
        style = ttk.Style(self.root)
        style.configure('Unified.Treeview', font=('Microsoft YaHei UI', 10), rowheight=35,
            background=BG, fieldbackground=BG, foreground=INK, borderwidth=0, relief='flat')
        style.layout('Unified.Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        style.configure('Unified.Treeview.Heading', background='#f0f0f0', foreground='#787878',
            font=('Microsoft YaHei UI', 9), padding=(7, 8), relief='flat', borderwidth=0)
        style.map('Unified.Treeview.Heading', background=[('active', '#e8e8e8')])
        style.map('Unified.Treeview', background=[('selected', '#eaeaea')], foreground=[('selected', '#242424')])
        table = ctk.CTkFrame(p.body, fg_color=BG, corner_radius=0)
        table.pack(fill='both', expand=True)
        table.rowconfigure(0, weight=1); table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, style='Unified.Treeview', columns=('file','before','after','saved','state','source'), show='headings', selectmode='extended', height=5)
        for key, title, width in [('file','PDF 文件',210),('before','原大小',80),('after','压缩后',80),('saved','减少',60),('state','状态',220),('source','来源文件夹',270)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=50, anchor='w' if key in ('file','state','source') else 'center', stretch=key in ('file','state','source'))
        sy = ctk.CTkScrollbar(table, command=self.tree.yview, width=10, fg_color=BG, button_color='#c5c5c5')
        sx = ctk.CTkScrollbar(table, command=self.tree.xview, orientation='horizontal', height=10, fg_color=BG, button_color='#c5c5c5')
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0,column=0,sticky='nsew'); sy.grid(row=0,column=1,sticky='ns'); sx.grid(row=1,column=0,sticky='ew')
        self.tree.tag_configure('done', foreground='#387c63')
        self.tree.tag_configure('error', foreground='#a94e55')
        self.tree.bind('<Double-1>', self.open_selected)
        self.tree.bind('<Delete>', lambda e: self.remove_files())
        self.tree.bind('<Control-a>', lambda e: self.tree.selection_set(self.tree.get_children()))
        self.selected_path = tk.StringVar(value='选择文件可查看完整路径。')
        self.path_label = label(p.body, size=10, color=MUTED, textvariable=self.selected_path,
                               wraplength=950, justify='left', anchor='w')
        self.path_label.pack(fill='x', pady=(5, 0))
        self.queue_window.bind('<Configure>', lambda e: self.path_label.configure(
            wraplength=max(300, self.queue_window.winfo_width()-50))
            if e.widget == self.queue_window and not getattr(self, 'windows_destroyed', False)
            and self.path_label.winfo_exists() else None, add='+')
        self.queue_status_label = label(p.body, size=10, color=MUTED, textvariable=self.status,
                                        wraplength=690, justify='left', anchor='w')
        self.open_btn = button(p.footer, '打开输出文件夹', self.open_folder, width=128)
        self.open_btn.pack(side='left')
        self.selected_folder_btn = button(p.footer, '打开所选位置', self.open_selected_folder, width=112)
        self.selected_folder_btn.pack(side='left', padx=6)
        self.default_btn = button(p.footer, '保存设置', lambda: self.show_folder_menu(self.default_btn), width=82)
        self.default_btn.pack(side='left', padx=6)
        self.cancel_btn = button(p.footer, '停止', self.cancel, width=62)
        self.cancel_btn.pack(side='right'); self.cancel_btn.configure(state='disabled')
        button(p.footer, '收起', p.hide, width=62).pack(side='right', padx=6)
        self.queue_window.withdraw()

    def show_queue(self):
        self.panels['queue'].show()
        self.tree.focus_set()
        self.refresh_summary()

    def toggle_queue(self):
        panel = self.panels['queue']
        if panel in self.dock.panels:
            panel.hide()
        else:
            self.show_queue()

    def dismiss_popovers(self, event=None):
        # CTk invokes a button on its canvas or label, before the global binding.
        ancestors = []
        widget = event.widget if event is not None else None
        while widget is not None:
            ancestors.append(widget)
            widget = getattr(widget, 'master', None)
        dismissed = False
        for panel in tuple(self.dock.panels):
            if panel.popover and panel.window not in ancestors and panel.anchor not in ancestors:
                panel.hide()
                dismissed = True
        return dismissed

    def show_mode_menu(self):
        if self.busy: return
        p = self.new_panel('mode', '压缩模式', 320, 252, popover=True, toggle=True)
        if p is None: return
        p.footer.pack_forget()
        for key, preset in PRESETS.items():
            selected = key == self.preset.get()
            row = ctk.CTkFrame(p.body, fg_color='#ededed' if selected else 'transparent', corner_radius=7)
            row.pack(fill='x', pady=2)
            def choose(k=key):
                if not self.busy:
                    self.select_mode(PRESETS[k].name)
                p.hide()
            b = ctk.CTkButton(row, text=preset.name+('   ✓' if selected else ''), anchor='w', fg_color='transparent',
                hover_color='#e8e8e8', text_color=BLUE if selected else INK, font=('Microsoft YaHei UI',12,'bold'), height=26, command=choose)
            b.pack(fill='x', padx=4, pady=(3,0))
            desc = label(row, preset.description, 10, color=MUTED)
            desc.pack(anchor='w', padx=10, pady=(0,5)); desc.bind('<Button-1>', lambda e, c=choose: c())
        p.show(self.mode_control)

    def select_mode(self, value):
        if not self.busy:
            self.preset.set(next(k for k,p in PRESETS.items() if p.name==value))
            self.mode_name.set(value)

    def show_add(self, anchor=None):
        if self.busy: return
        p = self.new_panel('add', '添加 PDF', 380, 255, toggle=True)
        if p is None: return
        drop = ctk.CTkFrame(p.body, fg_color='#f2f2f2', border_color='#d4d4d4', border_width=1, corner_radius=10)
        drop.pack(fill='both', expand=True)
        label(drop, '＋', 25, color=BLUE).pack(pady=(10,3))
        label(drop, '拖入 PDF 或文件夹', 14, True, color='#242424').pack()
        label(drop, '支持多个文件，重复项自动跳过', 10, color=MUTED).pack(pady=5)
        button(p.footer, '＋ 选择 PDF', self.pick_files, primary=True, width=125).pack(side='left')
        button(p.footer, '选择文件夹', self.pick_input_folder, width=125).pack(side='left', padx=8)
        p.show(anchor or self.add_btn)
        p.drop = WindowsFileDrop(p.window, self.accept_drop)

    def pick_files(self):
        if self.busy: return
        names = filedialog.askopenfilenames(parent=self.root, title='选择一个或多个 PDF', filetypes=[('PDF 文件','*.pdf')])
        if names:
            self.add_files(names)
            if 'add' in self.panels: self.panels['add'].hide()

    def pick_input_folder(self):
        if self.busy: return
        path = filedialog.askdirectory(parent=self.root, title='选择包含 PDF 的文件夹')
        if path:
            names = expand_dropped_paths([path])
            if names:
                self.add_files(names); self.panels['add'].hide()
            else: self.show_notice('没有找到 PDF', '此文件夹中没有可添加的 PDF 文件。')

    def show_folder_menu(self, anchor=None):
        p = self.new_panel('folder', '保存位置', 440, 340, toggle=True)
        if p is None: return
        self.folder_choice = tk.StringVar(value='custom' if self.output_folder.get() else 'default')
        def use_default():
            if self.busy:
                self.folder_choice.set('custom' if self.output_folder.get() else 'default'); return
            self.default_folder()
        def use_custom():
            if self.busy:
                self.folder_choice.set('custom' if self.output_folder.get() else 'default'); return
            self.pick_folder()
            self.folder_choice.set('custom' if self.output_folder.get() else 'default')
        self.default_radio = ctk.CTkRadioButton(p.body, text='原文件旁的「压缩输出」文件夹', variable=self.folder_choice, value='default', command=use_default, font=('Microsoft YaHei UI',12), text_color=INK, radiobutton_width=15, radiobutton_height=15)
        self.default_radio.pack(anchor='w', pady=(4,6))
        label(p.body, '默认位置', 10, color=MUTED).pack(anchor='w', padx=25)
        self.custom_radio = ctk.CTkRadioButton(p.body, text='指定文件夹', variable=self.folder_choice, value='custom', command=use_custom, font=('Microsoft YaHei UI',12), text_color=INK, radiobutton_width=15, radiobutton_height=15)
        self.custom_radio.pack(anchor='w', pady=(20,8))
        self.folder_path_label = label(p.body, self.output_folder.get() or '尚未指定文件夹', 10, color=MUTED, wraplength=360, anchor='w', justify='left')
        self.folder_path_label.pack(fill='x', padx=25)
        self.change_folder_btn = button(p.body, '更改位置…', use_custom, width=120)
        self.change_folder_btn.pack(anchor='w', padx=25, pady=9)
        label(p.body, '保存位置会在下次启动时恢复；压缩模式每次默认高清。', 10,
              color=MUTED, wraplength=395).pack(anchor='w', pady=4)
        button(p.footer, '打开输出文件夹', self.open_folder, width=145).pack(side='left')
        button(p.footer, '完成', p.hide, primary=True, width=70).pack(side='right')
        for w in (self.default_radio,self.custom_radio,self.change_folder_btn): w.configure(state='disabled' if self.busy else 'normal')
        p.show(anchor or self.folder_btn)

    def pick_folder(self):
        if self.busy: return
        folder = filedialog.askdirectory(parent=self.root, title='选择压缩文件保存位置')
        if folder:
            self.output_folder.set(folder); self.folder_label.set(folder)
            if 'folder' in self.panels:
                self.folder_path_label.configure(text=folder); self.folder_choice.set('custom')

    def default_folder(self):
        if self.busy: return
        self.output_folder.set(''); self.folder_label.set('原文件旁的「压缩输出」文件夹')
        if 'folder' in self.panels:
            self.folder_path_label.configure(text='尚未指定文件夹'); self.folder_choice.set('default')

    def start(self):
        if not self.files: self.show_add(); return
        if self.busy: return
        for key,p in self.panels.items():
            if key != 'queue': p.hide()
        self._last_run_stopped = False
        original['start'](self)

    def set_busy(self, busy):
        original['set_busy'](self, busy)
        for control in (self.retry_btn, self.resume_btn):
            control.configure(state='disabled' if busy else 'normal')
        if 'folder' in self.panels:
            for name in ('default_radio','custom_radio','change_folder_btn'):
                getattr(self,name).configure(state='disabled' if busy else 'normal')

    def refresh_summary(self):
        original['refresh_summary'](self)
        if hasattr(self,'queue_count'): self.queue_count.set(f'{len(self.files)} 个文件')
        if not self.busy and self.files:
            if self.status.get().startswith('已停止'):
                self.title_label.configure(text=f'已停止 · 完成 {len(self.results)}/{len(self.files)}', text_color='#545454')
                self.sub_label.configure(text='已完成文件已保存')
            elif self.results:
                saved = sum(r['before_bytes']-r['after_bytes'] for r in self.results.values())
                n = len(self.results)
                self.title_label.configure(text=f'完成 {n}/{len(self.files)} · 节省 {format_size(saved)}', text_color='#387c63' if n==len(self.files) else '#545454')
            elif self.status.get().startswith('处理结束'):
                self.title_label.configure(text='未完成 · 请查看文件队列', text_color='#a94e55')
                self.sub_label.configure(text='双击失败项查看原因')
        else: self.title_label.configure(text_color='#242424')

    def remove_files(self):
        if self.busy: return
        selected = self.tree.selection()
        if not selected: self.show_queue(); return
        def remove():
            if not self.busy: original['remove_files'](self)
        self.confirm(f'移除这 {len(selected)} 个任务？', '只移除队列中的任务，源文件和已完成的 PDF 都会保留。', remove, '移除任务')

    def clear_files(self):
        if self.busy or not self.files: return
        def clear():
            if not self.busy: original['clear_files'](self)
        self.confirm(f'清空这 {len(self.files)} 个任务？', '只清空当前队列，源文件和已完成的 PDF 都会保留。', clear, '清空队列')

    def open_folder(self):
        folder = self.output_folder.get()
        if not folder and self.results: folder = str(Path(next(reversed(self.results.values()))['output']).parent)
        if not folder and self.files: folder = str(Path(next(iter(self.files.values()))).parent/'压缩输出')
        if folder and Path(folder).is_dir():
            try: os.startfile(folder)
            except OSError as exc: self.show_notice('无法打开位置', str(exc))
        else: self.show_notice('输出文件夹', '完成压缩后，可从这里打开保存位置。')

    def open_selected(self, event=None):
        selection = self.tree.selection()
        if not selection: return
        iid = selection[0]
        if iid in self.results:
            try: os.startfile(self.results[iid]['output'])
            except OSError as exc: self.show_notice('无法打开 PDF', str(exc))
            return
        state = self.tree.set(iid,'state')
        failed = 'error' in self.tree.item(iid,'tags')
        p = self.new_panel('error', '文件处理失败' if failed else '文件状态', 440, 300)
        if p is None: return
        label(p.body, Path(self.files[iid]).name, 12, True, wraplength=400, justify='left').pack(anchor='w', pady=(0,8))
        box = ctk.CTkTextbox(p.body, height=105, fg_color='#f0f0f0', corner_radius=8, text_color='#787878', font=('Microsoft YaHei UI',12), wrap='word')
        box._textbox.configure(selectbackground='#dedede', selectforeground='#242424')
        box.pack(fill='both', expand=True); box.insert('1.0',state); box.configure(state='disabled')
        def back(): p.hide(); self.show_queue()
        button(p.footer, '返回队列', back).pack(side='left')
        def retry(): p.hide(); self.start()
        if failed:
            b = button(p.footer, '重试队列', retry, primary=True, width=100); b.pack(side='right')
            if self.busy: b.configure(state='disabled')
        p.show()

    def save_record(self):
        self.sync_records()
        if not self.task_records:
            self.show_notice('处理记录', '添加任务后可以导出记录。'); return
        p = self.new_panel('export', '导出处理记录', 400, 260, toggle=True)
        if p is None: return
        label(p.body, '本次会话全部处理记录', 13, True).pack(anchor='w')
        label(p.body, f'{len(self.task_records)} 个文件 · {len(self.record_rows())} 条记录 · CSV', 11, color=MUTED).pack(anchor='w', pady=4)
        self.export_name = ctk.CTkEntry(p.body, height=34, corner_radius=8, border_color='#dedede', fg_color='white', font=('Microsoft YaHei UI',12))
        self.export_name._entry.configure(selectbackground='#dedede', selectforeground='#242424')
        self.export_name.insert(0,'PDF压缩记录.csv'); self.export_name.pack(fill='x', pady=10)
        label(p.body, '包含成功、失败、停止及待处理任务；保留重试历史、原因与处理时间。', 10, color=MUTED, wraplength=360, justify='left').pack(anchor='w')
        button(p.footer,'取消',p.hide,width=70).pack(side='left')
        self.export_save_btn = button(p.footer,'保存记录…',self.export_record,primary=True,width=110)
        self.export_save_btn.pack(side='right'); p.show()

    def export_record(self):
        name = Path(self.export_name.get().strip() or 'PDF压缩记录.csv').name
        path = filedialog.asksaveasfilename(parent=self.root,title='保存处理记录',defaultextension='.csv',filetypes=[('CSV 表格','*.csv')],initialfile=name)
        if not path: return
        try:
            self.write_record(path)
        except OSError as exc: self.show_notice('记录未保存',str(exc)); return
        self.panels['export'].hide()
        self.show_notice('记录已保存',path,lambda: os.startfile(str(Path(path).parent)),'打开位置')

    def close(self):
        self.hide_tip()
        if self.busy:
            def stop_exit():
                if self.busy:
                    self.cancel(); self.root.after(200,self.close_when_stopped)
                else: self.destroy_windows()
            self.confirm('停止压缩并退出？','已完成的文件会保留；未完成的任务将停止。',stop_exit,'停止并退出')
        else: self.destroy_windows()

    def destroy_windows(self):
        for panel in self.panels.values():
            if panel.drop: panel.drop.close(); panel.drop=None
        original['destroy_windows'](self)

    methods=locals().copy()
    for name in ('new_panel','show_notice','confirm','build_queue','show_queue','toggle_queue','dismiss_popovers','show_mode_menu','select_mode',
        'show_add','pick_files','pick_input_folder','show_folder_menu','pick_folder','default_folder',
        'start','set_busy','refresh_summary','remove_files','clear_files','open_folder','open_selected',
        'save_record','export_record','close','destroy_windows'):
        setattr(Window,name,methods[name])
