from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sys
import traceback

from engine import PRESETS, Cancelled, compress_pdf, format_size, fresh_path
from drop_support import WindowsFileDrop, expand_dropped_paths


def worker_batch(jobs, preset, output_folder, events, stop):
    for iid, filename in jobs:
        if stop.is_set():
            events.put(('cancelled', iid, None))
            continue
        source = Path(filename)
        events.put(('started', iid, None))
        try:
            folder = Path(output_folder) if output_folder else source.parent / '压缩输出'
            target = fresh_path(folder, source.stem + '_' + PRESETS[preset].name)
            def update(percent, message):
                events.put(('progress', iid, (percent, message)))
            result = compress_pdf(source, target, preset, update, stop)
            events.put(('done', iid, result))
        except Cancelled:
            events.put(('cancelled', iid, None))
        except Exception as exc:
            events.put(('error', iid, {'message': str(exc), 'detail': traceback.format_exc()}))
    events.put(('finished', None, None))


def launch_ui(initial_files=(), *, run_mainloop=True):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    class Window:
        def __init__(self):
            self.root = tk.Tk()
            self.root.title('PDF 高清压缩 · v1.1 拖入版')
            self.root.geometry('1040x760')
            self.root.minsize(900, 720)
            self.root.configure(bg='#eef3f8')
            icon = Path(getattr(sys, '_MEIPASS', Path(__file__).parent / 'assets')) / 'app.ico'
            if icon.is_file():
                self.root.iconbitmap(str(icon))
            self.files, self.results = {}, {}
            self.process = self.stop = self.events = None
            self.busy, self.completed, self.total = False, 0, 0
            self.output_folder = tk.StringVar()
            self.preset = tk.StringVar(value='hd')
            self.status = tk.StringVar(value='把 PDF 文件拖到窗口，或点击“添加 PDF”。')
            self.drop_handler = None
            self.folder_label = tk.StringVar(value='默认保存到原文件旁的「压缩输出」文件夹')
            self.progress = tk.DoubleVar()
            self.make_style(ttk)
            outer = ttk.Frame(self.root, style='Base.TFrame', padding=26)
            outer.pack(fill='both', expand=True)
            outer.columnconfigure(0, weight=1)
            outer.rowconfigure(3, weight=1, minsize=150)
            head = ttk.Frame(outer, style='Base.TFrame')
            head.grid(row=0, column=0, sticky='ew', pady=(0, 18))
            ttk.Label(head, text='PDF 高清压缩', style='Title.TLabel').pack(anchor='w')
            ttk.Label(head, text='拖入 PDF 即可添加，文件更轻、文字依然清晰', style='Sub.TLabel').pack(anchor='w', pady=(5, 0))
            profiles = ttk.Frame(outer, style='Card.TFrame', padding=16)
            profiles.grid(row=1, column=0, sticky='ew', pady=(0, 16))
            self.profile_buttons = []
            for index, (key, value) in enumerate(PRESETS.items()):
                profiles.columnconfigure(index, weight=1)
                card = ttk.Frame(profiles, style='Card.TFrame', padding=(8, 2))
                card.grid(row=0, column=index, sticky='nsew')
                button = ttk.Radiobutton(card, text=value.name, value=key, variable=self.preset,
                                         style='Preset.TRadiobutton')
                button.pack(anchor='w')
                self.profile_buttons.append(button)
                ttk.Label(card, text=value.description, style='Muted.TLabel').pack(anchor='w', pady=(7, 0))
            toolbar = ttk.Frame(outer, style='Base.TFrame')
            toolbar.grid(row=2, column=0, sticky='ew', pady=(0, 10))
            self.add_btn = ttk.Button(toolbar, text='＋ 添加 PDF', command=self.pick_files, style='Primary.TButton')
            self.add_btn.pack(side='left')
            self.remove_btn = ttk.Button(toolbar, text='移除所选', command=self.remove_files)
            self.remove_btn.pack(side='left', padx=8)
            self.clear_btn = ttk.Button(toolbar, text='清空列表', command=self.clear_files)
            self.clear_btn.pack(side='left')
            self.open_btn = ttk.Button(toolbar, text='打开输出文件夹', command=self.open_folder)
            self.open_btn.pack(side='right')
            table = ttk.Frame(outer, style='Card.TFrame')
            table.grid(row=3, column=0, sticky='nsew')
            self.tree = ttk.Treeview(table, columns=('file', 'before', 'after', 'saved', 'state'),
                                     show='headings', selectmode='extended', height=9)
            for name, title, width in [('file', 'PDF 文件', 345), ('before', '原大小', 90),
                                      ('after', '压缩后', 90), ('saved', '减少', 75), ('state', '状态', 180)]:
                self.tree.heading(name, text=title)
                self.tree.column(name, width=width, minwidth=65,
                                 anchor='w' if name in ('file', 'state') else 'center',
                                 stretch=name in ('file', 'state'))
            scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
            self.tree.configure(yscrollcommand=scroll.set)
            self.tree.pack(side='left', fill='both', expand=True)
            scroll.pack(side='right', fill='y')
            self.tree.tag_configure('done', foreground='#147b62')
            self.tree.tag_configure('error', foreground='#bc4242')
            self.tree.bind('<Double-1>', self.open_selected)
            self.drop_hint = ttk.Label(table, text='把 PDF 文件拖到这里\n支持多选，也可拖入文件夹',
                                       background='white', foreground='#8293a6',
                                       font=('Microsoft YaHei UI', 14), justify='center', anchor='center')
            self.update_empty_hint()
            folder = ttk.Frame(outer, style='Base.TFrame')
            folder.grid(row=4, column=0, sticky='ew', pady=(14, 8))
            ttk.Label(folder, textvariable=self.folder_label, style='Sub.TLabel', wraplength=590).pack(side='left')
            self.folder_btn = ttk.Button(folder, text='更改保存位置', command=self.pick_folder)
            self.folder_btn.pack(side='right')
            self.default_btn = ttk.Button(folder, text='恢复默认', command=self.default_folder)
            self.default_btn.pack(side='right', padx=8)
            ttk.Progressbar(outer, maximum=100, variable=self.progress, style='Blue.Horizontal.TProgressbar').grid(row=5, column=0, sticky='ew', pady=(6, 9))
            ttk.Label(outer, textvariable=self.status, style='Sub.TLabel', wraplength=900).grid(row=6, column=0, sticky='w')
            bottom = ttk.Frame(outer, style='Base.TFrame')
            bottom.grid(row=7, column=0, sticky='ew', pady=(14, 0))
            ttk.Label(bottom, text='本地处理 · 不覆盖原件 · 保留文字与颜色模式', style='MutedBase.TLabel').pack(side='left')
            self.start_btn = ttk.Button(bottom, text='开始压缩', style='Primary.TButton', command=self.start)
            self.start_btn.pack(side='right')
            self.cancel_btn = ttk.Button(bottom, text='停止', command=self.cancel, state='disabled')
            self.cancel_btn.pack(side='right', padx=8)
            self.report_btn = ttk.Button(bottom, text='导出记录', command=self.save_record)
            self.report_btn.pack(side='right')
            self.root.protocol('WM_DELETE_WINDOW', self.close)
            self.root.after(150, self.poll)
            self.add_files(initial_files)
            self.root.after_idle(self.enable_drop)

        def enable_drop(self):
            try:
                self.drop_handler = WindowsFileDrop(self.root, self.accept_drop)
                if not self.drop_handler.enabled:
                    self.status.set('请点击“添加 PDF”选择文件。')
            except Exception:
                self.status.set('拖入功能未启动，可继续使用“添加 PDF”按钮。')

        def update_empty_hint(self):
            if self.files:
                self.drop_hint.place_forget()
            else:
                self.drop_hint.place(relx=.5, rely=.5, anchor='center')

        def accept_drop(self, names):
            if self.busy:
                self.status.set('正在压缩，请在本次任务完成后再拖入新文件。')
                return
            paths = expand_dropped_paths(names)
            if not paths:
                self.status.set('没有找到 PDF，请拖入 PDF 文件或包含 PDF 的文件夹。')
                return
            added = self.add_files(paths)
            self.status.set(f'已拖入添加 {added} 份 PDF，可点击“开始压缩”。' if added else '这些 PDF 已在列表中，已自动跳过重复文件。')

        @staticmethod
        def make_style(ttk):
            style = ttk.Style()
            style.theme_use('clam')
            style.configure('.', font=('Microsoft YaHei UI', 10), background='#eef3f8', foreground='#253a50')
            style.configure('Base.TFrame', background='#eef3f8')
            style.configure('Card.TFrame', background='#ffffff')
            style.configure('Title.TLabel', background='#eef3f8', foreground='#173f70', font=('Microsoft YaHei UI', 23, 'bold'))
            style.configure('Sub.TLabel', background='#eef3f8', foreground='#5b6f83')
            style.configure('Muted.TLabel', background='white', foreground='#718295', font=('Microsoft YaHei UI', 9))
            style.configure('MutedBase.TLabel', background='#eef3f8', foreground='#718295', font=('Microsoft YaHei UI', 9))
            style.configure('Preset.TRadiobutton', background='white', font=('Microsoft YaHei UI', 11, 'bold'))
            style.map('Preset.TRadiobutton', background=[('active', 'white')])
            style.configure('TButton', padding=(13, 8), background='white', borderwidth=0)
            style.map('TButton', background=[('active', '#e1ebf5')])
            style.configure('Primary.TButton', background='#2563a6', foreground='white', font=('Microsoft YaHei UI', 10, 'bold'))
            style.map('Primary.TButton', background=[('disabled', '#a9bacb'), ('active', '#174d87')], foreground=[('disabled', '#eef3f8')])
            style.configure('Treeview', background='white', fieldbackground='white', borderwidth=0, rowheight=36, font=('Microsoft YaHei UI', 10))
            style.configure('Treeview.Heading', background='#dfe8f1', foreground='#314d6c', padding=(8, 10), font=('Microsoft YaHei UI', 10, 'bold'))
            style.configure('Blue.Horizontal.TProgressbar', background='#2b76bf', troughcolor='#dce6f0', borderwidth=0, thickness=8)

        def add_files(self, names):
            if self.busy:
                return 0
            added = 0
            existing = {str(Path(value).resolve()).casefold() for value in self.files.values()}
            for name in names:
                path = Path(name)
                if not path.is_file() or path.suffix.lower() != '.pdf' or str(path.resolve()).casefold() in existing:
                    continue
                iid = self.tree.insert('', 'end', values=(path.name, format_size(path.stat().st_size), '—', '—', '待处理', str(path.parent.resolve())))
                self.files[iid] = str(path.resolve())
                existing.add(str(path.resolve()).casefold())
                added += 1
            self.update_empty_hint()
            return added

        def pick_files(self):
            self.add_files(filedialog.askopenfilenames(parent=self.root, title='选择一个或多个 PDF', filetypes=[('PDF 文件', '*.pdf')]))

        def remove_files(self):
            if not self.busy:
                for iid in self.tree.selection():
                    self.tree.delete(iid)
                    self.files.pop(iid, None)
                    self.results.pop(iid, None)
                self.update_empty_hint()

        def clear_files(self):
            if not self.busy:
                for iid in self.tree.get_children():
                    self.tree.delete(iid)
                self.files.clear()
                self.results.clear()
                self.progress.set(0)
                self.status.set('把 PDF 文件拖到窗口，或点击“添加 PDF”。')
                self.update_empty_hint()

        def pick_folder(self):
            folder = filedialog.askdirectory(parent=self.root, title='选择压缩文件保存位置')
            if folder:
                self.output_folder.set(folder)
                self.folder_label.set('保存到：' + folder)

        def default_folder(self):
            self.output_folder.set('')
            self.folder_label.set('默认保存到原文件旁的「压缩输出」文件夹')

        def set_busy(self, busy):
            self.busy = busy
            for control in (self.add_btn, self.remove_btn, self.clear_btn, self.folder_btn, self.default_btn, self.start_btn, *self.profile_buttons):
                control.configure(state='disabled' if busy else 'normal')
            self.cancel_btn.configure(state='normal' if busy else 'disabled')

        def start(self):
            if not self.files:
                messagebox.showinfo('添加文件', '请先添加 PDF 文件。', parent=self.root)
                return
            if self.busy:
                return
            self.completed, self.total = 0, len(self.files)
            self.results.clear()
            self.progress.set(0)
            for iid in self.files:
                self.tree.set(iid, 'after', '—')
                self.tree.set(iid, 'saved', '—')
                self.tree.set(iid, 'state', '等待处理')
                self.tree.item(iid, tags=())
            self.events, self.stop = mp.Queue(), mp.Event()
            self.process = mp.Process(target=worker_batch, args=(list(self.files.items()), self.preset.get(), self.output_folder.get(), self.events, self.stop), daemon=True)
            self.set_busy(True)
            self.status.set('准备处理文件…')
            self.process.start()

        def cancel(self):
            if self.stop:
                self.stop.set()
                self.status.set('正在停止，当前图片处理结束后退出；原件不会修改。')
                self.cancel_btn.configure(state='disabled')

        def finish(self):
            if self.process:
                self.process.join(timeout=.05)
            self.set_busy(False)
            if self.stop and self.stop.is_set():
                self.status.set('已停止。已完成文件已保存，其余原件保持不变。')
            else:
                saved = sum(r['before_bytes'] - r['after_bytes'] for r in self.results.values())
                self.status.set(f'处理结束：成功 {len(self.results)}/{self.total} 个，共节省 {format_size(saved)}。双击已完成项可打开 PDF。')
                self.progress.set(100)
            self.process = None

        def poll(self):
            if self.events:
                try:
                    while True:
                        kind, iid, data = self.events.get_nowait()
                        if kind == 'finished':
                            self.finish()
                            break
                        if iid not in self.files:
                            continue
                        if kind == 'started':
                            self.tree.selection_set(iid)
                            self.tree.see(iid)
                            self.tree.set(iid, 'state', '正在压缩')
                        elif kind == 'progress':
                            percent, message = data
                            self.tree.set(iid, 'state', f'{percent}% · {message}')
                            self.status.set(f'{Path(self.files[iid]).name} · {message}')
                            self.progress.set((self.completed + percent / 100) / max(1, self.total) * 100)
                        elif kind in ('done', 'error', 'cancelled'):
                            self.completed += 1
                            if kind == 'done':
                                self.results[iid] = data
                                self.tree.set(iid, 'after', format_size(data['after_bytes']))
                                self.tree.set(iid, 'saved', f'{data["reduction_percent"]:.1f}%')
                                self.tree.set(iid, 'state', '已精简 · 原画质保留' if data['unchanged_copy'] else '完成 · 核验通过')
                                self.tree.item(iid, tags=('done',))
                            elif kind == 'error':
                                self.tree.set(iid, 'state', data)
                                self.tree.item(iid, tags=('error',))
                            else:
                                self.tree.set(iid, 'state', '已停止')
                            self.progress.set(self.completed / max(1, self.total) * 100)
                except queue.Empty:
                    pass
                if self.busy and self.process and not self.process.is_alive():
                    # Leave one polling interval for the multiprocessing queue feeder.
                    self.root.after(200, self.check_exit)
            self.root.after(150, self.poll)

        def check_exit(self):
            if self.busy and self.process and not self.process.is_alive():
                for iid in self.files:
                    state = self.tree.set(iid, 'state')
                    if state.startswith(('等待', '正在', '0%', '1%')) or '%' in state:
                        self.tree.set(iid, 'state', '未完成，请重新尝试')
                self.finish()

        def open_folder(self):
            folder = self.output_folder.get()
            if not folder and self.results:
                folder = str(Path(next(reversed(self.results.values()))['output']).parent)
            if not folder and self.files:
                folder = str(Path(next(iter(self.files.values()))).parent / '压缩输出')
            if folder and Path(folder).is_dir():
                os.startfile(folder)
            else:
                messagebox.showinfo('输出文件夹', '完成压缩后，可从这里打开保存位置。', parent=self.root)

        def open_selected(self, event=None):
            selection = self.tree.selection()
            if selection and selection[0] in self.results:
                os.startfile(self.results[selection[0]]['output'])
            elif selection:
                messagebox.showinfo('文件状态', self.tree.set(selection[0], 'state'), parent=self.root)

        def save_record(self):
            if not self.results:
                messagebox.showinfo('处理记录', '完成压缩后可以导出记录。', parent=self.root)
                return
            path = filedialog.asksaveasfilename(parent=self.root, title='保存处理记录', defaultextension='.csv', filetypes=[('CSV 表格', '*.csv')], initialfile='PDF压缩记录.csv')
            if path:
                with open(path, 'w', newline='', encoding='utf-8-sig') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(['原文件', '压缩后文件', '模式', '页数', '原大小', '压缩后', '减少比例'])
                    for r in self.results.values():
                        writer.writerow([r['source'], r['output'], r['preset']['name'], r['pages'], format_size(r['before_bytes']), format_size(r['after_bytes']), f'{r["reduction_percent"]}%'])

        def close(self):
            if self.busy:
                self.cancel()
                self.root.after(200, self.close_when_stopped)
            else:
                if self.drop_handler:
                    self.drop_handler.close()
                self.root.destroy()

        def close_when_stopped(self):
            if self.process and self.process.is_alive():
                self.root.after(200, self.close_when_stopped)
            else:
                if self.drop_handler:
                    self.drop_handler.close()
                self.root.destroy()

    from mini_ui import install_mini_ui
    install_mini_ui(Window, tk, ttk, filedialog, messagebox)
    from task_flow import install_task_flow
    install_task_flow(Window)
    from desktop_ui import install_desktop_ui
    install_desktop_ui(Window)
    app = Window()
    app.add_files(initial_files)
    if run_mainloop:
        try:
            app.root.mainloop()
        finally:
            app.shutdown_workers()
    return app


