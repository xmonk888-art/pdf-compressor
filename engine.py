"""Local PDF image compression; page drawing operators and color spaces stay intact."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable
import hashlib
import math
import os
import re
import shutil
import time
import uuid
import zlib

import pymupdf as fitz
from PIL import Image, ImageChops, ImageStat


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    dpi: int
    fine_dpi: int
    quality: int
    render_limit: float
    description: str


PRESETS = {
    'hd': Preset('hd', '高清保真', 300, 600, 94, 2.5, '适合展册、产品资料和常规打印'),
    'balanced': Preset('balanced', '日常分享', 200, 400, 90, 4.0, '清晰度与文件大小兼顾'),
    'small': Preset('small', '小巧预览', 144, 300, 85, 7.0, '适合手机预览和快速传输'),
}


class CompressionError(Exception):
    pass


class Cancelled(Exception):
    pass


def format_size(size: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f'{size:.1f} {unit}' if unit != 'B' else f'{size} B'
        size /= 1024


def fresh_path(folder: Path, stem: str, suffix: str = '.pdf') -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    result = folder / (stem + suffix)
    number = 2
    while result.exists():
        result = folder / f'{stem}_{number}{suffix}'
        number += 1
    return result


def _cancel(event):
    if event is not None and event.is_set():
        raise Cancelled('任务已停止，原文件未修改。')


def _stamp(path: Path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _content_digest(doc, page):
    h = hashlib.sha256()
    for xref in page.get_contents():
        stream = doc.xref_stream(xref)
        h.update(len(stream).to_bytes(8, 'big'))
        h.update(stream)
    return h.hexdigest()


def _safe_colorspace(doc, xref):
    """Do not re-encode Indexed, CMYK, spot, calibrated or unresolved color spaces."""
    kind, value = doc.xref_get_key(xref, 'ColorSpace')
    if kind == 'xref':
        value = doc.xref_object(int(value.split()[0]), compressed=True)
    if value in ('/DeviceRGB', '/DeviceGray'):
        return True
    if re.match(r'^\[\s*/ICCBased\b', value):
        match = re.search(r'/ICCBased\s+(\d+)\s+0\s+R', value)
        if match:
            return doc.xref_get_key(int(match.group(1)), 'N')[1] in ('1', '3')
    return False


def _replace_image(doc, xref, pixmap, data, codec):
    color = doc.xref_get_key(xref, 'ColorSpace')
    doc.update_stream(xref, data, compress=False)
    for key, value in (
        ('Width', str(pixmap.width)), ('Height', str(pixmap.height)),
        ('BitsPerComponent', '8'), ('Filter', '/DCTDecode' if codec == 'jpeg' else '/FlateDecode'),
        ('DecodeParms', 'null'),
    ):
        doc.xref_set_key(xref, key, value)
    if color != doc.xref_get_key(xref, 'ColorSpace'):
        raise CompressionError('颜色配置校验未通过，已停止生成。')


def compress_pdf(source, destination, preset_key='hd', progress: Callable | None = None,
                 cancel_event=None, verify_render=True):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    preset = PRESETS[preset_key]
    if source == destination:
        raise CompressionError('输出文件不能覆盖原文件。')
    if destination.exists():
        raise CompressionError('输出文件已经存在，请换一个文件名。')
    if not source.is_file() or source.suffix.lower() != '.pdf':
        raise CompressionError('请选择可读取的 PDF 文件。')
    stamp, started = _stamp(source), time.monotonic()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f'.pdfhq-{uuid.uuid4().hex}.partial.pdf'
    doc = original = final = None

    def emit(percent, message):
        if progress:
            progress(max(0, min(100, int(percent))), message)

    try:
        _cancel(cancel_event)
        emit(1, '读取文件与页面')
        doc = fitz.open(source)
        if not doc.is_pdf or doc.page_count == 0:
            raise CompressionError('文件不是有效 PDF，或没有页面。')
        if doc.needs_pass:
            raise CompressionError('文件已加密，请先在 PDF 软件中另存为未加密副本。')
        if doc.get_sigflags() > 0:
            raise CompressionError('文件包含签名信息，请使用未签名的副本进行压缩。')
        count = doc.page_count
        rows, dimensions, fine_dimensions = {}, {}, set()
        before_pages = []
        fine_words = re.compile(r'证书|专利|资质|荣誉|certificate|certification|patent', re.I)
        for index, page in enumerate(doc):
            _cancel(cancel_event)
            text = page.get_text()
            before_pages.append((tuple(page.rect), text, _content_digest(doc, page)))
            fine_page = bool(fine_words.search(text))
            # No image hashes: this avoids decoding every very large image just to find DPI.
            # Identical pixel dimensions share the most conservative placement resolution.
            for info in page.get_image_info(hashes=False, xrefs=False):
                a, b, c, d, _, _ = info['transform']
                width, height = math.hypot(a, b), math.hypot(c, d)
                if min(width, height) <= .001:
                    continue
                dim = info['width'], info['height']
                dpi = min(dim[0] * 72 / width, dim[1] * 72 / height)
                dimensions[dim] = min(dpi, dimensions.get(dim, float('inf')))
                if fine_page:
                    fine_dimensions.add(dim)
            for row in page.get_images(full=True):
                rows.setdefault(row[0], row)
            emit(2 + 8 * (index + 1) / count, '分析图片分辨率')

        plans, mask_users = [], defaultdict(list)
        for xref, row in rows.items():
            dim = row[2], row[3]
            dpi = dimensions.get(dim, 0)
            target = preset.fine_dpi if dim in fine_dimensions or max(dim) >= 10000 else preset.dpi
            power = max(0, min(5, int(math.floor(math.log2(dpi / target))))) if dpi >= target else 0
            item = dict(xref=xref, mask=row[1], dimensions=dim, dpi=dpi,
                        target=target, power=power, original_bytes=len(doc.xref_stream_raw(xref)))
            plans.append(item)
            if row[1]:
                mask_users[row[1]].append(item)
        for users in mask_users.values():
            # Keep shared masks at original resolution: a skipped image may still
            # refer to the same mask, so changing it independently is unsafe.
            power = 0 if len(users) > 1 else users[0]['power']
            for item in users:
                item['power'] = power

        changed, masks, protected = [], set(), 0
        for index, item in enumerate(plans):
            _cancel(cancel_event)
            xref, power = item['xref'], item['power']
            row = rows[xref]
            emit(10 + 62 * index / max(1, len(plans)), f'优化图片 {index + 1}/{len(plans)}')
            if (row[4] != 8 or doc.xref_get_key(xref, 'ImageMask')[1] == 'true'
                    or doc.xref_get_key(xref, 'Decode')[0] != 'null'
                    or doc.xref_get_key(xref, 'Mask')[0] != 'null'
                    or not _safe_colorspace(doc, xref)):
                protected += 1
                continue
            if row[8] == 'DCTDecode' and not power:
                continue
            if item['original_bytes'] < 180000 and not power:
                continue
            pix = fitz.Pixmap(doc, xref)
            if pix.colorspace is None or pix.colorspace.n not in (1, 3) or pix.alpha:
                protected += 1
                continue
            mask = None
            if item['mask']:
                mask = fitz.Pixmap(doc, item['mask'])
                if mask.width != pix.width or mask.height != pix.height or mask.n != 1:
                    protected += 1
                    continue
            if power:
                pix.shrink(power)
            jpeg = pix.tobytes('jpeg', jpg_quality=preset.quality)
            lossless = zlib.compress(pix.samples, 7)
            data, codec = (jpeg, 'jpeg') if len(jpeg) < len(lossless) else (lossless, 'flate')
            if not power and len(data) >= item['original_bytes'] * .96:
                continue
            _replace_image(doc, xref, pix, data, codec)
            if mask is not None and power and item['mask'] not in masks:
                mask.shrink(power)
                if (mask.width, mask.height) != (pix.width, pix.height):
                    raise CompressionError('图片透明边缘校验未通过。')
                _replace_image(doc, item['mask'], mask, zlib.compress(mask.samples, 7), 'flate')
                masks.add(item['mask'])
            changed.append(dict(source_size=item['dimensions'], final_size=(pix.width, pix.height),
                                codec=codec, color_space_unchanged=True))
            pix = mask = None
            fitz.TOOLS.store_shrink(100)

        _cancel(cancel_event)
        emit(74, '清理冗余数据并保存')
        for page in doc:
            doc.xref_set_key(page.xref, 'PieceInfo', 'null')
        doc.xref_set_key(doc.pdf_catalog(), 'PieceInfo', 'null')
        doc.save(temporary, garbage=3, deflate=True)
        doc.close()
        doc = None
        original, final = fitz.open(source), fitz.open(temporary)
        if len(final) != count:
            raise CompressionError('压缩前后页数不同，已停止生成。')
        page_checks = []
        for index, page in enumerate(final):
            _cancel(cancel_event)
            rect, text, digest = before_pages[index]
            if tuple(page.rect) != rect or page.get_text() != text or _content_digest(final, page) != digest:
                raise CompressionError(f'第 {index + 1} 页的文字或矢量内容校验未通过。')
            check = dict(page=index + 1, text_vector_operators_and_geometry_equal=True)
            if verify_render:
                a, b = original[index].get_pixmap(alpha=False), page.get_pixmap(alpha=False)
                if (a.width, a.height, a.n) != (b.width, b.height, b.n):
                    raise CompressionError(f'第 {index + 1} 页的尺寸校验未通过。')
                ia, ib = Image.frombytes('RGB', (a.width, a.height), a.samples), Image.frombytes('RGB', (b.width, b.height), b.samples)
                difference = sum(ImageStat.Stat(ImageChops.difference(ia, ib)).mean) / 3
                if difference > preset.render_limit:
                    raise CompressionError(f'第 {index + 1} 页画面变化较大，建议使用更高清档位。')
                check['mean_render_delta_255_scale'] = difference
                a = b = ia = ib = None
                fitz.TOOLS.store_shrink(100)
            page_checks.append(check)
            emit(78 + 20 * (index + 1) / count, f'核对页面 {index + 1}/{count}')
        original.close()
        final.close()
        original = final = None
        if _stamp(source) != stamp:
            raise CompressionError('原文件在处理过程中发生变化，请保存后重新压缩。')
        _cancel(cancel_event)
        unchanged_copy = temporary.stat().st_size >= stamp[0]
        if unchanged_copy:
            shutil.copyfile(source, temporary)
        # Destination was reserved by the caller; never overwrite an existing user file.
        if destination.exists():
            raise CompressionError('输出位置出现同名文件，请重新开始。')
        os.rename(temporary, destination)
        after = destination.stat().st_size
        report = dict(source=str(source), output=str(destination), preset=asdict(preset),
                      pages=count, before_bytes=stamp[0], after_bytes=after,
                      reduction_percent=round((1 - after / stamp[0]) * 100, 2),
                      changed_images=len(changed), protected_images=protected,
                      color_conversion=False, source_unchanged=True, checks=page_checks,
                      unchanged_copy=unchanged_copy, seconds=round(time.monotonic() - started, 2))
        emit(100, '原文件已很精简，已保留原画质' if unchanged_copy else '完成，文字与矢量内容核验通过')
        return report
    except (Cancelled, CompressionError):
        raise
    except Exception as exc:
        raise CompressionError(f'无法完成此文件：{exc}') from exc
    finally:
        for opened in (doc, original, final):
            if opened is not None and not opened.is_closed:
                opened.close()
        if temporary.exists():
            temporary.unlink()
        fitz.TOOLS.store_shrink(100)
