"""One GUI per Windows session, with authenticated local named-pipe file forwarding."""
import ctypes
import os
from pathlib import Path
import queue
import threading
import time

from app_state import data_directory


class SessionMutex:
    def __init__(self, name):
        self.handle = None
        self.existing = False
        if os.name == 'nt':
            self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
            self.kernel.CreateMutexW.restype = ctypes.c_void_p
            self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            ctypes.set_last_error(0)
            self.handle = self.kernel.CreateMutexW(None, False, name)
            self.existing = ctypes.get_last_error() == 183
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class SingleInstance:
    def __init__(self):
        self.mutex = SessionMutex('Local\\PDFCompressor.Main')
        # The pipe name is user-specific; Local mutexes are session-specific.
        import hashlib
        user = str(Path.home()).casefold().encode('utf-8')
        self.address = r'\\.\pipe\PDFCompressor-' + hashlib.sha256(user).hexdigest()[:20]
        self.incoming = queue.SimpleQueue()
        self.stopping = threading.Event()
        self.listener = None
        self.thread = None
        self.key_path = data_directory() / 'ipc.key'

    def key(self, create=False):
        if create:
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self.key_path.open('xb') as stream:
                    stream.write(os.urandom(32))
            except FileExistsError:
                pass
        return self.key_path.read_bytes()

    def forward(self, files):
        from multiprocessing.connection import Client
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            try:
                with Client(self.address, family='AF_PIPE', authkey=self.key()) as conn:
                    conn.send_bytes(__import__('json').dumps(list(map(str, files))).encode('utf-8'))
                return True
            except (OSError, EOFError):
                time.sleep(.1)
        return False

    def listen(self):
        from multiprocessing.connection import Listener
        self.listener = Listener(self.address, family='AF_PIPE', authkey=self.key(create=True))
        def receive():
            while not self.stopping.is_set():
                try:
                    with self.listener.accept() as conn:
                        data = __import__('json').loads(conn.recv_bytes(1_048_576).decode('utf-8'))
                        if isinstance(data, list) and all(isinstance(x, str) for x in data):
                            self.incoming.put(data)
                except (OSError, EOFError, ValueError):
                    if self.stopping.is_set():
                        break
        self.thread = threading.Thread(target=receive, daemon=True, name='LocalFileForwarding')
        self.thread.start()

    def attach(self, app):
        def poll():
            if app.windows_destroyed:
                return
            try:
                while True:
                    files = self.incoming.get_nowait()
                    if files:
                        app.forwarded_files.extend(files)
                        app.status.set('已收到新文件，将在当前任务结束后加入队列。' if app.busy else '已收到新文件。')
                    app.root.deiconify()
                    app.root.lift()
                    if not app.busy:
                        app.consume_forwarded_files()
            except queue.Empty:
                pass
            app.root.after(150, poll)
        app.root.after(150, poll)

    def close(self):
        self.stopping.set()
        if self.listener is not None:
            self.listener.close()
        self.mutex.close()
