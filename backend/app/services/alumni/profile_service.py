"""Alumni profiles — Prompts/29 §29.6 ``profile_service`` {alumni.core, alumni.portal}.

1. **Auto-create** on ``student.graduated`` (Phase 18): graduation year, programme and contacts from the student
   record; the ``alumni`` role is granted to the student's user (portal login continues on the same account). The
   Phase 28 ``placement.alumni_employment`` event (accepted / joined offer) seeds ``alumni_employment_history
   (is_current)`` and the profile's current company — whichever of the two events arrives first, the second fills in.
   **Legacy import** (CSV / rows: registration number, name, year, programme, contacts) creates ``students(status=
   'alumni')`` stubs when no student row exists (``legacy`` flag in the side store).
2. **Claim & verification**: an unclaimed profile is claimed with registration number + graduation year + the email /
   phone on record → OTP (3 wrong codes → 429, unknown details answer with the same message — no enumeration); a
   claimed profile is verified by the coordinator (optionally with a document); ``is_verified`` gates the directory
   listing, job posting and the requests bridge. **Merge** keeps one profile, re-points employment, jobs, donations
   and the user link, and records the id mapping (audited).
3. **Consent** (DPDP): ``consent_contact``, per-field directory consent, mentor / recruiter willingness.
4. **Employment** history (adding a current job closes the previous current one), higher studies, completeness.
5. **Engagement** score from ``alumni.engagement_weights`` (recomputed nightly), chapters, membership card (Phase 26).
"""

import csv
import io
import secrets
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.alumni import DIRECTORY_FIELDS, ENGAGEMENT_WEIGHTS, PROFILE_FIELDS
from app.models.academic import Program
from app.models.alumni import AlumniEmploymentHistory, AlumniEvent, AlumniJob, AlumniProfile, Donation
from app.models.students import Student, StudentProgramEnrollment
from app.schemas.alumni import (
    AlmEmploymentIn,
    AlmEmploymentOut,
    AlmEngagementOut,
    AlmImportReport,
    AlmProfileListItem,
    AlumniImport,
    AlumniImportRow,
    AlumniProfileOut,
    AlumniProfileUpdate,
    ClaimRequest,
    ClaimResponse,
    ClaimVerify,
    ClaimVerifyResponse,
    MergeReport,
    MergeRequest,
    VerifyDecision,
)
from app.services.alumni.common import AlumniBase, forbidden, is_auditor, mask, not_found, now_utc, rule

ENTITY = "alumni_profile"
OTP_TTL = 600
CLAIM_GENERIC = "If the details match our records, a code has been sent."


def _completeness(a: AlumniProfile, employment: int) -> int:
    filled = sum(1 for f in PROFILE_FIELDS if getattr(a, f))
    return min(100, round(100 * (filled + (1 if employment else 0)) / (len(PROFILE_FIELDS) + 1)))


