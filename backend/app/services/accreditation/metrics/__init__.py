"""Per-module metric registrations (Prompts/32 §32.6 ``metric_service`` step 1). Importing this package fills
``app.core.metrics.REGISTRY`` / ``DRILLDOWNS``."""

from app.services.accreditation.metrics import campus, hr, published, results, students  # noqa: F401

__all__ = ["campus", "hr", "published", "results", "students"]
