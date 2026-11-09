import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest

import pymupdf as fitz
from PIL import Image, ImageCms

from engine import Cancelled, CompressionError, PRESETS, compress_pdf, fresh_path


def make_sample(path):
    gradient = Image.linear_gradient('L').resize((2400, 1600))
    alpha = Image.new('L', gradient.size, 0)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(alpha)
    draw.ellipse((30, 50, 2370, 1550), fill=255)
    color = Image.merge('RGB', (gradient, gradient.transpose(Image.Transpose.FLIP_TOP_BOTTOM), gradient))
    rgba = color.copy()
    rgba.putalpha(alpha)
    stream = BytesIO()
    rgba.save(stream, format='PNG')
    d = fitz.open()
    p = d.new_page()
    p.insert_text((40, 45), 'Product parameters: wingspan 4700 mm; payload 50 kg', fontsize=12)
    p.draw_rect((35, 25, 555, 65), color=(0, .3, .7), width=1.3)
    xref = p.insert_image((70, 100, 310, 260), stream=stream.getvalue())
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    profile = d.get_new_xref()
    d.update_object(profile, '<< /N 3 >>')
    d.update_stream(profile, icc)
    d.xref_set_key(xref, 'ColorSpace', f'[/ICCBased {profile} 0 R]')
    hidden = d.add_ocg('Hidden reference', on=False)
    p.draw_rect((50, 400, 500, 500), color=None, fill=(0, 1, 0), oc=hidden)
    # Shared soft mask across two distinct images: it must not be independently resized.
    other = Image.merge('RGB', (gradient, gradient, gradient))
    other.putalpha(alpha)
    buffer = BytesIO()
    other.save(buffer, format='PNG')
    second = p.insert_image((70, 300, 190, 380), stream=buffer.getvalue())
    smask = d.xref_get_key(xref, 'SMask')[1]
    d.xref_set_key(second, 'SMask', smask)
    small = BytesIO()
    color.resize((2000, 1000)).save(small, format='PNG')
    p.insert_image((350, 100, 550, 200), stream=small.getvalue())
    p = d.new_page()
    p.insert_text((40, 50), 'Vector dimensions: 3250 x 4700 x 680 mm')
    # A CMYK image is retained without any conversion or reinterpretation.
    base = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 180, 120), False)
    base.clear_with(120)
    cm = fitz.Pixmap(fitz.csCMYK, base)
    p.insert_image((60, 90, 240, 210), pixmap=cm)
    d.save(path, deflate=True)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / '中文输入.pdf'
        self.source_hash = make_sample(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def test_presets_preserve_source_text_vectors_color_and_masks(self):
        for key in PRESETS:
            with self.subTest(preset=key):
                target = self.root / f'{key}.pdf'
                report = compress_pdf(self.source, target, key)
                self.assertEqual(report['pages'], 2)
                self.assertFalse(report['color_conversion'])
                self.assertTrue(all(v['text_vector_operators_and_geometry_equal'] for v in report['checks']))
                self.assertLessEqual(target.stat().st_size, self.source.stat().st_size)
                self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)
                with fitz.open(self.source) as a, fitz.open(target) as b:
                    ca = next(r[0] for r in a[1].get_images() if fitz.Pixmap(a, r[0]).colorspace.n == 4)
                    cb = next(r[0] for r in b[1].get_images() if fitz.Pixmap(b, r[0]).colorspace.n == 4)
                    self.assertEqual(a.xref_stream(ca), b.xref_stream(cb))
                    masks = [(r[2:4], r[1]) for r in b[0].get_images() if r[1]]
                    for dimensions, mask in masks:
                        pix = fitz.Pixmap(b, mask)
                        self.assertEqual(dimensions, (pix.width, pix.height))
                    def profiles(d):
                        return sorted(hashlib.sha256(d.xref_stream(i)).hexdigest() for i in range(1, d.xref_length()) if d.xref_get_key(i, 'N') == ('int', '3') and d.xref_is_stream(i))
                    self.assertEqual(profiles(a), profiles(b))
                    self.assertEqual([v['on'] for v in a.get_ocgs().values()], [v['on'] for v in b.get_ocgs().values()])

    def test_cancel_creates_no_partial_output(self):
        event = threading.Event()
        event.set()
        target = self.root / 'cancel.pdf'
        with self.assertRaises(Cancelled):
            compress_pdf(self.source, target, cancel_event=event)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob('*.partial.pdf')))

    def test_no_overwrite_and_name_collision(self):
        with self.assertRaises(CompressionError):
            compress_pdf(self.source, self.source)
        target = self.root / 'existing.pdf'
        target.write_bytes(b'untouched')
        with self.assertRaises(CompressionError):
            compress_pdf(self.source, target)
        self.assertEqual(target.read_bytes(), b'untouched')
        self.assertEqual(fresh_path(self.root, 'existing').name, 'existing_2.pdf')

    def test_encrypted_file_is_not_silently_processed(self):
        encrypted = self.root / 'encrypted.pdf'
        with fitz.open(self.source) as doc:
            doc.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='test-owner', user_pw='test-user')
        with self.assertRaisesRegex(CompressionError, '加密'):
            compress_pdf(encrypted, self.root / 'decrypted.pdf')


if __name__ == '__main__':
    unittest.main(verbosity=2)
