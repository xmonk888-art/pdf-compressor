"""Task bookkeeping and recovery. The compression engine is deliberately unchanged."""
import csv
from datetime import datetime
import multiprocessing as mp
import os
from pathlib import Path
import queue
import time
import traceback

from engine import PRESETS, format_size


STATES = {'pending': '待处理', 'queued': '等待处理', 'running': '正在压缩',
          'done': '成功', 'failed': '失败', 'stopped': '已停止',
          'interrupted': '异常中断', 'startup_failed': '启动失败'}


def install_task_flow(Window):
    original_init = Window.__init__
    original_add = Window.add_files
    original_destroy = Window.destroy_windows

    def init(self):
        self.task_records = {}
        self.active_jobs = []
        self.exit_deadline = None
        self.retired_workers = []
        self.shutdown_requested = False
        self.windows_destroyed = False
        original_init(self)
        self.root.report_callback_exception = self.callback_error

    def sync_records(self):
        for iid, source in self.files.items():
            if iid not in self.task_records:
                self.task_records[iid] = {'source': source, 'state': 'pending', 'attempts': []}

    def add_files(self, names):
        count = original_add(self, names)
        self.sync_records()
        if count:
            self.status.set(f'已添加 {count} 个 PDF，共 {len(self.files)} 个任务。')
        self.refresh_summary()
        return count

    def current_attempt(self, iid):
        return self.task_records[iid]['attempts'][-1]

    def start(self, states=None):
        if self.busy or self.shutdown_requested:
            return
        if not self.files:
            self.show_add()
            return
        self.sync_records()
        jobs = [(i, f) for i, f in self.files.items()
                if self.task_records[i]['state'] != 'done'
                and (states is None or self.task_records[i]['state'] in states)]
        if not jobs:
            self.show_notice('没有可处理任务', '成功项已保留，没有符合条件的失败或未完成任务。')
            return
        for key, panel in self.panels.items():
            if key != 'queue':
                panel.hide()
        self.active_jobs = [i for i, _ in jobs]
        self.completed, self.total = 0, len(jobs)
        self.exit_deadline = None
        self.progress.set(0)
        for iid, source in jobs:
            record = self.task_records[iid]
            record['state'] = 'queued'
            try:
                before = Path(source).stat().st_size
            except OSError:
                before = None
            record['attempts'].append(dict(state='queued', preset=self.preset.get(),
                folder=self.output_folder.get() or str(Path(source).parent / '压缩输出'),
                submitted=datetime.now().isoformat(timespec='seconds'), started='', ended='',
                before_bytes=before, seconds='', error='', detail='', result=None))
            self.tree.set(iid, 'state', '等待处理')
            self.tree.set(iid, 'after', '—')
            self.tree.set(iid, 'saved', '—')
            self.tree.item(iid, tags=())
        from app import worker_batch
        from single_instance import SessionMutex
        self.busy_mutex = SessionMutex('Local\\PDFCompressor.Busy')
        self.set_busy(True)
        self.status.set(f'准备处理 {self.total} 个任务，成功项已保留…')
        try:
            self.events, self.stop = mp.Queue(), mp.Event()
            self.process = mp.Process(target=worker_batch,
                args=(jobs, self.preset.get(), self.output_folder.get(), self.events, self.stop), daemon=True)
            self.process.start()
        except Exception as exc:
            detail = traceback.format_exc()
            self.fail_unfinished('startup_failed', f'无法启动处理进程：{exc}', detail)
            self.finish(abnormal='启动失败：请查看任务详情后重试。')
            self.show_error_details('任务启动失败', str(exc), detail)

    def retry_failed(self):
        self.start({'failed', 'startup_failed'})

    def resume_incomplete(self):
        self.start({'pending', 'stopped', 'interrupted'})

    def finish_attempt(self, iid, state, error='', detail='', result=None):
        record = self.task_records[iid]
        attempt = self.current_attempt(iid)
        record['state'] = attempt['state'] = state
        attempt.update(ended=datetime.now().isoformat(timespec='seconds'), error=error,
                       detail=detail, result=result)
        tick = attempt.pop('_tick', None)
        attempt['seconds'] = round(time.monotonic() - tick, 2) if tick is not None else ''
        if result:
            self.results[iid] = result
            attempt['seconds'] = result['seconds']
            self.tree.set(iid, 'before', format_size(result['before_bytes']))
            self.tree.set(iid, 'after', format_size(result['after_bytes']))
            self.tree.set(iid, 'saved', f'{result["reduction_percent"]:.1f}%')
            text = '已精简 · 原画质保留' if result['unchanged_copy'] else '完成 · 核验通过'
            self.tree.item(iid, tags=('done',))
        else:
            text = error or STATES[state]
            self.tree.item(iid, tags=('error',) if state in ('failed', 'startup_failed', 'interrupted') else ())
        self.tree.set(iid, 'state', text)

    def fail_unfinished(self, state, message, detail):
        for iid in self.active_jobs:
            if self.task_records[iid]['state'] in ('queued', 'running'):
                self.finish_attempt(iid, state, message, detail)

    def finish(self, abnormal=''):
        process, events = self.process, self.events
        stopped = self.stop is not None and self.stop.is_set()
        self.process = self.events = None
        self.exit_deadline = None
        # A final queue message does not mean the OS process has exited yet.
        # Keep ownership until the process and its queue have been reclaimed.
        self.retired_workers.append((process, events))
        self.reap_workers()
        self.set_busy(False)
        if self.busy_mutex is not None:
            self.busy_mutex.close()
            self.busy_mutex = None
        if abnormal:
            self.status.set(abnormal)
        elif stopped:
            self.status.set('已停止。成功项已保存，可点击“继续未完成”。')
        else:
            good = sum(self.task_records[i]['state'] == 'done' for i in self.active_jobs)
            bad = len(self.active_jobs) - good
            self.status.set(f'处理结束：本轮成功 {good} 个，失败 {bad} 个；已有成功项保留。')
            self.progress.set(100)
        self.persist_records()
        self.root.after_idle(self.consume_forwarded_files)

    def poll(self):
        if self.windows_destroyed:
            return
        self.reap_workers()
        if self.events is not None:
            try:
                while True:
                    kind, iid, data = self.events.get_nowait()
                    if kind == 'finished':
                        self.finish()
                        break
                    if iid not in self.files or iid not in self.active_jobs:
                        continue
                    attempt = self.current_attempt(iid)
                    if kind == 'started':
                        self.task_records[iid]['state'] = attempt['state'] = 'running'
                        attempt.update(started=datetime.now().isoformat(timespec='seconds'), _tick=time.monotonic())
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
                            self.finish_attempt(iid, 'done', result=data)
                        elif kind == 'error':
                            info = data if isinstance(data, dict) else {'message': str(data), 'detail': str(data)}
                            self.finish_attempt(iid, 'failed', info['message'], info['detail'])
                        else:
                            self.finish_attempt(iid, 'stopped')
                        self.progress.set(self.completed / max(1, self.total) * 100)
            except queue.Empty:
                pass
            if self.busy and self.process is not None and not self.process.is_alive():
                if self.exit_deadline is None:
                    self.exit_deadline = time.monotonic() + .6
                elif time.monotonic() >= self.exit_deadline:
                    code = self.process.exitcode
                    message = f'处理进程异常退出（退出码 {code}），可继续未完成任务。'
                    self.fail_unfinished('interrupted', message, message)
                    self.finish(abnormal=message)
                    self.show_error_details('处理异常中断', message, message)
        if not self.windows_destroyed:
            self.root.after(150, self.poll)

    def reap_workers(self, blocking=False):
        remaining = []
        for process, events in self.retired_workers:
            if process is not None:
                if process.pid is not None:
                    # An exceptional main-loop exit must keep draining while
                    # waiting: a child queue feeder can otherwise block its exit.
                    while blocking and process.is_alive():
                        if events is not None:
                            try:
                                events.get(timeout=.05)
                            except (queue.Empty, EOFError, OSError):
                                pass
                        process.join(timeout=.05)
                    process.join(timeout=0)
                    if process.is_alive():
                        remaining.append((process, events))
                        continue
                process.close()
            if events is not None:
                events.close()
                events.join_thread()
        self.retired_workers = remaining

    def close_when_stopped(self):
        if self.busy:
            self.root.after(100, self.close_when_stopped)
        else:
            self.destroy_windows()

    def destroy_windows(self):
        if self.windows_destroyed:
            return
        self.shutdown_requested = True
        if self.busy:
            self.cancel()
            self.root.after(100, self.destroy_windows)
            return
        self.reap_workers()
        if self.retired_workers:
            self.status.set('正在退出，等待后台任务释放…')
            self.root.after(100, self.destroy_windows)
            return
        self.windows_destroyed = True
        # Remove timers owned by this Tcl interpreter before their Python
        # callbacks are deleted with the windows (poll, tooltips, DPI checks).
        for timer in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            # Cancel the Tcl timer only. Each widget deletes its own registered
            # Python command on destruction; deleting it here would do so twice.
            self.root.tk.call('after', 'cancel', timer)
        original_destroy(self)

    def shutdown_workers(self):
        """Main-loop exit also owns cleanup, including an exceptional exit."""
        if self.stop is not None:
            self.stop.set()
        if self.process is not None or self.events is not None:
            self.retired_workers.append((self.process, self.events))
            self.process = self.events = None
        self.reap_workers(blocking=True)
        if self.busy_mutex is not None:
            self.busy_mutex.close()
            self.busy_mutex = None

    def show_error_details(self, title, message, detail, iid=None, *, source_iid=None):
        import customtkinter as ctk
        from ui_shell import label, button, MUTED
        source = (title, source_iid) if source_iid is not None else None
        old = self.panels.get('error')
        if source is not None and old in self.dock.panels and old.detail_source != source:
            old.hide()
        p = self.new_panel('error', title, 490, 350, toggle=source is not None)
        if p is None: return
        p.detail_source = source
        label(p.body, message, 12, color=MUTED, wraplength=450, justify='left').pack(anchor='w', fill='x')
        box = ctk.CTkTextbox(p.body, height=140, fg_color='#f0f0f0', text_color='#545454',
                            font=('Microsoft YaHei UI', 11), wrap='word')
        box._textbox.configure(selectbackground='#dedede', selectforeground='#242424')
        box.pack(fill='both', expand=True, pady=8)
        box.insert('1.0', detail or message)
        box.configure(state='disabled')
        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(f'{title}\n{message}\n{detail}')
        self.copy_error_btn = button(p.footer, '复制详情', copy, width=80)
        self.copy_error_btn.pack(side='left')
        button(p.footer, '返回队列', lambda: (p.hide(), self.show_queue()), width=80).pack(side='left', padx=6)
        if iid is not None:
            state = self.task_records[iid]['state']
            fn = self.retry_failed if state in ('failed', 'startup_failed') else self.resume_incomplete
            b = button(p.footer, '重试失败项' if state in ('failed', 'startup_failed') else '继续未完成',
                       lambda: (p.hide(), fn()), primary=True, width=110)
            b.pack(side='right')
            if self.busy:
                b.configure(state='disabled')
        p.show()

    def callback_error(self, exc_type, exc, tb):
        detail = ''.join(traceback.format_exception(exc_type, exc, tb))
        self.show_error_details('操作未完成', str(exc), detail)

    def open_selected(self, event=None):
        if event is not None:
            iid = self.tree.identify_row(event.y)
            if not iid:
                return
            self.tree.selection_set(iid)
        selection = self.tree.selection()
        if not selection:
            return
        iid = selection[0]
        if iid in self.results:
            try:
                os.startfile(self.results[iid]['output'])
            except OSError as exc:
                self.show_error_details('无法打开 PDF', str(exc), traceback.format_exc())
            return
        self.sync_records()
        record = self.task_records[iid]
        attempt = record['attempts'][-1] if record['attempts'] else {}
        message = f'{Path(record["source"]).name}\n{STATES[record["state"]]}'
        self.show_error_details('文件状态', message, attempt.get('detail') or attempt.get('error') or self.tree.set(iid, 'state'),
                                iid if record['state'] in ('failed', 'startup_failed', 'stopped', 'interrupted') else None,
                                source_iid=iid)

    def open_selected_folder(self):
        selection = self.tree.selection()
        if not selection:
            self.show_notice('选择文件', '请先在队列中选择一个文件。')
            return
        iid = selection[0]
        if iid not in self.results:
            self.show_notice('尚无输出文件', '所选文件尚未成功完成压缩，没有可打开的保存位置。')
            return
        folder = Path(self.results[iid]['output']).parent
        try:
            if not folder.is_dir():
                raise OSError('保存文件夹已被移动或删除。')
            os.startfile(str(folder))
        except OSError as exc:
            self.show_error_details('无法打开位置', str(exc), traceback.format_exc())

    def record_rows(self):
        self.sync_records()
        rows = []
        for iid, record in self.task_records.items():
            for number, attempt in enumerate(record['attempts'] or [{}], 1):
                result = attempt.get('result') or {}
                before = attempt.get('before_bytes')
                rows.append([record['source'], result.get('output', ''),
                    PRESETS[attempt['preset']].name if attempt.get('preset') else '',
                    result.get('pages', ''), format_size(before) if before is not None else '',
                    format_size(result['after_bytes']) if result else '',
                    f'{result["reduction_percent"]}%' if result else '',
                    STATES[attempt.get('state', 'pending')], attempt.get('error', ''),
                    attempt.get('submitted', ''), attempt.get('started', ''), attempt.get('ended', ''),
                    attempt.get('seconds', ''), attempt.get('folder', ''), number if attempt else 0,
                    '在队列' if iid in self.files else '已移除', attempt.get('detail', '')])
        return rows

    def write_record(self, path):
        with open(path, 'w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.writer(stream)
            writer.writerow(['原文件', '压缩后文件', '模式', '页数', '原大小', '压缩后', '减少比例',
                '状态', '失败原因', '提交时间', '开始时间', '结束时间', '耗时秒', '保存位置', '尝试次数', '队列状态', '错误详情'])
            writer.writerows(self.record_rows())

    methods = locals().copy()
    Window.__init__ = init
    for name in ('sync_records', 'add_files', 'current_attempt', 'start', 'retry_failed', 'resume_incomplete',
                 'finish_attempt', 'fail_unfinished', 'finish', 'poll', 'show_error_details', 'callback_error',
                 'open_selected', 'open_selected_folder', 'record_rows', 'write_record',
                 'reap_workers', 'close_when_stopped', 'destroy_windows', 'shutdown_workers'):
        setattr(Window, name, methods[name])
