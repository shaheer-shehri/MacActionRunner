"""Generate a 10x15 cm packing-label PDF for a multi-sign order.

One page per sign, showing the company name and its address large and centered,
so each individually-packaged sign in a multi-location order can be labelled with
the location it belongs to. Vector text via reportlab's built-in fonts (no font
files to bundle).
"""
from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
PAGE_MM = (100, 150)          # 10 x 15 cm, portrait
MARGIN_MM = 9


@dataclass
class Label:
    marker: str               # e.g. "E1" — ties the label to its sign file
    company: str
    address: str


def _wrap(text: str, font: str, size: float, max_w: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if not cur or stringWidth(trial, font, size) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit(text: str, font: str, max_w: float, max_h: float,
         max_size: float, min_size: float = 7, leading: float = 1.18):
    """Largest font size (and wrapped lines) that fits text in the box."""
    size = max_size
    while size >= min_size:
        lines = _wrap(text, font, size, max_w)
        if (len(lines) * size * leading <= max_h
                and all(stringWidth(ln, font, size) <= max_w for ln in lines)):
            return size, lines
        size -= 1
    return min_size, _wrap(text, font, min_size, max_w)


def _fit_one_line(text: str, font: str, max_w: float,
                  max_size: float, min_size: float = 5) -> float:
    """Largest font size that renders `text` on a SINGLE line within max_w."""
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_w:
        size -= 0.5
    return size


def _draw_centered(c, lines, font, size, cx, top_y, leading=1.18):
    y = top_y
    for ln in lines:
        c.setFont(font, size)
        c.drawCentredString(cx, y, ln)
        y -= size * leading
    return y


def _draw_label(c, W, H, label: Label, addr_size: float):
    margin = MARGIN_MM * mm
    cw = W - 2 * margin
    cx = W / 2

    # small marker top-left (for matching label -> sign file)
    if label.marker:
        c.setFont(FONT_BOLD, 12)
        c.drawString(margin, H - margin - 12, label.marker)

    # company: bold, upper area
    comp_top = H - margin - 22
    comp_size, comp_lines = _fit(label.company or "", FONT_BOLD, cw, 34 * mm, max_size=30)
    comp_bottom = _draw_centered(c, comp_lines, FONT_BOLD, comp_size, cx, comp_top,
                                 leading=1.15) if comp_lines else comp_top

    # address: ONE line, sized down until it fits the label width (no line breaks),
    # centered in the space left under the company name.
    addr_area_top = comp_bottom - 8 * mm
    addr_area_h = addr_area_top - margin
    addr = " ".join((label.address or "").split())
    if addr:
        c.setFont(FONT, addr_size)
        c.drawCentredString(cx, margin + (addr_area_h - addr_size) / 2, addr)


def build_label_pdf(out_path: str, labels: list[Label]) -> None:
    W, H = PAGE_MM[0] * mm, PAGE_MM[1] * mm
    cw = W - 2 * MARGIN_MM * mm
    # One uniform address size for the whole set: the largest that keeps every
    # address on a single line, so all labels of an order look consistent.
    sizes = [_fit_one_line(" ".join(l.address.split()), FONT, cw, max_size=40)
             for l in labels if l.address]
    addr_size = min(sizes) if sizes else 40

    c = canvas.Canvas(out_path, pagesize=(W, H))
    for lab in labels:
        _draw_label(c, W, H, lab, addr_size)
        c.showPage()
    c.save()
