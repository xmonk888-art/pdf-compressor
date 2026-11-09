"""Desktop interaction, visible status, local preferences and file operations."""
from datetime import datetime
import os
from pathlib import Path
import uuid

from app_state import LocalState


def install_desktop_ui(Window):
    old_init = Window.__init__
    old_refresh = Window.refresh_summary
    old_destroy = Window.destroy_windows
    old_pick_folder = Window.pick_folder
    old_default_folder = Window.default_folder

    def init(self):
        self.local_state = LocalState()
        self.forwarded_files = []
        self.busy_mutex = None
        self._saved_on_exit = False
        self.record_path = self.local_state.directory / 'records' / (
            datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8] + '.csv')
        old_init(self)
        folder = self.local_state.values.get('output_folder', '')
        if isinstance(folder, str):
            self.output_folder.set(folder)
            self.folder_label.set(folder or '原文件旁的「压缩输出」文件夹')
        size = self.local_state.values.get('queue_size')
        if isinstance(size, list) and len(size) == 2 and all(isinstance(x, int) for x in size):
            self.panels['queue'].dock_size = (max(700, min(size[0], 1600)), max(330, min(size[1], 950)))
        position = self.local_state.values.get('main_position')
        if isinstance(position, list) and len(position) == 2 and all(isinstance(x, int) for x in position):
            from ui_shell import place_in_work_area
            self.root.after_idle(lambda: place_in_work_area(self.root, *position))
        self.root.unbind('<Control-o>')
        self.root.unbind('<Control-l>')
        self.root.bind_all('<Control-o>', lambda e: self.route_shortcut(self.show_add))
        self.root.bind_all('<Control-l>', lambda e: self.route_shortcut(self.toggle_queue))
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.refresh_actions())
        self.tree.bind('<Button-3>', self.show_file_menu)
        self.status_label.bind('<Double-Button-1>', lambda e: self.show_notice('完整状态', self.status.get()))
        if self.local_state.warning:
            self.status.set(self.local_state.warning)
        self.refresh_summary()

    def refresh_summary(self):
        old_refresh(self)
        self.refresh_actions()

    def route_shortcut(self, action):
        if self.root.grab_current() is None:
            action()
        return 'break'

    def refresh_actions(self):
        if not hasattr(self, 'tree'):
            return
        records = getattr(self, 'task_records', {})
        states = [records.get(i, {}).get('state', 'pending') for i in self.files]
        selected = self.tree.selection()
        def enable(name, yes):
            control = getattr(self, name, None)
            if control is not None:
                control.configure(state='normal' if yes else 'disabled')
        enable('start_btn', self.busy or any(s != 'done' for s in states))
        if self.busy and self.stop is not None and self.stop.is_set():
            enable('start_btn', False)
        enable('retry_btn', not self.busy and any(s in ('failed', 'startup_failed') for s in states))
        enable('resume_btn', not self.busy and any(s in ('pending', 'stopped', 'interrupted') for s in states))
        enable('remove_btn', bool(selected) and not self.busy)
        enable('clear_btn', bool(self.files) and not self.busy)
        enable('selected_folder_btn', bool(selected) and selected[0] in self.results)
        enable('report_btn', bool(records))
        folder = self.output_folder.get()
        enable('open_btn', bool(self.results) or bool(folder and Path(folder).is_dir()))
        if hasattr(self, 'selected_path'):
            text = '选择文件可查看完整路径；右键打开位置或复制路径。'
            if selected and selected[0] in self.files:
                iid = selected[0]
                text = '源：' + self.files[iid]
                if iid in self.results:
                    text += '\n输出：' + self.results[iid]['output']
            self.selected_path.set(text)

    def persist_records(self):
        if not self.task_records:
            return True
        temp = self.record_path.with_suffix('.tmp')
        try:
            self.record_path.parent.mkdir(parents=True, exist_ok=True)
            self.write_record(temp)
            temp.replace(self.record_path)
            return True
        except OSError as exc:
            self.status.set(f'处理记录未自动保存，可手动导出：{exc}')
            return False
        finally:
            temp.unlink(missing_ok=True)

    def save_preferences(self):
        try:
            values = dict(output_folder=self.output_folder.get())
            if self.root.state() == 'normal':
                values['main_position'] = [self.root.winfo_x(), self.root.winfo_y()]
            if self.queue_window.state() == 'normal':
                values['queue_size'] = list(self.panels['queue'].dock_size)
            self.local_state.save(**values)
        except OSError as exc:
            self.status.set(f'设置未保存：{exc}')

    def pick_folder(self):
        old_pick_folder(self)
        self.save_preferences()
        self.refresh_actions()

    def default_folder(self):
        old_default_folder(self)
        self.save_preferences()
        self.refresh_actions()

    def destroy_windows(self):
        if self.windows_destroyed:
            return
        if not self.busy and not self._saved_on_exit:
            self.persist_records()
            self.save_preferences()
            self._saved_on_exit = True
        old_destroy(self)

    def consume_forwarded_files(self):
        if self.busy or not self.forwarded_files:
            return
        names, self.forwarded_files = self.forwarded_files, []
        from drop_support import expand_dropped_paths
        count = self.add_files(expand_dropped_paths(names))
        self.status.set(f'已加入 {count} 个文件。' if count else '收到的文件已在队列中，或不是可读取的 PDF。')

    def open_history(self):
        self.persist_records()
        folder = self.local_state.directory / 'records'
        try:
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError as exc:
            self.show_notice('无法打开历史记录', str(exc))

    def open_source_folder(self):
        selected = self.tree.selection()
        if selected:
            try:
                os.startfile(str(Path(self.files[selected[0]]).parent))
            except OSError as exc:
                self.show_notice('无法打开源文件位置', str(exc))

    def copy_paths(self, output=False):
        paths = [self.results[i]['output'] if output else self.files[i]
                 for i in self.tree.selection() if not output or i in self.results]
        if paths:
            self.root.clipboard_clear()
            self.root.clipboard_append('\n'.join(paths))
            self.status.set(f'已复制 {len(paths)} 个路径。')

    def show_selected_details(self):
        selected = self.tree.selection()
        if not selected:
            return
        iid = selected[0]
        self.sync_records()
        from task_flow import STATES
        record = self.task_records[iid]
        lines = ['源文件：' + record['source'], '当前状态：' + STATES[record['state']]]
        if iid in self.results:
            lines.append('输出文件：' + self.results[iid]['output'])
        for number, attempt in enumerate(record['attempts'], 1):
            lines.append(f'\n第 {number} 次：{STATES[attempt["state"]]}  {attempt["submitted"]}')
            if attempt['error']:
                lines.append(attempt['error'])
        self.show_error_details('文件详情', Path(record['source']).name, '\n'.join(lines), source_iid=iid)

    def show_file_menu(self, event):
        import tkinter as tk
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
        menu = tk.Menu(self.root, tearoff=False, bg='#fafafa', fg='#242424',
                       activebackground='#dedede', activeforeground='#242424')
        menu.add_command(label='打开输出 PDF', command=self.open_selected,
                         state='normal' if iid in self.results else 'disabled')
        menu.add_command(label='打开输出位置', command=self.open_selected_folder,
                         state='normal' if iid in self.results else 'disabled')
        menu.add_command(label='打开源文件位置', command=self.open_source_folder)
        menu.add_separator()
        menu.add_command(label='复制源文件路径', command=self.copy_paths)
        menu.add_command(label='复制输出路径', command=lambda: self.copy_paths(True),
                         state='normal' if iid in self.results else 'disabled')
        menu.add_command(label='查看处理详情', command=self.show_selected_details)
        menu.add_separator()
        menu.add_command(label='移除任务', command=self.remove_files,
                         state='disabled' if self.busy else 'normal')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    methods = locals().copy()
    Window.__init__ = init
    for name in ('refresh_summary', 'refresh_actions', 'route_shortcut', 'persist_records', 'save_preferences',
                 'pick_folder', 'default_folder', 'destroy_windows', 'consume_forwarded_files',
                 'open_history', 'open_source_folder', 'copy_paths', 'show_selected_details', 'show_file_menu'):
        setattr(Window, name, methods[name])