class ProfileService(AlumniBase):
    # ---- outputs --------------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[AlumniProfile], *, full: bool = True) -> list[AlumniProfileOut]:
        cards = await self.cards(rows)
        emp = await self.employment([a.id for a in rows]) if full else {}
        metas = await self.metas("profile", [str(a.id) for a in rows])
        masked = is_auditor(self.principal)
        out: list[AlumniProfileOut] = []
        for a in rows:
            c, m = cards.get(a.id, {}), metas.get(str(a.id), {})
            jobs = emp.get(a.id, [])
            out.append(
                AlumniProfileOut(
                    id=a.id,
                    student_id=a.student_id,
                    user_id=a.user_id,
                    name=c.get("name") or "Alumnus",
                    registration_number=c.get("registration_number"),
                    graduation_year=a.graduation_year,
                    program_id=a.program_id,
                    program=c.get("program"),
                    department_id=c.get("department_id"),
                    college_id=c.get("college_id"),
                    current_company=a.current_company,
                    designation=a.designation,
                    city=a.city,
                    country=a.country,
                    linkedin_url=a.linkedin_url,
                    email=mask(a.email) if masked else a.email,
                    phone=mask(a.phone) if masked else a.phone,
                    is_verified=a.is_verified,
                    claim_status=m.get("claim_status") or ("verified" if a.is_verified else "claimed"),
                    legacy=bool(m.get("legacy")),
                    willing_to_mentor=a.willing_to_mentor,
                    willing_to_recruit=a.willing_to_recruit,
                    consent_contact=a.consent_contact,
                    consent_directory_fields=list(m.get("consent_directory_fields") or []),
                    higher_studies=m.get("higher_studies"),
                    chapter=m.get("chapter"),
                    completeness=int(m.get("completeness") or _completeness(a, len(jobs))),
                    engagement_score=int((m.get("engagement") or {}).get("score") or 0),
                    employment=[
                        AlmEmploymentOut(
                            id=j.id,
                            company=j.company,
                            designation=j.designation,
                            from_on=j.from_on,
                            to_on=j.to_on,
                            is_current=j.is_current,
                        )
                        for j in jobs
                    ],
                    last_updated_by_alumni_at=a.last_updated_by_alumni_at,
                    created_at=a.created_at,
                    masked=masked,
                )
            )
        return out

    async def out(self, a: AlumniProfile) -> AlumniProfileOut:
        return (await self.outs([a]))[0]

    # ---- self -------------------------------------------------------------------------------------------------------------
    async def me(self) -> AlumniProfileOut:
        return await self.out(await self.require_my_profile())

    async def update_me(self, body: AlumniProfileUpdate) -> AlumniProfileOut:
        a = await self.require_my_profile(lock=True)
        data = body.model_dump(exclude_unset=True)
        m = await self.profile_meta(a.id)
        old = {k: getattr(a, k) for k in data if hasattr(a, k)}
        for key in ("consent_directory_fields", "higher_studies", "chapter"):
            if key in data:
                v = data.pop(key)
                m[key] = [f for f in v if f in DIRECTORY_FIELDS] if key == "consent_directory_fields" and v else v
        for k, v in data.items():
            setattr(a, k, str(v) if k == "email" and v else v)
        a.last_updated_by_alumni_at = now_utc()
        emp = (await self.employment([a.id])).get(a.id, [])
        m["completeness"] = _completeness(a, len(emp))
        m["profile_updates"] = int(m.get("profile_updates") or 0) + 1
        await self.put_meta("profile", a.id, m)
        await self._audit("profile_update", ENTITY, a.id, old, {**data, "consents": m.get("consent_directory_fields")})
        await self._emit("alumni.updated", {"alumni_id": str(a.id)}, ENTITY, a.id)
        return await self.out(a)

    async def my_employment(self) -> list[AlmEmploymentOut]:
        return (await self.me()).employment

    async def add_employment(self, body: AlmEmploymentIn, a: AlumniProfile | None = None) -> AlmEmploymentOut:
        a = a or await self.require_my_profile(lock=True)
        if body.is_current:
            await self._close_current(a, body.from_on)
            a.current_company, a.designation = body.company, body.designation
        row = AlumniEmploymentHistory(institution_id=self.inst, alumni_id=a.id, **body.model_dump())
        self.db.add(row)
        a.last_updated_by_alumni_at = now_utc() if a.user_id == self.actor_id else a.last_updated_by_alumni_at
        await self.db.flush()
        await self._audit("employment_add", ENTITY, a.id, None, {"company": row.company, "current": row.is_current})
        return AlmEmploymentOut.model_validate(row, from_attributes=True)

    async def _close_current(self, a: AlumniProfile, until: date | None) -> None:
        for r in (
            await self.db.execute(
                select(AlumniEmploymentHistory).where(
                    AlumniEmploymentHistory.alumni_id == a.id, AlumniEmploymentHistory.is_current.is_(True)
                )
            )
        ).scalars():
            r.is_current = False
            r.to_on = r.to_on or until or await self.today()

    async def _my_job(self, jid: uuid.UUID) -> tuple[AlumniProfile, AlumniEmploymentHistory]:
        a = await self.require_my_profile(lock=True)
        row = (
            await self.db.execute(
                select(AlumniEmploymentHistory).where(
                    AlumniEmploymentHistory.id == jid, AlumniEmploymentHistory.alumni_id == a.id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise not_found("Employment")
        return a, row

    async def update_employment(self, jid: uuid.UUID, body: AlmEmploymentIn) -> AlmEmploymentOut:
        a, row = await self._my_job(jid)
        if body.is_current and not row.is_current:
            await self._close_current(a, body.from_on)
        for k, v in body.model_dump().items():
            setattr(row, k, v)
        if row.is_current:
            a.current_company, a.designation = row.company, row.designation
        await self.db.flush()
        return AlmEmploymentOut.model_validate(row, from_attributes=True)

    async def delete_employment(self, jid: uuid.UUID) -> None:
        a, row = await self._my_job(jid)
        if row.is_current:
            a.current_company = a.designation = None
        await self.db.delete(row)
        await self.db.flush()

    # ---- engagement ---------------------------------------------------------------------------------------------------------
    async def weights(self) -> dict[str, int]:
        v = await self.setting("alumni", "engagement_weights")
        return {**ENGAGEMENT_WEIGHTS, **(v if isinstance(v, dict) else {})}

    async def compute_engagement(self, a: AlumniProfile, w: dict[str, int] | None = None) -> dict[str, Any]:
        from app.models.events import EventRegistration

        w = w or await self.weights()
        m = await self.profile_meta(a.id)
        attended = 0
        if a.student_id:
            attended = int(
                (
                    await self.db.execute(
                        select(func.count())
                        .select_from(EventRegistration)
                        .join(AlumniEvent, AlumniEvent.event_id == EventRegistration.event_id)
                        .where(
                            EventRegistration.person_id == a.student_id,
                            EventRegistration.attended.is_(True),
                        )
                    )
                ).scalar_one()
            )
        donations = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(Donation)
                    .where(
                        Donation.institution_id == self.inst,
                        Donation.donor_ref["alumni_id"].astext == str(a.id),
                    )
                )
            ).scalar_one()
        )
        jobs = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(AlumniJob).where(AlumniJob.posted_by_alumni_id == a.id)
                )
            ).scalar_one()
        )
        breakdown = {
            "profile_update": w["profile_update"] * min(int(m.get("profile_updates") or 0), 4),
            "event_attended": w["event_attended"] * attended,
            "donation": w["donation"] * donations,
            "mentoring": w["mentoring"] * (1 if a.willing_to_mentor else 0),
            "job_post": w["job_post"] * jobs,
            "survey": w["survey"] * int(m.get("surveys") or 0),
        }
        emp = (await self.employment([a.id])).get(a.id, [])
        engagement: dict[str, Any] = {
            "score": sum(breakdown.values()),
            "breakdown": breakdown,
            "at": now_utc().isoformat(),
        }
        m["engagement"] = engagement
        m["completeness"] = _completeness(a, len(emp))
        await self.put_meta("profile", a.id, m)
        return engagement

    async def my_engagement(self) -> AlmEngagementOut:
        a = await self.require_my_profile()
        e = await self.compute_engagement(a)
        return AlmEngagementOut(alumni_id=a.id, score=e["score"], breakdown=e["breakdown"], computed_at=now_utc())

    async def recompute_all(self) -> int:
        w = await self.weights()
        n = 0
        for a in (
            await self.db.execute(select(AlumniProfile).where(AlumniProfile.institution_id == self.inst))
        ).scalars():
            await self.compute_engagement(a, w)
            n += 1
        await self._emit("alumni.engagement_scored", {"profiles": n}, ENTITY, None)
        return n

    async def survey_credit(self) -> int:
        n = 0
        for (aid,) in (
            await self.db.execute(
                select(AlumniProfile.id).where(
                    AlumniProfile.institution_id == self.inst, AlumniProfile.user_id.is_not(None)
                )
            )
        ).all():
            m = await self.profile_meta(aid)
            m["surveys"] = int(m.get("surveys") or 0) + 1
            await self.put_meta("profile", aid, m)
            n += 1
        return n

    async def card(self) -> tuple[bytes, str]:
        from app.services.documents.render_service import RenderService

        a = await self.require_my_profile(verified=True)
        from app.models.documents import IssuedDocument

        rs = RenderService(self.db, self.principal, self.request, self.inst)
        res = await rs.render("alumni_membership_card", "alumni_profile", a.id)
        doc = (
            await self.db.execute(select(IssuedDocument).where(IssuedDocument.id == res.issued_document_id))
        ).scalar_one()
        return await rs.original_pdf(doc), f"alumni-card-{a.id.hex[:8]}.pdf"

    # ---- 1. auto-create / employment seed ----------------------------------------------------------------------------------------
    async def on_graduated(self, student_id: uuid.UUID, enrollment_id: uuid.UUID | None) -> AlumniProfile | None:
        if await self.setting("alumni", "auto_create_on_graduation") is False:
            return None
        st = (await self.db.execute(select(Student).where(Student.id == student_id))).scalar_one_or_none()
        if st is None:
            return None
        e = None
        if enrollment_id:
            e = (
                await self.db.execute(
                    select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == enrollment_id)
                )
            ).scalar_one_or_none()
        a = (
            await self.db.execute(select(AlumniProfile).where(AlumniProfile.student_id == st.id).with_for_update())
        ).scalar_one_or_none()
        created = a is None
        if a is None:
            a = AlumniProfile(
                institution_id=self.inst,
                student_id=st.id,
                user_id=st.user_id,
                graduation_year=(e.exit_date.year if e and e.exit_date else (await self.today()).year),
                program_id=e.program_id if e else None,
                email=st.email,
                phone=st.phone,
                city=((st.current_address or st.permanent_address or {}) or {}).get("city"),
                country="India",
                is_verified=True,  # graduated through the system — identity known
            )
            self.db.add(a)
            await self.db.flush()
        m = await self.profile_meta(a.id)
        m.setdefault("claim_status", "verified")
        m.setdefault("consent_directory_fields", await self.directory_defaults())
        m.setdefault("source", "graduation")
        pending = await self.meta("pending_employment", st.id)
        await self.put_meta("profile", a.id, m)
        if pending:
            await self.seed_employment(a, pending)
        await self.alumni_role_grant(st.user_id)
        if created:
            await self._audit("auto_create", ENTITY, a.id, None, {"student_id": str(st.id)})
            await self._emit("alumni.profile_created", {"alumni_id": str(a.id), "student_id": str(st.id)}, ENTITY, a.id)
            inst = await self.institution()
            await self._notify("alumni.profile_created", [st.user_id], {"institution": inst.name})
        return a

    async def on_employment(self, enrollment_id: uuid.UUID, payload: dict[str, Any]) -> bool:
        e = (
            await self.db.execute(select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == enrollment_id))
        ).scalar_one_or_none()
        if e is None:
            return False
        a = (
            await self.db.execute(
                select(AlumniProfile).where(AlumniProfile.student_id == e.student_id).with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            # the graduation consumer has not run yet — park the employment for it
            await self.put_meta("pending_employment", e.student_id, payload)
            return False
        return await self.seed_employment(a, payload)

    async def seed_employment(self, a: AlumniProfile, p: dict[str, Any]) -> bool:
        company = str(p.get("company") or "").strip()
        if not company:
            return False
        dup = (
            await self.db.execute(
                select(AlumniEmploymentHistory.id).where(
                    AlumniEmploymentHistory.alumni_id == a.id, AlumniEmploymentHistory.company == company
                )
            )
        ).first()
        if dup:
            return False
        await self._close_current(a, None)
        self.db.add(
            AlumniEmploymentHistory(
                institution_id=self.inst,
                alumni_id=a.id,
                company=company[:200],
                designation=(p.get("role") or None) and str(p["role"])[:120],
                from_on=await self.today(),
                is_current=True,
            )
        )
        a.current_company, a.designation = company[:200], (str(p.get("role"))[:120] if p.get("role") else None)
        m = await self.profile_meta(a.id)
        m["employment_source"] = {"offer_id": p.get("offer_id"), "ctc_paise": p.get("ctc_paise")}
        await self.put_meta("profile", a.id, m)
        await self.db.flush()
        return True

    # ---- legacy import ------------------------------------------------------------------------------------------------------------------
    async def _rows_from_file(self, url: str, mapping: dict[str, str] | None) -> list[AlumniImportRow]:
        from app.core.files import get_storage

        raw = await get_storage().get(url)
        text = raw.decode("utf-8-sig", errors="replace")
        rows: list[AlumniImportRow] = []
        for rec in csv.DictReader(io.StringIO(text)):
            data = {(mapping or {}).get(k, k): (v or "").strip() for k, v in rec.items() if k}
            try:
                rows.append(AlumniImportRow.model_validate({k: v for k, v in data.items() if v}))
            except ValueError:
                continue
        return rows

    async def import_rows(self, body: AlumniImport) -> AlmImportReport:
        self.require_coordinator()
        rows = list(body.rows or [])
        if body.file_url:
            rows += await self._rows_from_file(body.file_url, body.mapping)
        report = AlmImportReport()
        programs = {
            p.code.upper(): p
            for p in (await self.db.execute(select(Program).where(Program.institution_id == self.inst))).scalars()
        }
        college_id = body.college_id
        if college_id is None:
            from app.models.platform import College

            college_id = (
                await self.db.execute(select(College.id).where(College.institution_id == self.inst).limit(1))
            ).scalar_one_or_none()
        defaults = await self.directory_defaults()
        for i, r in enumerate(rows):
            prog = programs.get((r.program_code or "").upper())
            st = (
                await self.db.execute(
                    select(Student).where(
                        Student.institution_id == self.inst, Student.registration_number == r.registration_number
                    )
                )
            ).scalar_one_or_none()
            legacy = st is None
            if st is None:
                if college_id is None:
                    report.errors.append({"row": i + 1, "error": "no college to attach the legacy student"})
                    continue
                first, _, last = r.name.partition(" ")
                st = Student(
                    institution_id=self.inst,
                    college_id=college_id,
                    registration_number=r.registration_number,
                    first_name=first[:100],
                    last_name=last[:100] or None,
                    dob=date(r.graduation_year - 22, 1, 1),
                    gender="other",
                    email=r.email,
                    phone=r.phone,
                    status="alumni",
                )
                self.db.add(st)
                await self.db.flush()
            exists = (
                await self.db.execute(select(AlumniProfile.id).where(AlumniProfile.student_id == st.id))
            ).scalar_one_or_none()
            if exists is not None:
                report.skipped += 1
                continue
            a = AlumniProfile(
                institution_id=self.inst,
                student_id=st.id,
                user_id=st.user_id,
                graduation_year=r.graduation_year,
                program_id=prog.id if prog else None,
                email=r.email or st.email,
                phone=r.phone or st.phone,
                city=r.city,
                current_company=r.company,
                is_verified=False,
            )
            self.db.add(a)
            await self.db.flush()
            await self.put_meta(
                "profile",
                a.id,
                {
                    "claim_status": "unclaimed",
                    "legacy": legacy,
                    "source": "import",
                    "consent_directory_fields": defaults,
                },
            )
            if r.company:
                self.db.add(
                    AlumniEmploymentHistory(
                        institution_id=self.inst, alumni_id=a.id, company=r.company, is_current=True
                    )
                )
            report.created += 1 if legacy else 0
            report.linked += 0 if legacy else 1
            await self._emit("alumni.profile_created", {"alumni_id": str(a.id), "legacy": legacy}, ENTITY, a.id)
        await self._audit("import", ENTITY, None, None, report.model_dump())
        return report

    # ---- 2. claim / verify / merge ------------------------------------------------------------------------------------------------------
    async def claim(self, body: ClaimRequest) -> ClaimResponse:
        from app.db.session import redis_client
        from app.services.auth_service import _send_task

        if await self.setting("alumni", "claim_verification") == "coordinator_only":
            raise rule("Profiles are claimed through the alumni office", "CLAIM_BY_COORDINATOR", 403)
        row = (
            await self.db.execute(
                select(AlumniProfile, Student)
                .join(Student, Student.id == AlumniProfile.student_id)
                .where(
                    AlumniProfile.institution_id == self.inst,
                    Student.registration_number == body.registration_number.strip(),
                    AlumniProfile.graduation_year == body.graduation_year,
                )
            )
        ).first()
        a = row[0] if row else None
        ok = False
        channel = None
        if a is not None:
            m = await self.profile_meta(a.id)
            on_email = bool(body.email and a.email and a.email.lower() == str(body.email).lower())
            on_phone = bool(body.phone and a.phone and a.phone[-10:] == body.phone.strip()[-10:])
            ok = (on_email or on_phone) and m.get("claim_status", "unclaimed") in ("unclaimed", "rejected")
            channel = "email" if on_email else "sms" if on_phone else None
        if not ok or a is None:
            # same answer for unknown registration numbers / wrong contacts — no enumeration
            raise APIError(404, ErrorCode.NOT_FOUND, CLAIM_GENERIC, {"code": "CLAIM_NOT_MATCHED"})
        token = secrets.token_urlsafe(24)
        code = f"{secrets.randbelow(10**6):06d}"
        await redis_client.set(f"alumni_claim:{token}", f"{a.id}:{code}", ex=OTP_TTL)
        dest = str(body.email) if channel == "email" else str(body.phone)
        _send_task(
            "notifications.send_email_otp" if channel == "email" else "notifications.send_sms_otp",
            {"institution_id": str(self.inst), "destination": dest, "code": code, "ttl": OTP_TTL},
        )
        await self._audit("claim_otp_sent", ENTITY, a.id, None, {"channel": channel, "to": mask(dest)})
        return ClaimResponse(claim_token=token, channel=channel, ttl_seconds=OTP_TTL)

    async def claim_verify(self, body: ClaimVerify) -> ClaimVerifyResponse:
        from app.db.session import redis_client

        tries_key = f"alumni_claim_tries:{body.claim_token}"
        tries = int(await redis_client.get(tries_key) or 0)
        if tries >= 3:
            raise APIError(
                429, ErrorCode.RATE_LIMITED, "Too many wrong codes — start the claim again", {"code": "OTP_LOCKED"}
            )
        raw = await redis_client.get(f"alumni_claim:{body.claim_token}")
        raw = raw.decode() if isinstance(raw, bytes) else raw
        aid, _, code = str(raw or "").partition(":")
        if not raw or not secrets.compare_digest(code, body.otp.strip()):
            await redis_client.incr(tries_key)
            await redis_client.expire(tries_key, OTP_TTL)
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Wrong or expired code",
                {"code": "OTP_INVALID", "attempts_left": max(2 - tries, 0)},
            )
        await redis_client.delete(f"alumni_claim:{body.claim_token}")
        a = await self.profile(uuid.UUID(aid), lock=True, visible=False)
        m = await self.profile_meta(a.id)
        m["claim_status"] = "claimed"
        m["claimed_at"] = now_utc().isoformat()
        username = None
        if a.user_id is None:
            username = await self._ensure_user(a)
        await self.put_meta("profile", a.id, m)
        await self._audit("claim", ENTITY, a.id, None, {"claim_status": "claimed"})
        await self._emit("alumni.profile_claimed", {"alumni_id": str(a.id)}, ENTITY, a.id)
        return ClaimVerifyResponse(
            alumni_id=a.id,
            claim_status="claimed",
            username=username,
            message="Profile claimed — the alumni office verifies it next. Set your password from the emailed link.",
        )

    async def _ensure_user(self, a: AlumniProfile) -> str | None:
        """Legacy alumni get a portal account (password set through the reset link)."""
        from app.core.security import hash_password
        from app.models.platform import User

        st = (await self.db.execute(select(Student).where(Student.id == a.student_id))).scalar_one()
        username = f"alumni.{st.registration_number.lower()}"[:60]
        u = (
            await self.db.execute(select(User).where(User.institution_id == self.inst, User.username == username))
        ).scalar_one_or_none()
        if u is None:
            u = User(
                institution_id=self.inst,
                username=username,
                email=a.email,
                phone=a.phone,
                display_name=st.full_name,
                user_type="alumni",
                password_hash=hash_password(secrets.token_urlsafe(18)),
                is_verified=True,
                must_change_password=True,
            )
            self.db.add(u)
            await self.db.flush()
        a.user_id = u.id
        st.user_id = st.user_id or u.id
        await self.alumni_role_grant(u.id)
        return username

    async def verify(self, aid: uuid.UUID, body: VerifyDecision) -> AlumniProfileOut:
        self.require_coordinator("verify")
        a = await self.profile(aid, lock=True)
        m = await self.profile_meta(a.id)
        history = list(m.get("verification") or [])
        history.append(
            {
                "at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
                "approve": body.approve,
                "remarks": body.remarks,
                "document_url": body.document_url,
            }
        )
        m["verification"] = history
        m["claim_status"] = "verified" if body.approve else "rejected"
        a.is_verified = body.approve
        if body.approve and a.user_id is None:
            await self._ensure_user(a)
        await self.put_meta("profile", a.id, m)
        await self._audit("verify", ENTITY, a.id, None, {"approve": body.approve, "remarks": body.remarks})
        if body.approve:
            await self._emit("alumni.profile_verified", {"alumni_id": str(a.id)}, ENTITY, a.id)
            await self._notify("alumni.verified", [a.user_id], {})
        return await self.out(a)

    async def merge(self, body: MergeRequest) -> MergeReport:
        self.require_coordinator("verify")
        keep = await self.profile(body.keep_id, lock=True)
        drop = await self.profile(body.merge_id, lock=True)
        moved: dict[str, int] = {"employment": 0, "jobs": 0, "donations": 0}
        for r in (
            await self.db.execute(select(AlumniEmploymentHistory).where(AlumniEmploymentHistory.alumni_id == drop.id))
        ).scalars():
            r.alumni_id = keep.id
            r.is_current = r.is_current and not keep.current_company
            moved["employment"] += 1
        for j in (await self.db.execute(select(AlumniJob).where(AlumniJob.posted_by_alumni_id == drop.id))).scalars():
            j.posted_by_alumni_id = keep.id
            moved["jobs"] += 1
        for d in (
            await self.db.execute(
                select(Donation).where(
                    Donation.institution_id == self.inst, Donation.donor_ref["alumni_id"].astext == str(drop.id)
                )
            )
        ).scalars():
            d.donor_ref = {**(d.donor_ref or {}), "alumni_id": str(keep.id), "merged_from": str(drop.id)}
            moved["donations"] += 1
        for f in (*PROFILE_FIELDS, "graduation_year", "program_id", "user_id"):
            if getattr(keep, f) is None and getattr(drop, f) is not None:
                setattr(keep, f, getattr(drop, f))
        keep.is_verified = keep.is_verified or drop.is_verified
        km, dm = await self.profile_meta(keep.id), await self.profile_meta(drop.id)
        km["merged_from"] = [*(km.get("merged_from") or []), str(drop.id)]
        if keep.is_verified:
            km["claim_status"] = "verified"
        await self.put_meta("profile", keep.id, km)
        await self.put_meta("merged", drop.id, {"into": str(keep.id), "meta": dm, "student_id": str(drop.student_id)})
        old = {"merge_id": str(drop.id), "student_id": str(drop.student_id)}
        drop.user_id = None
        await self.db.flush()
        await self.db.delete(drop)
        await self.db.flush()
        await self._audit("merge", ENTITY, keep.id, old, {"kept": str(keep.id), "moved": moved})
        await self._emit(
            "alumni.profile_merged", {"kept_id": str(keep.id), "merged_id": str(body.merge_id)}, ENTITY, keep.id
        )
        return MergeReport(kept_id=keep.id, merged_id=body.merge_id, moved=moved)

    # ---- coordinator views -----------------------------------------------------------------------------------------------------------
    async def list_profiles(
        self,
        *,
        batch: int | None = None,
        program_id: uuid.UUID | None = None,
        status: str | None = None,
        department_id: uuid.UUID | None = None,
        q: str | None = None,
        scope: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[AlmProfileListItem], int]:
        if not (self.staff_reader() or self.coordinator()):
            raise forbidden("alumni:view_all required")
        stmt = (
            select(AlumniProfile)
            .join(Student, Student.id == AlumniProfile.student_id)
            .where(AlumniProfile.institution_id == self.inst, await self.profile_predicate(scope))
        )
        if batch:
            stmt = stmt.where(AlumniProfile.graduation_year == batch)
        if program_id:
            stmt = stmt.where(AlumniProfile.program_id == program_id)
        if department_id:
            stmt = stmt.where(
                AlumniProfile.program_id.in_(select(Program.id).where(Program.department_id == department_id))
            )
        if status == "verified":
            stmt = stmt.where(AlumniProfile.is_verified.is_(True))
        elif status in ("unverified", "unclaimed", "claimed", "rejected"):
            stmt = stmt.where(AlumniProfile.is_verified.is_(False))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                (Student.first_name.ilike(like))
                | (Student.last_name.ilike(like))
                | (Student.registration_number.ilike(like))
                | (AlumniProfile.current_company.ilike(like))
            )
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = list(
            (
                await self.db.execute(
                    stmt.order_by(AlumniProfile.graduation_year.desc(), Student.registration_number)
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars()
        )
        outs = await self.outs(rows, full=False)
        items = [
            AlmProfileListItem(
                **o.model_dump(
                    include={
                        "id",
                        "name",
                        "registration_number",
                        "graduation_year",
                        "program",
                        "department_id",
                        "city",
                        "current_company",
                        "email",
                        "phone",
                        "is_verified",
                        "claim_status",
                        "legacy",
                        "willing_to_mentor",
                        "willing_to_recruit",
                        "consent_contact",
                        "engagement_score",
                    }
                )
            )
            for o in outs
            if status not in ("unclaimed", "claimed", "rejected") or o.claim_status == status
        ]
        return items, total

    async def get_profile(self, aid: uuid.UUID) -> AlumniProfileOut:
        if not (self.staff_reader() or self.coordinator()):
            raise forbidden("alumni:view_all required")
        return await self.out(await self.profile(aid))

    async def export_rows(self, scope: str | None = None) -> list[dict[str, Any]]:
        """Coordinator export (audited). Contacts only for alumni who consented to contact."""
        if not (self.can("alumni", "export") or self.can("alumni", "manage")) or is_auditor(self.principal):
            raise forbidden("alumni:export required")
        rows = list(
            (
                await self.db.execute(
                    select(AlumniProfile).where(
                        AlumniProfile.institution_id == self.inst, await self.profile_predicate(scope)
                    )
                )
            ).scalars()
        )
        outs = await self.outs(rows, full=False)
        await self._audit("export", ENTITY, None, None, {"rows": len(outs)})
        return [
            {
                "registration_number": o.registration_number,
                "name": o.name,
                "graduation_year": o.graduation_year,
                "program": o.program,
                "city": o.city,
                "company": o.current_company,
                "designation": o.designation,
                "email": o.email if o.consent_contact else None,
                "phone": o.phone if o.consent_contact else None,
                "verified": o.is_verified,
                "mentor": o.willing_to_mentor,
                "recruiter": o.willing_to_recruit,
            }
            for o in outs
        ]

    # ---- annual update campaign / claim links ---------------------------------------------------------------------------------------
    async def claim_links(self, ids: list[uuid.UUID] | None = None) -> int:
        inst = await self.institution()
        stmt = (
            select(AlumniProfile, Student.registration_number)
            .join(Student, Student.id == AlumniProfile.student_id)
            .where(AlumniProfile.institution_id == self.inst, AlumniProfile.user_id.is_(None))
        )
        if ids:
            stmt = stmt.where(AlumniProfile.id.in_(ids))
        n = 0
        for a, reg in (await self.db.execute(stmt)).all():
            if not a.email:
                continue
            await self._notify(
                "alumni.claim_link",
                [],
                {"institution": inst.name, "registration_number": reg, "link": "/alumni/claim"},
                audience={"emails": [a.email]},
            )
            n += 1
        return n

    async def update_campaign(self) -> int:
        cutoff = now_utc() - timedelta(days=330)
        n = 0
        for a in (
            await self.db.execute(
                select(AlumniProfile).where(
                    AlumniProfile.institution_id == self.inst,
                    AlumniProfile.user_id.is_not(None),
                    (AlumniProfile.last_updated_by_alumni_at.is_(None))
                    | (AlumniProfile.last_updated_by_alumni_at < cutoff),
                )
            )
        ).scalars():
            await self._notify("alumni.profile_update_reminder", [a.user_id], {"link": "/alumni/profile"})
            n += 1
        return n


# ---- Phase 26 resolver ---------------------------------------------------------------------------------------------------------------
def _register() -> None:
    from app.services.documents.render_service import RenderService, register_resolver

    @register_resolver("alumni_profile")
    async def _alumni_ctx(svc: RenderService, aid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
        a = (await svc.db.execute(select(AlumniProfile).where(AlumniProfile.id == aid))).scalar_one()
        st = (await svc.db.execute(select(Student).where(Student.id == a.student_id))).scalar_one()
        prog = (
            (await svc.db.execute(select(Program).where(Program.id == a.program_id))).scalar_one_or_none()
            if a.program_id
            else None
        )
        ctx = {
            "alumni": {
                "name": st.full_name,
                "registration_number": st.registration_number,
                "program": prog.name if prog else "",
                "batch": a.graduation_year or "",
                "member_no": f"ALM-{a.graduation_year or 0}-{str(a.id)[:8].upper()}",
                "company": a.current_company or "",
            }
        }
        return ctx, "alumni", st.id


_register()
