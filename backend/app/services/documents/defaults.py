"""Platform default templates (Prompts/26 §26.2) and the block-layout → HTML compiler of the template builder.

``compile_layout(layout)`` turns builder blocks into a Jinja HTML document: ``header`` (logo + institution),
``title``, ``paragraph`` (text with ``{{ variables }}``), ``table`` (``props.rows``: ``[[label, "{{ var }}"], …]``),
``photo``, ``qr``, ``barcode``, ``signatures`` (``props.roles``), ``seal``, ``footer``, ``watermark`` and
``secondary`` (bilingual block rendered below in the secondary script). Every default is one ``layout`` per type;
the seeded ``html_template`` is that layout compiled, so raw-HTML editing starts from the same markup.
"""

import html as _html
from typing import Any

from app.enums.documents import (
    BILINGUAL_TYPES,
    COMMON_VARIABLES,
    STAFF_TYPES,
    STAFF_VARIABLES,
    STUDENT_VARIABLES,
    TEMPLATE_TYPES,
    TYPE_VARIABLES,
)

BASE_CSS = (
    "@page{size:A4;margin:18mm}body{font-family:'Noto Sans','Noto Sans Devanagari','Noto Sans Tamil',"
    "'Noto Sans Telugu',sans-serif;font-size:11pt;color:#111}"
    ".hdr{text-align:center;border-bottom:2px solid #333;padding-bottom:6px;margin-bottom:14px}"
    ".hdr img{height:56px}.hdr h1{font-size:16pt;margin:4px 0}.title{text-align:center;font-size:15pt;"
    "font-weight:bold;text-decoration:underline;margin:18px 0}.meta{display:flex;justify-content:space-between;"
    "font-size:9pt}p{line-height:1.7;text-align:justify}table.kv{border-collapse:collapse;width:100%}"
    "table.kv td{border:1px solid #999;padding:4px 6px}.sigs{display:flex;justify-content:space-between;"
    "margin-top:48px}.sig{text-align:center;font-size:9pt}.sig img{height:36px}.qr img{width:28mm}"
    ".photo img{width:30mm;height:36mm;object-fit:cover}.footer{position:fixed;bottom:0;font-size:8pt;color:#555}"
    ".wm{position:fixed;top:42%;left:8%;font-size:52pt;color:rgba(160,160,160,.22);transform:rotate(-30deg)}"
    ".secondary{margin-top:18px;border-top:1px dashed #999;padding-top:10px}"
)
CARD_CSS = (
    "@page{size:85.6mm 54mm;margin:0}body{font:7pt sans-serif;margin:0}.card{padding:3mm}"
    ".hdr{text-align:center;font-weight:bold;font-size:8pt}.photo img{width:18mm;height:22mm;float:left;margin-right:2mm}"
    ".qr img{width:16mm;float:right}.wm{display:none}"
)

TITLES: dict[str, str] = {
    "id_card": "Identity Card",
    "bonafide": "Bonafide Certificate",
    "character": "Character Certificate",
    "conduct": "Conduct Certificate",
    "noc": "No Objection Certificate",
    "tc": "Transfer Certificate",
    "migration": "Migration Certificate",
    "course_completion": "Course Completion Certificate",
    "provisional": "Provisional Certificate",
    "degree": "Degree Certificate",
    "grade_card": "Grade Card",
    "transcript": "Transcript of Academic Record",
    "hall_ticket": "Hall Ticket",
    "receipt": "Receipt",
    "experience": "Experience Certificate",
    "service": "Service Certificate",
    "internship_noc": "No Objection Certificate for Internship",
    "hostel_allotment": "Hostel Allotment Letter",
    "event_certificate": "Certificate of Participation",
    "undertaking": "Undertaking",
    "medical_certificate": "Medical Certificate",
    "fee_structure_letter": "Fee Structure Letter",
    "offer_letter": "Offer Letter",
    "donation_receipt_80g": "Donation Receipt (Section 80G)",
    "alumni_membership_card": "Alumni Membership Card",
    "phd_registration_letter": "PhD Registration Letter",
    "phd_synopsis_ack": "Acknowledgement of Synopsis Submission",
    "phd_provisional_certificate": "Provisional Certificate (Doctor of Philosophy)",
    "examiner_invitation": "Invitation to Examine a PhD Thesis",
    "custom": "Certificate",
}

