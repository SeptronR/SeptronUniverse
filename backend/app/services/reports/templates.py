"""Platform report print layouts — Prompts/36 §36.2 (``0036`` data): ``document_templates`` rows (``institution_id``
NULL) for ``report_portrait`` / ``report_landscape`` / ``register_ledger`` / ``statutory_cover`` with letterhead and
watermark placeholders. The renderer (``render_service.render_pdf``) applies the same layouts; institutions may copy a
row and restyle it in the Phase 26 template designer."""

from typing import Any

_LETTERHEAD = (
    "<header class='lh'>{% if institution.logo_url %}<img src='{{ institution.logo_url }}' class='logo'/>{% endif %}"
    "<div class='name'>{{ institution.name }}</div><div class='addr'>{{ institution.address }}</div></header>"
)
_FOOTER = "<footer>{{ generated_by }} · {{ generated_on }} · Page <span class='page'></span></footer>"
_WATERMARK = "{% if draft %}<div class='wm'>DRAFT</div>{% endif %}"
_TABLE = (
    "<h1>{{ title }}</h1><div class='meta'>{{ scope }}</div><table><thead><tr>{% for c in columns %}<th>{{ c.label }}</th>"
    "{% endfor %}</tr></thead><tbody>{% for r in rows %}<tr>{% for c in columns %}<td>{{ r[c.key] }}</td>{% endfor %}</tr>"
    "{% endfor %}</tbody></table>"
)
_CSS = (
    "body{font-family:sans-serif;font-size:8.5pt} .lh{border-bottom:2px solid #1F4E79} .logo{height:36px;float:right}"
    " th{background:#1F4E79;color:#fff} td,th{border:1px solid #999;padding:2px 4px} table{border-collapse:collapse;width:100%}"
    " .wm{position:fixed;top:40%;left:20%;font-size:90pt;color:rgba(200,0,0,.12);transform:rotate(-30deg)}"
)

REPORT_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "template_type": "report_portrait",
        "name": "Report — portrait",
        "page_size": "A4",
        "orientation": "portrait",
        "body": _TABLE,
    },
    {
        "template_type": "report_landscape",
        "name": "Report — landscape",
        "page_size": "A4",
        "orientation": "landscape",
        "body": _TABLE,
    },
    {
        "template_type": "register_ledger",
        "name": "Register — ledger (page-wise totals)",
        "page_size": "A4",
        "orientation": "landscape",
        "body": _TABLE + "{% if page_totals %}<div class='tot'>Page total: {{ page_totals }}</div>{% endif %}",
    },
    {
        "template_type": "statutory_cover",
        "name": "Statutory report — cover and sign-off",
        "page_size": "A4",
        "orientation": "portrait",
        "body": "<h1>{{ title }}</h1><div>{{ period_label }} · version {{ version }}</div><table><tr><th>Role</th><th>Signed by</th>"
        "<th>On</th></tr>{% for s in signoffs %}<tr><td>{{ s.role }}</td><td>{{ s.user_name }}</td><td>{{ s.at }}</td></tr>"
        "{% endfor %}</table>",
    },
)


def template_rows() -> list[dict[str, Any]]:
    return [
        {
            "template_type": t["template_type"],
            "name": t["name"],
            "layout": {
                "orientation": t["orientation"],
                "blocks": ["letterhead", "body", "footer"],
                "watermark": "draft",
            },
            "html_template": _WATERMARK + _LETTERHEAD + t["body"] + _FOOTER,
            "css": _CSS + ("@page{size:A4 landscape}" if t["orientation"] == "landscape" else "@page{size:A4}"),
            "page_size": t["page_size"],
            "variables": ["institution", "title", "scope", "columns", "rows", "generated_by", "generated_on", "draft"],
        }
        for t in REPORT_TEMPLATES
    ]
