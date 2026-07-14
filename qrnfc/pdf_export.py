"""Assemble a print-ready PDF with a `Spot_Weiss` separation (overprint on).

Structure mirrors the client's finished samples:
  * one full-page RGB artwork image (DCTDecode)
  * one full-page image in a /Separation `Spot_Weiss` colour space (Flate),
    drawn with an overprint ExtGState.

NOTE: the alternate colour space + tint transform below only affect on-screen
preview; the RIP keys off the separation *name* + overprint. The definitive
check is running an output through the client's RIP (open question #7).
"""
from __future__ import annotations

import io
import zlib

import pikepdf
from PIL import Image
from pikepdf import Array, Dictionary, Name

# points-per-mm
MM = 72.0 / 25.4


def _rgb_xobject(pdf: pikepdf.Pdf, img: Image.Image) -> pikepdf.Object:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=92)
    st = pikepdf.Stream(pdf, buf.getvalue())
    st.stream_dict = Dictionary(
        Type=Name.XObject, Subtype=Name.Image,
        Width=img.width, Height=img.height,
        ColorSpace=Name.DeviceRGB, BitsPerComponent=8,
        Filter=Name.DCTDecode,
    )
    return pdf.make_indirect(st)


def _spot_colorspace(pdf: pikepdf.Pdf, spot_name: str) -> pikepdf.Object:
    # tint transform: exponential, tint(1)-> no CMYK ink (paper white preview)
    tint = pdf.make_indirect(Dictionary(
        FunctionType=2, Domain=[0, 1], C0=[0, 0, 0, 0], C1=[0, 0, 0, 0], N=1,
    ))
    return pdf.make_indirect(Array([
        Name.Separation, Name("/" + spot_name), Name.DeviceCMYK, tint,
    ]))


def _spot_xobject(pdf: pikepdf.Pdf, mask: Image.Image, cs: pikepdf.Object) -> pikepdf.Object:
    raw = mask.convert("L").tobytes()
    st = pikepdf.Stream(pdf, zlib.compress(raw, 9))
    st.stream_dict = Dictionary(
        Type=Name.XObject, Subtype=Name.Image,
        Width=mask.width, Height=mask.height,
        ColorSpace=cs, BitsPerComponent=8,
        Filter=Name.FlateDecode,
    )
    return pdf.make_indirect(st)


def build_pdf(out_path: str, rgb: Image.Image, white: Image.Image,
              page_w_pt: float, page_h_pt: float,
              spot_name: str = "Spot_Weiss") -> None:
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(page_w_pt, page_h_pt))

    art = _rgb_xobject(pdf, rgb)
    cs = _spot_colorspace(pdf, spot_name)
    spot = _spot_xobject(pdf, white, cs)

    gs = pdf.make_indirect(Dictionary(
        Type=Name.ExtGState, OP=True, op=True, OPM=1,
    ))

    page.Resources = Dictionary(
        XObject=Dictionary(Art=art, White=spot),
        ExtGState=Dictionary(GsOP=gs),
    )
    w, h = page_w_pt, page_h_pt
    content = (
        f"q {w:.3f} 0 0 {h:.3f} 0 0 cm /Art Do Q\n"
        f"/GsOP gs\n"
        f"q {w:.3f} 0 0 {h:.3f} 0 0 cm /White Do Q\n"
    ).encode("latin1")
    page.Contents = pdf.make_stream(content)

    pdf.save(out_path)
    pdf.close()
