"""PAdES signature presence check for eSign / DSC verification — Prompts/41 §41.6 (``ESignProvider.verify``).

Full certificate-chain validation needs ``pyhanko`` (installed in production images); without it the check reports
whether the PDF carries a ``/ByteRange`` signature dictionary and its sub-filter."""

import re
from typing import Any


def verify_pades(pdf: bytes) -> dict[str, Any]:
    try:
        import io

        from pyhanko.pdf_utils.reader import PdfFileReader  # type: ignore[import-not-found]
        from pyhanko.sign.validation import validate_pdf_signature  # type: ignore[import-not-found]

        r = PdfFileReader(io.BytesIO(pdf))
        sigs = r.embedded_signatures
        if not sigs:
            return {"signed": False, "valid": False}
        st = validate_pdf_signature(sigs[0])
        return {
            "signed": True,
            "valid": bool(st.intact and st.valid),
            "signer": str(st.signing_cert.subject.human_friendly) if st.signing_cert else None,
        }
    except ImportError:
        signed = b"/ByteRange" in pdf
        sub = re.search(rb"/SubFilter\s*/([A-Za-z0-9.]+)", pdf)
        return {
            "signed": signed,
            "valid": None,
            "sub_filter": sub.group(1).decode() if sub else None,
            "note": "install pyhanko for chain validation",
        }
