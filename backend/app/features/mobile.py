"""Feature keys registered by Phase 42 (docs/Feature_Flags.md mobile group).

``mobile.app`` gates the app login and ``/mobile/config`` per institution; the others switch app-side behaviour
(offline cache + write queue, biometric lock, tablet master-detail layouts) reported to the app via ``/auth/me``.
"""

from app.core.features import register_feature

for _key, _name, _desc, _tier, _deps in (
    ("mobile.app", "Mobile app", "Flutter app access", "starter", ()),
    ("mobile.offline", "Offline mode", "read cache + write queue", "standard", ("mobile.app",)),
    ("mobile.biometric_lock", "Biometric app lock", "device biometrics", "starter", ("mobile.app",)),
    ("mobile.tablet_layout", "Tablet layouts", "master-detail layouts", "standard", ("mobile.app",)),
):
    register_feature(
        key=_key,
        group="mobile",
        name=_name,
        description=_desc,
        default_enabled=True,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
