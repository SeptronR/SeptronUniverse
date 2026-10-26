"""Alumni directory — Prompts/29 §29.6 ``directory_service`` {alumni.portal}.

Search with facets (batch, programme, city, company) over **verified** profiles; each entry is projected to the
row's consented fields (``profile:<id>.consent_directory_fields``) ∩ the requester class: alumni see every consented
field, students (only when ``alumni.directory_open_to_students``) never see contacts, staff readers (coordinator,
placement officer — mentor / recruiter finder, HOD — department alumni) see consented fields. Contacts appear only
with ``consent_contact``; a profile with no directory consent is not listed. The endpoint is rate-limited. Contact
requests are relayed as in-app / email notifications without exposing either side's contacts (403 ``NO_CONSENT``
when the recipient did not consent to contact).
"""

import uuid
from collections import Counter
from typing import Any, Literal

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.alumni import CONTACT_FIELDS, STUDENT_FIELDS
from app.models.academic import Program
from app.models.alumni import AlumniProfile
from app.schemas.alumni import ContactRequest, ContactRequestOut, DirectoryEntry, DirectoryFacets, DirectoryPage
from app.services.alumni.common import AlumniBase, dept_subquery, forbidden, rule, scope_ids

Requester = Literal["alumni", "student", "staff"]


class DirectoryService(AlumniBase):
    async def requester(self) -> tuple[Requester, AlumniProfile | None]:
        me = await self.my_profile()
        if me is not None:
            return "alumni", me
        if self.staff_reader() or self.coordinator():
            return "staff", None
        if self.can("alumni", "self") and await self.my_student() is not None:
            if await self.setting("alumni", "directory_open_to_students") is True:
                return "student", None
            raise forbidden("The alumni directory is not open to students")
        raise forbidden("alumni:self|view_all required")

    @staticmethod
    def project(a: AlumniProfile, card: dict[str, Any], consent: list[str], who: Requester) -> dict[str, Any]:
        values = {
            "name": card.get("name"),
            "batch": a.graduation_year,
            "program": card.get("program"),
            "city": a.city,
            "country": a.country,
            "company": a.current_company,
            "designation": a.designation,
            "linkedin_url": a.linkedin_url,
            "email": a.email,
            "phone": a.phone,
        }
        allowed = set(consent)
        if who == "student":
            allowed &= STUDENT_FIELDS
        if not a.consent_contact:
            allowed -= CONTACT_FIELDS
        return {k: v for k, v in values.items() if k in allowed and v not in (None, "")}

    async def search(
        self,
        *,
        q: str | None = None,
        batch: int | None = None,
        program_id: uuid.UUID | None = None,
        city: str | None = None,
        company: str | None = None,
        willing_to_mentor: bool | None = None,
        willing_to_recruit: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> DirectoryPage:
        who, me = await self.requester()
        stmt = select(AlumniProfile).where(
            AlumniProfile.institution_id == self.inst, AlumniProfile.is_verified.is_(True)
        )
        if me is not None:
            stmt = stmt.where(AlumniProfile.id != me.id)
        p = self.principal
        if who == "staff" and not self.all_access() and not self.can("placement", "manage"):
            if scope_ids(p, "department") or scope_ids(p, "faculty"):
                stmt = stmt.where(
                    AlumniProfile.program_id.in_(select(Program.id).where(Program.department_id.in_(dept_subquery(p))))
                )
            else:
                stmt = stmt.where(await self.profile_predicate())
        if batch:
            stmt = stmt.where(AlumniProfile.graduation_year == batch)
        if program_id:
            stmt = stmt.where(AlumniProfile.program_id == program_id)
        if city:
            stmt = stmt.where(func.lower(AlumniProfile.city) == city.strip().lower())
        if company:
            stmt = stmt.where(AlumniProfile.current_company.ilike(f"%{company.strip()}%"))
        if willing_to_mentor is not None:
            stmt = stmt.where(AlumniProfile.willing_to_mentor.is_(willing_to_mentor))
        if willing_to_recruit is not None:
            stmt = stmt.where(AlumniProfile.willing_to_recruit.is_(willing_to_recruit))
        rows = list((await self.db.execute(stmt.order_by(AlumniProfile.graduation_year.desc()).limit(2000))).scalars())
        cards = await self.cards(rows)
        metas = await self.metas("profile", [str(a.id) for a in rows])
        entries: list[DirectoryEntry] = []
        facets: dict[str, Counter[str]] = {k: Counter() for k in ("batch", "program", "city", "company")}
        needle = (q or "").strip().lower()
        for a in rows:
            consent = list(metas.get(str(a.id), {}).get("consent_directory_fields") or [])
            if not consent:
                continue  # directory consent off → not listed
            fields = self.project(a, cards.get(a.id, {}), consent, who)
            if needle and needle not in " ".join(str(v) for v in fields.values()).lower():
                continue
            for k, counter in facets.items():
                if fields.get(k):
                    counter[str(fields[k])] += 1
            entries.append(
                DirectoryEntry(
                    id=a.id,
                    fields=fields,
                    willing_to_mentor=a.willing_to_mentor,
                    willing_to_recruit=a.willing_to_recruit,
                    contactable=a.consent_contact,
                )
            )
        return DirectoryPage(
            items=entries[offset : offset + limit],
            total=len(entries),
            facets=DirectoryFacets(**{k: dict(v.most_common(20)) for k, v in facets.items()}),
            requester=who,
        )

    async def contact(self, aid: uuid.UUID, body: ContactRequest) -> ContactRequestOut:
        who, me = await self.requester()
        self.require_writer()
        if me is not None and not me.is_verified:
            raise rule("Your alumni profile is not verified yet", "VERIFICATION_REQUIRED", 403)
        target = (
            await self.db.execute(
                select(AlumniProfile).where(
                    AlumniProfile.id == aid,
                    AlumniProfile.institution_id == self.inst,
                    AlumniProfile.is_verified.is_(True),
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Alumni profile not found")
        if not target.consent_contact:
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "This alumnus has not consented to contact", {"code": "NO_CONSENT"}
            )
        sender, sender_batch = "A member of the institution", ""
        if me is not None:
            c = (await self.cards([me])).get(me.id, {})
            sender, sender_batch = c.get("name") or "An alumnus", str(me.graduation_year or "")
        elif self.actor_id is not None:
            names = await self.user_display([self.actor_id])
            sender = names.get(self.actor_id) or sender
            sender_batch = who
        rid = uuid.uuid4()
        await self.put_meta(
            "contact",
            rid,
            {"from_user": str(self.actor_id), "to_alumni": str(target.id), "message": body.message, "who": who},
        )
        await self._notify(
            "alumni.contact_request",
            [target.user_id],
            {"sender": sender, "sender_batch": sender_batch, "message": body.message[:500]},
        )
        await self._audit("contact_request", "alumni_profile", target.id, None, {"request_id": str(rid), "who": who})
        await self._emit(
            "alumni.contact_requested",
            {"alumni_id": str(target.id), "request_id": str(rid)},
            "alumni_profile",
            target.id,
        )
        return ContactRequestOut(
            id=rid, to_alumni_id=target.id, relayed=target.user_id is not None, channels=["in_app", "email"]
        )
