"""Generate a QR code and composite it onto the template.

Produces the two rasters the PDF exporter needs:
  * ``rgb``   – RGB artwork (template colours flattened, with QR painted in)
  * ``white`` – 8-bit Spot-White mask (template alpha, plus white behind the QR
                on non-white materials so the black modules stay opaque on
                transparent/black substrates)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass
class QRBox:
    """QR placement as fractions of the template, so one value works for every
    colour/language/size of a shape (A6 is A5 scaled). Measured from the empty
    QR window in the blank templates.
        fx, fy   -> top-left, fractions of width / height
        fsize    -> square side, fraction of WIDTH
    """
    fx: float
    fy: float
    fsize: float
    quiet_modules: int = 4

    def pixels(self, W: int, H: int) -> tuple[int, int, int]:
        return round(self.fx * W), round(self.fy * H), round(self.fsize * W)


def make_qr(link: str, box: QRBox, size_px: int) -> Image.Image:
    """Black-on-white QR sized to ``size_px`` px square."""
    import qrcode
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=box.quiet_modules,
        box_size=10,
    )
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size_px, size_px), Image.NEAREST)


def compose(template_png: str, link: str, box: QRBox,
            white_behind_qr: bool = True,
            white_bleed_px: int = 5,
            background=(255, 255, 255)) -> tuple[Image.Image, Image.Image]:
    tpl = Image.open(template_png).convert("RGBA")
    W, H = tpl.size
    arr = np.asarray(tpl).astype(np.uint8)
    rgb = arr[:, :, :3].copy()
    alpha = arr[:, :, 3].copy()

    # Flatten template RGB over the chosen background using its own alpha.
    a = alpha.astype(float)[:, :, None] / 255.0
    bg = np.array(background, dtype=float)
    flat = (rgb.astype(float) * a + bg * (1 - a)).astype(np.uint8)

    x, y, s = box.pixels(W, H)
    qr = np.asarray(make_qr(link, box, s))  # (s, s, 3)
    if x + s > W or y + s > H:
        raise ValueError(f"QR box {box} -> ({x},{y},{s}) exceeds template {W}x{H}")

    flat[y:y + s, x:x + s] = qr
    if white_behind_qr:
        # Paint the QR footprint into the white channel so black modules read on
        # transparent/black materials. Spread (choke/trap) by white_bleed_px so
        # the fill overlaps the template frame's own white and leaves no hairline
        # un-inked ring at the anti-aliased window edge.
        b = white_bleed_px
        y0, y1 = max(0, y - b), min(H, y + s + b)
        x0, x1 = max(0, x - b), min(W, x + s + b)
        alpha[y0:y1, x0:x1] = 255

    return Image.fromarray(flat, "RGB"), Image.fromarray(alpha, "L")
