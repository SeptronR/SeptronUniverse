"""Disclosures and faculty-directory settings — Prompts/40 §40.8 (``website:manage`` | ``accreditation:manage``).

Disclosure items (``website_meta disclosures``): ``metric`` (Phase 32 ``metric_values`` by ``metric_key``), ``policy``
/ ``document`` (URL of a Phase 33 policy file / Phase 26 document), ``text``; only ``is_published`` items render.
The directory settings choose the allow-listed fields (``website.faculty_directory_fields``) and the opt-out list.
"""

from app.core.errors import APIError, ErrorCode
from app.schemas.website import DisclosureSettingsIO, FacultyDirectorySettingsIO
from app.services.website.common import WebsiteBase, invalidate
from app.services.website.public_service import DIRECTORY_COLUMNS


class WebsiteSettingsService(WebsiteBase):
    def _editor(self) -> None:
        if not (self.can("manage") or (self.principal and self.principal.has("accreditation", "manage"))):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")

    async def disclosures(self) -> DisclosureSettingsIO:
        self.require("view", "update", "manage")
        return DisclosureSettingsIO.model_validate(await self.meta("disclosures", {}) or {})

    async def save_disclosures(self, body: DisclosureSettingsIO) -> DisclosureSettingsIO:
        self._editor()
        await self.put_meta("disclosures", body.model_dump(mode="json"))
        await invalidate(self.inst)
        await self.audit(
            "disclosures_update", "website_disclosures", None, {"published": sum(i.is_published for i in body.items)}
        )
        return body

    async def directory(self) -> FacultyDirectorySettingsIO:
        self.require("view", "manage")
        return FacultyDirectorySettingsIO(
            fields=list(await self.setting("faculty_directory_fields") or []),
            opt_out=list(await self.setting("faculty_directory_opt_out") or []),
        )

    async def save_directory(self, body: FacultyDirectorySettingsIO) -> FacultyDirectorySettingsIO:
        self.require("manage")
        bad = [f for f in body.fields if f not in DIRECTORY_COLUMNS]
        if bad:
            raise APIError(422, ErrorCode.VALIDATION, f"Fields not allowed: {', '.join(bad)}", {"field": "fields"})
        from app.schemas.settings import SettingItem
        from app.services.settings_service import SettingsService

        await SettingsService(self.db, self.principal).bulk_update(
            [
                SettingItem(category="website", key="faculty_directory_fields", value=body.fields),
                SettingItem(category="website", key="faculty_directory_opt_out", value=[str(x) for x in body.opt_out]),
            ],
            self.request,
        )
        await self.audit("directory_update", "website_directory", None, {"fields": body.fields})
        await invalidate(self.inst)
        return body
