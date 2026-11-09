"""Local user preferences and processing records; independent of installation path."""
import json
import os
from pathlib import Path
import uuid


def data_directory():
    return Path(os.environ.get('PDFCOMPRESSOR_DATA_DIR') or
                str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'PDFCompressor'))


class LocalState:
    def __init__(self):
        self.directory = data_directory()
        self.path = self.directory / 'settings.json'
        self.warning = ''
        try:
            data = json.loads(self.path.read_text('utf-8')) if self.path.exists() else {}
            self.values = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.values = {}
            self.warning = '设置读取失败，已使用默认设置。'

    def save(self, **values):
        self.values.update(values)
        self.directory.mkdir(parents=True, exist_ok=True)
        temp = self.directory / f'.settings-{uuid.uuid4().hex}.tmp'
        try:
            temp.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), 'utf-8')
            temp.replace(self.path)
        finally:
            temp.unlink(missing_ok=True)