def main():
    mp.freeze_support()
    parser = argparse.ArgumentParser(description='本地 PDF 高清压缩工具')
    parser.add_argument('files', nargs='*')
    parser.add_argument('--compress', metavar='PDF')
    parser.add_argument('--output', metavar='PDF')
    parser.add_argument('--preset', choices=PRESETS, default='hd')
    parser.add_argument('--report')
    args = parser.parse_args()
    if args.compress:
        if not args.output:
            parser.error('--compress requires --output')
        try:
            result = compress_pdf(args.compress, args.output, args.preset)
        except Exception as exc:
            result = {'error': str(exc)}
            if args.report:
                Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
            return 2
        if args.report:
            Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
        return 0
    from single_instance import SingleInstance
    instance = SingleInstance()
    try:
        if instance.mutex.existing:
            if not instance.forward(args.files):
                import tkinter.messagebox
                tkinter.messagebox.showerror('软件正在运行', '已有实例尚未响应，请稍后重试；不会重复打开新的程序。')
                return 3
            return 0
        instance.listen()
        app = launch_ui(args.files, run_mainloop=False)
        instance.attach(app)
        try:
            app.root.mainloop()
        finally:
            app.shutdown_workers()
        return 0
    finally:
        instance.close()


if __name__ == '__main__':
    raise SystemExit(main())
