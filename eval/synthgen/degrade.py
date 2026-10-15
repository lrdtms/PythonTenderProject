"""Turn a native PDF into an image-only 'scanned' PDF (no text layer)."""

from __future__ import annotations

import random
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageEnhance, ImageFilter


def scan_pdf(src: Path, dst: Path, rng: random.Random, dpi: int = 150) -> None:
    source = pymupdf.open(src)
    out = pymupdf.open()
    for page in source:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        img = img.rotate(rng.uniform(-1.0, 1.0), resample=Image.BICUBIC, fillcolor=255)
        img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.4, 0.9)))
        noise = Image.effect_noise(img.size, 18)
        img = Image.blend(img, noise, 0.07)
        img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 0.95))
        buf = BytesIO()
        img.save(buf, "JPEG", quality=rng.randint(45, 70))
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=buf.getvalue())
    out.save(dst)
    out.close()
    source.close()
