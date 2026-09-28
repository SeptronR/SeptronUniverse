"""Feature keys registered by Phase 04 (docs/Feature_Flags.md §2.13 — communication and workflow).

Bulk campaigns, scheduled sends, the WhatsApp bot, the AI assistant and emergency broadcast are Phase 24's.
"""

from app.core.features import register_feature

for _key, _name, _desc, _on, _tier, _deps in (
    ("comms.sms", "SMS", "SMS channel", True, "starter", ()),
    ("comms.whatsapp", "WhatsApp", "WhatsApp channel", False, "standard", ()),
    ("comms.email", "Email", "email channel", True, "starter", ()),
    ("comms.push", "Push", "FCM/WebPush", True, "starter", ()),
    ("comms.announcements", "Announcements", "announcements", True, "starter", ()),
    ("comms.announcement_ack", "Acknowledgements", "read receipts", True, "standard", ("comms.announcements",)),
    ("comms.preferences", "Notification preferences", "per-user preferences", True, "starter", ()),
    ("workflow.engine", "Workflow engine", "approval workflows", True, "starter", ()),
    ("workflow.delegation", "Delegation", "delegate approvals", True, "standard", ("workflow.engine",)),
):
    register_feature(
        key=_key,
        group="events",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
