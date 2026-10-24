"""Minimal DOCX writer (WordprocessingML in a zip) — headings, paragraphs and simple tables.

Used where ``python-docx`` is not installed (NBA SAR export, Phase 17). Output opens in Word / LibreOffice / Google
Docs; no styles beyond bold headings and table borders.
"""

import io
import zipfile
from typing import Any
from xml.sax.saxutils import escape

_CT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)
_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _run(text: str, bold: bool = False, size: int | None = None) -> str:
    props = ""
    if bold or size:
        props = "<w:rPr>" + ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size}"/>' if size else "") + "</w:rPr>"
    return f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


class DocxLite:
    def __init__(self) -> None:
        self.body: list[str] = []

    def heading(self, text: str, level: int = 1) -> None:
        self.body.append(f"<w:p>{_run(text, bold=True, size=36 - level * 4)}</w:p>")

    def paragraph(self, text: str, bold: bool = False) -> None:
        self.body.append(f"<w:p>{_run(text, bold=bold)}</w:p>")

    def table(self, header: list[str], rows: list[list[Any]]) -> None:
        border = "".join(
            f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
            for s in ("top", "left", "bottom", "right", "insideH", "insideV")
        )
        out = [f"<w:tbl><w:tblPr><w:tblBorders>{border}</w:tblBorders></w:tblPr>"]
        for i, row in enumerate([header, *rows]):
            cells = "".join(f"<w:tc><w:p>{_run('' if v is None else str(v), bold=i == 0)}</w:p></w:tc>" for v in row)
            out.append(f"<w:tr>{cells}</w:tr>")
        out.append("</w:tbl>")
        self.body.append("".join(out))
        self.body.append("<w:p/>")

    def to_bytes(self) -> bytes:
        doc = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_NS}><w:body>'
            + "".join(self.body)
            + "</w:body></w:document>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", _CT)
            z.writestr("_rels/.rels", _RELS)
            z.writestr("word/document.xml", doc)
        return buf.getvalue()
