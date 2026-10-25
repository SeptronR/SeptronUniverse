"""Feature keys registered by Phase 24 (docs/Feature_Flags.md communication group, advanced keys)."""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("comms.emergency_broadcast", "Emergency broadcast", "all-channel blast", False, "standard", ("comms.sms",)),
    ("comms.bulk_campaigns", "Bulk campaigns", "segments, campaigns", True, "standard", ("comms.sms",)),
    ("comms.scheduled_sends", "Scheduled sends", "scheduling", True, "standard", ("comms.bulk_campaigns",)),
    ("comms.whatsapp_bot", "WhatsApp bot", "chat flows", False, "professional", ("comms.whatsapp",)),
    ("comms.ai_assistant", "AI assistant", "LLM assistant", False, "professional", ()),
)

for _key, _name, _desc, _on, _tier, _deps in _KEYS:
    register_feature(
        key=_key,
        group="communication",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
