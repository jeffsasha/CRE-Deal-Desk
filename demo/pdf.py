"""Minimal PDF writers for generating clearly labeled SAMPLE documents.

text_pdf(): a PDF with a real text layer (Helvetica), like a digitally generated contract.
scanned_pdf(): an image-only PDF (no text layer), like a scanned paper contract; only
OCR can read it.
"""
import io
import textwrap

PAGE_W, PAGE_H = 612, 792


def _esc(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(paragraphs, width=92):
    lines = []
    for p in paragraphs:
        if p == "":
            lines.append("")
            continue
        lines.extend(textwrap.wrap(p, width) or [""])
    return lines


def text_pdf(pages):
    """pages: list of lists of paragraphs. Returns PDF bytes."""
    objects = []

    def add(obj):
        objects.append(obj)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    pages_id_placeholder = len(objects) + 1
    add(b"")  # pages object filled later
    page_ids = []
    for paragraphs in pages:
        lines = _wrap(paragraphs)
        ops = ["BT", "/F1 10 Tf", "13 TL", f"54 {PAGE_H - 60} Td"]
        for line in lines:
            ops.append(f"({_esc(line)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("cp1252", errors="replace")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(add(
            f"<< /Type /Page /Parent {pages_id_placeholder} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Contents {content} 0 R /Resources << /Font << /F1 {font} 0 R >> >> >>".encode()))
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects[pages_id_placeholder - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    catalog = add(f"<< /Type /Catalog /Pages {pages_id_placeholder} 0 R >>".encode())
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def scanned_pdf(pages):
    """Render pages to images (no text layer) and save as a multi-page PDF."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    font = None
    for path in ["/System/Library/Fonts/Supplemental/Times New Roman.ttf", "/Library/Fonts/Times New Roman.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]:
        try:
            font = ImageFont.truetype(path, 30)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    images = []
    for paragraphs in pages:
        img = Image.new("L", (1700, 2200), 250)
        d = ImageDraw.Draw(img)
        y = 120
        for line in _wrap(paragraphs, width=88):
            d.text((130, y), line, font=font, fill=25)
            y += 42
        img = img.rotate(0.4, fillcolor=250).filter(ImageFilter.GaussianBlur(0.6))
        images.append(img.convert("RGB"))
    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:], resolution=200)
    return buf.getvalue()