_S = "{{ student.name }} (Reg. No. {{ student.registration_number }})"
BODIES: dict[str, str] = {
    "bonafide": f"This is to certify that {_S}, son/daughter of {{{{ student.guardian_name }}}}, is a bonafide "
    "student of this institution studying {{ enrolment.program }} ({{ enrolment.batch }}) during the academic year "
    "{{ enrolment.academic_year }}. This certificate is issued for the purpose of {{ purpose }}.",
    "character": f"This is to certify that {_S} was a student of {{{{ enrolment.program }}}} at this institution. "
    "To the best of our knowledge he/she bears a good moral character.",
    "conduct": f"This is to certify that the conduct of {_S} during the period of study in "
    "{{ enrolment.program }} has been good.",
    "noc": "This is to certify that the institution has no objection to {{ staff.name }} ({{ staff.designation }}, "
    "{{ staff.department }}) for the purpose of {{ purpose }}.",
    "tc": f"Certified that {_S}, admitted on {{{{ enrolment.admission_date }}}} to {{{{ enrolment.program }}}}, has "
    "left the institution. Status: {{ enrolment.status }}. Conduct: good. No dues are outstanding.",
    "migration": f"Certified that the university has no objection to {_S} migrating to another university. "
    "Programme: {{ enrolment.program }}.",
    "course_completion": f"This is to certify that {_S} has successfully completed {{{{ enrolment.program }}}} "
    "with a CGPA of {{ enrolment.cgpa }}.",
    "provisional": f"This is to certify that {_S} has passed {{{{ enrolment.program }}}} with a CGPA of "
    "{{ enrolment.cgpa }}. The degree will be conferred at the next convocation.",
    "degree": "{{ student.name }} having fulfilled the requirements is hereby conferred the degree of "
    "{{ award.degree }} with {{ award.class }} on {{ award.date }}.",
    "grade_card": f"Statement of grades for {_S}, {{{{ enrolment.program }}}}. SGPA {{{{ term.sgpa }}}}, "
    "CGPA {{ enrolment.cgpa }}.",
    "transcript": f"Academic record of {_S}, {{{{ enrolment.program }}}}. Credits earned "
    "{{ enrolment.credits_earned }}, CGPA {{ enrolment.cgpa }}.",
    "hall_ticket": f"Admit {_S} of {{{{ enrolment.program }}}} to the examinations listed.",
    "receipt": "Received from {{ student.name }} the sum stated towards {{ purpose }}.",
    "experience": "This is to certify that {{ staff.name }} (Emp. {{ staff.employee_id }}) worked as "
    "{{ staff.designation }} in the department of {{ staff.department }} from {{ staff.joining_date }} to "
    "{{ staff.exit_date }}. We wish him/her success.",
    "service": "This is to certify that {{ staff.name }} (Emp. {{ staff.employee_id }}) is serving as "
    "{{ staff.designation }} in {{ staff.department }} since {{ staff.joining_date }}.",
    "internship_noc": f"The institution has no objection to {_S} of {{{{ enrolment.program }}}} undertaking an "
    "internship for {{ purpose }}.",
    "hostel_allotment": f"{_S} is allotted {{{{ hostel.room }}}} in {{{{ hostel.name }}}}.",
    "event_certificate": "This is to certify that {{ participant.name }} participated in {{ event.title }} "
    "({{ event.type }}) held from {{ event.from_on }} to {{ event.to_on }}.",
    "undertaking": "I, {{ student.name }}, undertake to abide by the rules of {{ institution.name }}.",
    "medical_certificate": "This is to certify that {{ student.name }} was examined at the health centre "
    "for {{ purpose }}.",
    "fee_structure_letter": f"The fee structure applicable to {_S}, {{{{ enrolment.program }}}}, for the academic "
    "year {{ enrolment.academic_year }} is issued for {{ purpose }}.",
    "offer_letter": "We are pleased to offer {{ student.name }} admission to {{ enrolment.program }}.",
    "donation_receipt_80g": "Received with thanks from {{ donor.name }}{% if donor.pan %} (PAN {{ donor.pan }}){% endif %} "
    "the sum of Rs. {{ donation.amount }} ({{ donation.amount_words }}) by {{ donation.mode }}{% if donation.reference %} "
    "(ref. {{ donation.reference }}){% endif %} on {{ donation.on_date }} towards {{ donation.campaign }}. Receipt No. "
    "{{ donation.receipt_no }}. Donations to {{ institution.name }} qualify for deduction under section 80G of the "
    "Income-tax Act, 1961 vide registration {{ g80.registration_no }} valid from {{ g80.valid_from }} to "
    "{{ g80.valid_to }}.",
    "alumni_membership_card": "{{ alumni.name }}<br>{{ alumni.program }} · {{ alumni.batch }}<br>Member No. "
    "{{ alumni.member_no }}",
    "phd_registration_letter": f"This is to certify that {_S} is registered for the Doctor of Philosophy programme "
    "({{ scholar.mode }}) in {{ enrolment.department }} with effect from {{ scholar.registration_date }} under the guidance "
    "of {{ scholar.guide }}{% if scholar.co_guide %} and {{ scholar.co_guide }}{% endif %}. Area of research: "
    "{{ scholar.research_area }}. The thesis is to be submitted on or before {{ scholar.max_duration_end }}.",
    "phd_synopsis_ack": f"Received the synopsis “{{{{ thesis.title }}}}” of {_S}, research scholar in "
    "{{ enrolment.department }}, on {{ thesis.submitted_on }}. Similarity index: {{ thesis.similarity }} %.",
    "phd_provisional_certificate": f"This is to certify that {_S} has been found qualified for the award of the "
    "degree of Doctor of Philosophy in {{ enrolment.department }} for the thesis entitled “{{ thesis.title }}” under "
    "the guidance of {{ scholar.guide }}. The degree will be conferred at the next convocation. Date of award: "
    "{{ award.date }}.",
    "examiner_invitation": "Dear {{ examiner.name }} ({{ examiner.affiliation }}), you are invited to evaluate the PhD "
    "thesis entitled “{{ thesis.title }}” submitted in {{ enrolment.department }}. Kindly respond within "
    "{{ examiner.due_days }} days using the link sent by email.",
    "custom": "{{ body }}",
    "id_card": "{{ student.name }}<br>{{ student.registration_number }}<br>{{ enrolment.program }}",
}
SECONDARY_HI: dict[str, str] = {
    "donation_receipt_80g": "{{ donor.name }} से रु. {{ donation.amount }} का दान धन्यवाद सहित प्राप्त हुआ। यह दान आयकर "
    "अधिनियम की धारा 80G के अंतर्गत कटौती योग्य है (पंजीकरण {{ g80.registration_no }})।",
    "bonafide": "प्रमाणित किया जाता है कि {{ student.name_secondary }} (पंजीकरण सं. {{ student.registration_number }}) "
    "इस संस्थान के {{ enrolment.program }} के वास्तविक छात्र/छात्रा हैं।",
    "degree": "{{ student.name_secondary }} को {{ award.degree }} की उपाधि प्रदान की जाती है।",
    "provisional": "प्रमाणित किया जाता है कि {{ student.name_secondary }} ने {{ enrolment.program }} उत्तीर्ण किया है।",
    "tc": "प्रमाणित किया जाता है कि {{ student.name_secondary }} ने संस्थान छोड़ दिया है।",
}
SIGNERS: dict[str, list[str]] = {
    "degree": ["registrar", "principal"],
    "provisional": ["coe", "registrar"],
    "grade_card": ["coe"],
    "transcript": ["coe", "registrar"],
    "hall_ticket": ["coe"],
    "experience": ["principal"],
    "service": ["principal"],
    "noc": ["principal"],
    "donation_receipt_80g": ["principal"],
    "alumni_membership_card": ["registrar"],
    "phd_registration_letter": ["registrar"],
    "phd_synopsis_ack": ["registrar"],
    "phd_provisional_certificate": ["coe", "registrar"],
    "examiner_invitation": ["coe"],
}


