from pathlib import Path
import tempfile
import unittest
import sys

from drop_support import expand_dropped_paths


class DroppedFilesTests(unittest.TestCase):
    def test_unicode_spaces_braces_multi_files_and_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            a = p / '中文 空格{版本}.PDF'
            b = p / '第二份.pdf'
            a.write_bytes(b'test')
            b.write_bytes(b'test')
            found = expand_dropped_paths([str(a), str(b), str(a)])
            self.assertEqual(found, [str(a.resolve()), str(b.resolve())])

    def test_folder_drop_is_direct_children_only(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            (p / '一级.pdf').write_bytes(b'test')
            (p / '不导入.txt').write_bytes(b'test')
            (p / '子文件夹').mkdir()
            (p / '子文件夹/二级.pdf').write_bytes(b'test')
            self.assertEqual(expand_dropped_paths([folder]), [str((p / '一级.pdf').resolve())])

    def test_non_pdf_and_missing_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'not-pdf.txt'
            p.write_bytes(b'test')
            self.assertEqual(expand_dropped_paths([str(p), str(p.parent/'missing.pdf')]), [])


@unittest.skipUnless(sys.platform == 'win32', 'Native drop event test requires Windows')
class NativeWindowDropTests(unittest.TestCase):
    def test_own_window_and_child_receive_unicode_file_drop(self):
        """Exercise the component's Win32 protocol in its own test window.

        This is an in-process component test, not cross-window desktop input.
        """
        import ctypes
        from ctypes import wintypes
        import struct
        import time
        import tkinter as tk
        from tkinter import ttk
        from drop_support import WindowsFileDrop

        root = tk.Tk()
        root.withdraw()
        child = ttk.Treeview(root)
        child.pack()
        root.update_idletasks()
        child_hwnd = child.winfo_id()
        received = []
        hook = WindowsFileDrop(root, received.append)
        self.assertTrue(hook.enabled)
        self.assertIn(child_hwnd, hook.originals)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel.GlobalLock.restype = ctypes.c_void_p
        kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel.GlobalUnlock.restype = wintypes.BOOL
        user = hook.user32
        user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user.SendMessageW.restype = ctypes.c_ssize_t
        names = ['D:\\示例文件夹\\01 中文 空格{甲}.PDF', 'D:\\示例文件夹\\02_第二份.pdf']
        data = struct.pack('<IiiII', 20, 0, 0, 0, 1) + ('\0'.join(names) + '\0\0').encode('utf-16-le')
        try:
            for target in [hook.hwnd, child_hwnd]:
                memory = kernel.GlobalAlloc(0x42, len(data))
                address = kernel.GlobalLock(memory)
                ctypes.memmove(address, data, len(data))
                kernel.GlobalUnlock(memory)
                self.assertEqual(user.SendMessageW(target, hook.WM_DROPFILES, memory, 0), 0)
                end = time.monotonic() + .3
                while time.monotonic() < end:
                    root.update()
                    time.sleep(.01)
            self.assertEqual(received, [names, names])
            originals = dict(hook.originals)
            hook.close()
            for hwnd, old in originals.items():
                self.assertEqual(user.GetWindowLongPtrW(hwnd, hook.GWLP_WNDPROC), old)
        finally:
            hook.close()
            root.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
