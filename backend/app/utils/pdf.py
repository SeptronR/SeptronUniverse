"""PDF rendering — WeasyPrint when its native libraries load (containers: Pango/Cairo in the image), otherwise a
dependency-free single-font PDF writer so payslips still render on a workstation without GTK (Windows dev boxes).

``render_pdf(html, lines)``: ``html`` for WeasyPrint, ``lines`` (plain text rows) for the fallback. Both paths return
``%PDF-`` bytes; the fallback lays the lines out on A4 pages in Helvetica.
"""

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _weasy() -> Any:
    try:
        import weasyprint

        weasyprint.HTML(string="<p></p>").write_pdf()
        return weasyprint
    except Exception:  # noqa: BLE001 - OSError (missing libpango) or any import-time failure → fallback writer
        return None


def render_pdf(html: str, lines: list[str], title: str = "Document") -> bytes:
    wp = _weasy()
    if wp is not None:
        try:
            return bytes(wp.HTML(string=html).write_pdf())
        except Exception:  # noqa: BLE001 - fall back to the plain writer
            pass
    return simple_pdf(lines, title)


def _esc(text: str) -> str:
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def simple_pdf(lines: list[str], title: str = "Document") -> bytes:
    """Minimal PDF 1.4: Helvetica 10 pt, 60 lines per A4 page, a bold title on the first page."""
    per_page = 60
    pages = [lines[i : i + per_page] for i in range(0, max(len(lines), 1), per_page)] or [[]]
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_id = len(objects) + 1 + 2 * len(pages)  # reserved after the page/content pairs
    page_ids: list[int] = []
    for n, chunk in enumerate(pages):
        ops = ["BT"]
        y = 800
        if n == 0:
            ops.append(f"/F2 14 Tf 50 {y} Td ({_esc(title)}) Tj")
            y -= 26
            ops.append(f"0 {-26} Td /F1 10 Tf")
        else:
            ops.append(f"/F1 10 Tf 50 {y} Td")
        for line in chunk:
            ops.append(f"({_esc(line)}) Tj 0 -12 Td")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        page = add(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] /Contents {content} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R /F2 {bold} 0 R >> >> >>".encode()
        )
        page_ids.append(page)
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


# ---- ID cards (Phase 07) ----------------------------------------------------------------------------------------------
CARD_W, CARD_H = 243, 153  # CR80 (85.6 × 54 mm) in points


def qr_matrix(data: str) -> list[list[bool]]:
    """QR modules (``True`` = dark) with a one-module quiet zone — drawn as vector squares, so no image library or
    native renderer is needed."""
    import qrcode

    qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    return [list(row) for row in qr.get_matrix()]


def id_card_pdf(cards: list[dict[str, str]]) -> bytes:
    """One CR80 page per card: header band (institution / college), name, registration number, programme, batch,
    blood group, validity and the verification QR on the right. ``cards``: dicts with ``institution``, ``college``,
    ``name``, ``registration_number``, ``program``, ``batch``, ``blood_group``, ``valid_until``, ``emergency``,
    ``verify_url``."""
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_id = len(objects) + 1 + 2 * max(len(cards), 1)
    page_ids: list[int] = []
    for card in cards or [{}]:
        ops = [
            "0.12 0.11 0.29 rg 0 123 243 30 re f",  # header band
            "1 1 1 rg BT /F2 9 Tf 8 140 Td",
            f"({_esc(card.get('institution', '')[:44])}) Tj ET",
            f"BT /F1 6.5 Tf 8 129 Td ({_esc(card.get('college', '')[:56])}) Tj ET",
            "0 0 0 rg",
            "0.85 0.85 0.85 RG 8 62 44 54 re S",  # photo frame
            "BT /F1 5 Tf 15 86 Td (PHOTO) Tj ET",
            f"BT /F2 9 Tf 58 106 Td ({_esc(card.get('name', '')[:30])}) Tj ET",
        ]
        y = 95
        for label, key in (
            ("Reg. no", "registration_number"),
            ("Programme", "program"),
            ("Batch", "batch"),
            ("Blood group", "blood_group"),
            ("Emergency", "emergency"),
            ("Valid until", "valid_until"),
        ):
            value = card.get(key) or "-"
            ops.append(f"BT /F2 6 Tf 58 {y} Td ({_esc(label)}) Tj /F1 6 Tf 42 0 Td ({_esc(str(value)[:30])}) Tj ET")
            y -= 9
        matrix = qr_matrix(card.get("verify_url", "") or "-")
        size = 66.0
        cell = size / len(matrix)
        ox, oy = CARD_W - size - 8, 8.0
        ops.append("0 0 0 rg")
        for r, row in enumerate(matrix):
            for c, dark in enumerate(row):
                if dark:
                    ops.append(f"{ox + c * cell:.2f} {oy + size - (r + 1) * cell:.2f} {cell:.2f} {cell:.2f} re")
        ops.append("f")
        ops.append(f"BT /F1 5 Tf {ox:.1f} {oy + size + 3:.1f} Td (Scan to verify) Tj ET")
        ops.append("BT /F1 5 Tf 8 8 Td (If found, please return to the institution office.) Tj ET")
        stream = "\n".join(ops).encode("latin-1", "replace")
        content = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        page = add(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {CARD_W} {CARD_H}] /Contents {content} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R /F2 {bold} 0 R >> >> >>".encode()
        )
        page_ids.append(page)
    kids = " ".join(f"{p} 0 R" for p in page_ids)
    add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