def variables_for(template_type: str) -> list[dict[str, str]]:
    person = STAFF_VARIABLES if template_type in STAFF_TYPES else STUDENT_VARIABLES
    return [*COMMON_VARIABLES, *person, *TYPE_VARIABLES.get(template_type, [])]


def default_layout(template_type: str, *, bilingual: bool = False) -> dict[str, Any]:
    if template_type == "alumni_membership_card":
        return {
            "variant": "alumni",
            "blocks": [
                {"type": "header", "props": {"logo": True}},
                {"type": "paragraph", "text": BODIES["alumni_membership_card"]},
                {"type": "qr", "props": {}},
            ],
        }
    if template_type == "id_card":
        return {
            "variant": "student",
            "blocks": [
                {"type": "header", "props": {"logo": True}},
                {"type": "photo", "props": {}},
                {"type": "paragraph", "text": BODIES["id_card"]},
                {"type": "qr", "props": {}},
            ],
        }
    blocks: list[dict[str, Any]] = [
        {"type": "header", "props": {"logo": True}},
        {"type": "meta", "props": {}},
        {"type": "title", "text": TITLES.get(template_type, "Certificate")},
        {"type": "paragraph", "text": BODIES.get(template_type, BODIES["custom"])},
    ]
    if bilingual and template_type in SECONDARY_HI:
        blocks.append({"type": "secondary", "text": SECONDARY_HI[template_type], "props": {"language": "hi"}})
    blocks += [
        {"type": "qr", "props": {}},
        {"type": "signatures", "props": {"roles": SIGNERS.get(template_type, ["registrar"])}},
        {"type": "seal", "props": {}},
        {"type": "footer", "text": "Verify at {{ document.verify_url }}"},
        {"type": "watermark", "props": {}},
    ]
    return {"blocks": blocks}


def _block_html(b: dict[str, Any]) -> str:
    t, text, props = b.get("type"), b.get("text") or "", b.get("props") or {}
    if t == "header":
        logo = (
            '{% if institution.logo_url %}<img src="{{ institution.logo_url }}">{% endif %}'
            if props.get("logo")
            else ""
        )
        return (
            f'<div class="hdr">{logo}<h1>{{{{ institution.name }}}}</h1><div>{{{{ institution.address }}}}</div></div>'
        )
    if t == "meta":
        return (
            '<div class="meta"><span>No. {{ document.number }}{% if document.serial_no %} · Serial '
            "{{ document.serial_no }}{% endif %}</span><span>Date: {{ document.issued_on }}</span></div>"
        )
    if t == "title":
        return f'<div class="title">{text}</div>'
    if t == "paragraph":
        return f"<p>{text}</p>"
    if t == "secondary":
        return f'<div class="secondary" lang="{_html.escape(str(props.get("language") or "hi"))}"><p>{text}</p></div>'
    if t == "table":
        rows = "".join(f"<tr><td>{r[0]}</td><td>{r[1]}</td></tr>" for r in props.get("rows") or [] if len(r) >= 2)
        return f'<table class="kv">{rows}</table>'
    if t == "photo":
        return '<div class="photo">{% if photo %}<img src="{{ photo }}">{% endif %}</div>'
    if t in ("qr", "barcode"):
        return '<div class="qr">{% if document.qr %}<img src="{{ document.qr }}">{% endif %}</div>'
    if t == "signatures":
        sigs = "".join(
            f'<div class="sig">{{% if signatories.{r}.signature_url %}}<img src="{{{{ signatories.{r}.signature_url }}}}">'
            f"{{% endif %}}<div>{{{{ signatories.{r}.name }}}}</div><div>{{{{ signatories.{r}.designation }}}}</div></div>"
            for r in (props.get("roles") or ["registrar"])
        )
        return f'<div class="sigs">{sigs}</div>'
    if t == "seal":
        return '{% if institution.seal_url %}<div class="seal"><img src="{{ institution.seal_url }}"></div>{% endif %}'
    if t == "footer":
        return f'<div class="footer">{text}</div>'
    if t == "watermark":
        return '{% if watermark %}<div class="wm">{{ watermark }}</div>{% endif %}'
    return f"<div>{text}</div>"


BLOCK_TYPES: tuple[str, ...] = (
    "header",
    "meta",
    "title",
    "paragraph",
    "table",
    "photo",
    "qr",
    "barcode",
    "signatures",
    "seal",
    "footer",
    "watermark",
    "secondary",
)


def compile_layout(layout: dict[str, Any] | None) -> str:
    blocks = (layout or {}).get("blocks") or []
    body = "\n".join(_block_html(b) for b in blocks if isinstance(b, dict))
    wrap = f'<div class="card">{body}</div>' if (layout or {}).get("variant") else body
    if not any(isinstance(b, dict) and b.get("type") == "watermark" for b in blocks):
        wrap += _block_html({"type": "watermark"})
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{{{{ css }}}}</style></head><body>{wrap}</body></html>'


def default_template(template_type: str, *, bilingual: bool = False) -> dict[str, Any]:
    layout = default_layout(template_type, bilingual=bilingual)
    card = template_type in ("id_card", "alumni_membership_card")
    return {
        "template_type": template_type,
        "name": f"{TITLES.get(template_type, template_type)}{' (bilingual)' if bilingual else ''}"[:120],
        "layout": layout,
        "html_template": compile_layout(layout),
        "css": CARD_CSS if card else BASE_CSS,
        "page_size": "ID_CR80" if card else "A4",
        "is_bilingual": bilingual,
        "secondary_language": "hi" if bilingual else None,
        "variables": variables_for(template_type),
    }


def platform_defaults() -> list[dict[str, Any]]:
    """Every template type once, plus the IN-pack bilingual variants and staff / scholar ID cards."""
    out = [default_template(t) for t in TEMPLATE_TYPES]
    out += [{**default_template(t, bilingual=True), "pack": "IN"} for t in BILINGUAL_TYPES]
    for variant in ("staff", "scholar"):
        d = default_template("id_card")
        d["layout"] = {**d["layout"], "variant": variant}
        d["name"] = f"{variant.title()} ID card (CR80)"
        out.append(d)
    return out
