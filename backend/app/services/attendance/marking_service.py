"""Session marking — Prompts/11 §11.6 ``attendance_service.py`` (rules 1–7).

1. ``session_for_marking``: the roster is the offering's **confirmed** registration items of the session's term,
   section-filtered through the timetable entry's ``section_id`` (Phase 10); existing marks; approved OD covering the
   date pre-fills ``on_duty``. Staff only (students read their own history through the summaries).
2. ``bulk_mark``: the session row is locked ``FOR UPDATE``; the caller teaches the offering / owns the session
   (substituted sessions belong to the substitute) or is HOD / registrar over its department; the session must be
   ``scheduled|conducted``, not finalized (409 ``RECORD_LOCKED``) and not later than today + ``future_marking_days``
   (409 ``RULE_VIOLATION FUTURE_SESSION``). Idempotent upsert; ``mark_rest_as`` fills the unmarked roster (approved OD →
   ``on_duty``); students outside the roster come back in ``rejected[]``. The session becomes ``conducted`` /
   ``taken``; one audit row with the counts; ``attendance.marked`` emitted; the offering's summaries are recomputed
   inline (a single aggregate query) and **guardian alerts** fire once per absence streak.
3. ``finalize`` locks; ``edit_finalized`` (``attendance:edit_finalized`` — HOD / registrar over the department) writes
   one audit row per changed mark with old / new and the reason. Beat ``attendance.auto_finalize`` finalizes taken
   sessions older than ``auto_finalize_days``.
4. QR: ``issue_qr`` stores a random token on the session (``qr_token`` / ``qr_expires_at``, ``qr_ttl_seconds``,
   rotating — each issue replaces the previous); ``qr_checkin`` marks the calling student ``present`` (``late`` after
   ``qr_late_minutes``) when registered (409 ``RULE_VIOLATION NOT_REGISTERED``) — an expired / unknown token is 401,
   a repeated scan a no-op.
5. Geo check-in ({attendance.geo_app}): during the session window inside the college geo-fence
   (``attendance.geo_fence`` {lat, lng, radius_m}) → ``present`` with ``source='app'`` and a *pending review* remark;
   outside → 422.
6. Device punches ({attendance.biometric|rfid}): device token (SHA-256 as Phase 06), identifier = registration /
   enrolment number; the session is the one running at that time in the device's room (``attendance_devices.location``
   = room code) or, without a room, the student's own session at that time; unknown / ambiguous punches are recorded
   as audit rows (``record_type='attendance_punch'``, action ``unmatched``) and listed for review.
7. Offline batch: per-item savepoints; finalized sessions answer ``RECORD_LOCKED`` per item; the batch key is kept
   for 24 h (replay returns the stored result).
"""

import base64
import contextlib
import hashlib
import io
import json
import math
import secrets
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select

from app.core.errors import APIError, ErrorCode
from app.models.attendance import StudentClassAttendance
from app.models.hr import AttendanceDevice
from app.models.platform import AuditLog
from app.models.students import Student
from app.models.timetable import ClassSession, Room
from app.schemas.attendance import (
    BulkMarkRequest,
    CheckinResult,
    EditFinalizedRequest,
    FinalizeRequest,
    GeoCheckinRequest,
    MarkResult,
    OfflineBatch,
    OfflineBatchResult,
    OfflineItemResult,
    QrCheckinRequest,
    QrIssueResponse,
    RejectedMark,
    RosterRow,
    SessionForAttendance,
    StudentPunchIngest,
    StudentPunchResult,
    UnmatchedPunch,
)
from app.services.attendance.common import ATT, AttendanceBase, rule, student_name
from app.services.timetable.common import now_utc

SESSION = "class_session"
PUNCH = "attendance_punch"
NOT_ATTENDED = ("absent", "leave", "medical")


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _qr_png(token: str) -> str | None:
    try:
        import qrcode

        img = qrcode.make(token)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 - the client can render the token itself
        return None


class MarkingService(AttendanceBase):
    # ---- 1. roster ------------------------------------------------------------------------------------------------
    async def session_for_marking(self, session_id: uuid.UUID) -> SessionForAttendance:
        self.assert_staff()
        s = await self.sessions.get_one(session_id)
        return await self._sheet(s)

    async def _sheet(self, s: ClassSession) -> SessionForAttendance:
        roster = await self.marks.roster(s)
        marks = await self.marks.marks(s)
        od = await self.ods.approved_covering([r[0] for r in roster], s.session_date)
        rows: list[RosterRow] = []
        counts: dict[str, int] = defaultdict(int)
        for enr_id, stu_id, first, last, regno, roll, photo, _uid in roster:
            m = marks.get(enr_id)
            if m is not None:
                counts[m.status] += 1
            rows.append(
                RosterRow(
                    student_program_enrollment_id=enr_id,
                    student_id=stu_id,
                    name=" ".join(p for p in (first, last) if p),
                    registration_number=regno,
                    roll_number=roll,
                    photo_url=photo,
                    status=m.status if m else None,
                    source=m.source if m else None,
                    remarks=m.remarks if m else None,
                    marked_at=m.marked_at if m else None,
                    prefill="on_duty" if enr_id in od else None,
                )
            )
        counts["roster"] = len(rows)
        counts["unmarked"] = sum(1 for r in rows if r.status is None)
        labels = await self.session_labels(s)
        return SessionForAttendance(
            session_id=s.id,
            offering_id=s.offering_id,
            session_date=s.session_date,
            start_time=s.start_time,
            end_time=s.end_time,
            staff_id=s.staff_id,
            status=s.status,
            attendance_status=s.attendance_status,
            finalized_at=s.finalized_at,
            can_mark=await self.may_mark(s) and s.attendance_status != "finalized",
            can_edit_finalized=self.can(ATT, "edit_finalized") and await self.unit_admin(s),
            counts=dict(counts),
            roster=rows,
            **labels,
        )

    # ---- 2. bulk mark ---------------------------------------------------------------------------------------------
    async def bulk_mark(self, session_id: uuid.UUID, body: BulkMarkRequest) -> MarkResult:
        s = await self.sessions.get_one(session_id, for_update=True)
        await self.assert_mark(s)
        await self.assert_markable(s)
        return await self._apply(s, body)

    async def _apply(self, s: ClassSession, body: BulkMarkRequest) -> MarkResult:
        roster = {r[0]: r for r in await self.marks.roster(s)}
        existing = await self.marks.marks(s)
        od = await self.ods.approved_covering(list(roster), s.session_date)
        wanted: dict[uuid.UUID, tuple[str, str | None]] = {}
        result = MarkResult(session_id=s.id)
        for item in body.marks:
            if item.student_program_enrollment_id not in roster:
                result.rejected.append(
                    RejectedMark(
                        student_program_enrollment_id=item.student_program_enrollment_id, reason="NOT_IN_ROSTER"
                    )
                )
                continue
            wanted[item.student_program_enrollment_id] = (str(item.status), item.remarks)
        for enr_id in roster:
            if enr_id in wanted:
                continue
            if enr_id in od and (enr_id not in existing or existing[enr_id].status in NOT_ATTENDED):
                wanted[enr_id] = ("on_duty", "approved OD")
            elif body.mark_rest_as and enr_id not in existing:
                wanted[enr_id] = (body.mark_rest_as, None)
        rows: list[dict[str, Any]] = []
        newly_absent: list[uuid.UUID] = []
        for enr_id, (status, remarks) in wanted.items():
            old = existing.get(enr_id)
            if old is not None and old.status == status and (remarks is None or old.remarks == remarks):
                result.unchanged += 1
                continue
            if old is None:
                result.created += 1
            else:
                result.updated += 1
            if status == "absent" and (old is None or old.status != "absent"):
                newly_absent.append(enr_id)
            rows.append(
                {
                    "student_program_enrollment_id": enr_id,
                    "status": status,
                    "source": str(body.source),
                    "marked_by": self.actor_id,
                    "remarks": remarks if remarks is not None else (old.remarks if old else None),
                }
            )
        await self.marks.upsert_marks(s, rows)
        first = s.attendance_status == "not_taken"
        s.status = "conducted"
        if s.attendance_status == "not_taken":
            s.attendance_status = "taken"
            s.attendance_taken_at = now_utc()
        if body.topic:
            s.topic = body.topic
        result.attendance_status = s.attendance_status
        await self.db.flush()
        await self._audit(
            "mark",
            SESSION,
            s.id,
            None,
            {
                "created": result.created,
                "updated": result.updated,
                "unchanged": result.unchanged,
                "rejected": len(result.rejected),
                "source": str(body.source),
                "first_marking": first,
            },
        )
        await self._emit(
            "attendance.marked",
            {
                "session_id": str(s.id),
                "offering_id": str(s.offering_id),
                "session_date": s.session_date.isoformat(),
                "created": result.created,
                "updated": result.updated,
            },
            SESSION,
            s.id,
        )
        if rows:
            from app.services.attendance.summary_service import SummaryService

            await SummaryService(self.db, self.principal, self.request, self.inst).recompute(s.offering_id)
            await self.streak_alerts(s, newly_absent)
        return result

    async def streak_alerts(self, s: ClassSession, enrolment_ids: list[uuid.UUID]) -> int:
        """``attendance.absent_alert`` exactly when an absence streak reaches ``absent_alert_consecutive`` (OD / exempt
        marks neither break nor extend a streak)."""
        from app.core.features import is_enabled

        if not enrolment_ids or not await is_enabled(self.inst, "attendance.guardian_alerts"):
            return 0
        n = int(await self.att_setting("absent_alert_consecutive", 3))
        guardians = bool(await self.att_setting("notify_guardians", True))
        labels = await self.session_labels(s)
        people = await self.enrolments(enrolment_ids)
        sent = 0
        for enr_id in enrolment_ids:
            recent = (
                (
                    await self.db.execute(
                        select(StudentClassAttendance.status)
                        .join(
                            ClassSession,
                            and_(
                                ClassSession.id == StudentClassAttendance.session_id,
                                ClassSession.session_date == StudentClassAttendance.session_date,
                            ),
                        )
                        .where(
                            StudentClassAttendance.student_program_enrollment_id == enr_id,
                            StudentClassAttendance.status.notin_(("on_duty", "exempt")),
                            ClassSession.session_date <= s.session_date,
                        )
                        .order_by(ClassSession.session_date.desc(), ClassSession.start_time.desc())
                        .limit(n + 1)
                    )
                )
                .scalars()
                .all()
            )
            streak = list(recent[:n])
            if len(streak) < n or any(x != "absent" for x in streak):
                continue
            if len(recent) > n and recent[n] == "absent":
                continue  # already alerted for this streak
            enrol, student = people.get(enr_id, (None, None))
            if student is None:
                continue
            await self._notify(
                "attendance.absent_alert",
                [student.user_id],
                {
                    "student_name": student_name(student),
                    "course": labels.get("course_code") or "class",
                    "date": s.session_date.isoformat(),
                    "streak": n,
                },
                guardians=guardians,
            )
            await self._emit(
                "attendance.absent_alert",
                {"student_program_enrollment_id": str(enr_id), "streak": n, "session_id": str(s.id)},
                SESSION,
                s.id,
            )
            sent += 1
        return sent

    # ---- 3. finalize / edit -----------------------------------------------------------------------------------------
    async def finalize(self, session_id: uuid.UUID, body: FinalizeRequest | None = None) -> SessionForAttendance:
        s = await self.sessions.get_one(session_id, for_update=True)
        await self.assert_mark(s)
        if s.attendance_status == "finalized":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Already finalized")
        if s.attendance_status != "taken":
            raise rule("Attendance has not been taken for this session", "NOT_TAKEN")
        self._finalize_row(s, self.actor_id)
        await self.db.flush()
        await self._audit(
            "finalize",
            SESSION,
            s.id,
            {"attendance_status": "taken"},
            {"attendance_status": "finalized", "note": body.note if body else None},
        )
        await self._emit(
            "attendance.finalized", {"session_id": str(s.id), "offering_id": str(s.offering_id)}, SESSION, s.id
        )
        return await self._sheet(s)

    @staticmethod
    def _finalize_row(s: ClassSession, by: uuid.UUID | None) -> None:
        s.attendance_status, s.finalized_at, s.finalized_by = "finalized", now_utc(), by
        s.qr_token, s.qr_expires_at = None, None

    async def edit_finalized(self, session_id: uuid.UUID, body: EditFinalizedRequest) -> MarkResult:
        s = await self.sessions.get_one(session_id, for_update=True)
        if not (self.can(ATT, "edit_finalized") and await self.unit_admin(s)):
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "Editing finalized attendance needs attendance:edit_finalized"
            )
        return await self.privileged_edit(
            s, {m.student_program_enrollment_id: (str(m.status), m.remarks) for m in body.marks}, body.reason
        )

    async def privileged_edit(
        self, s: ClassSession, changes: dict[uuid.UUID, tuple[str, str | None]], reason: str, source: str = "manual"
    ) -> MarkResult:
        """Audited per-row edit (finalized sessions, OD applied after the fact)."""
        roster = {r[0] for r in await self.marks.roster(s)}
        existing = await self.marks.marks(s)
        result = MarkResult(session_id=s.id, attendance_status=s.attendance_status)
        rows: list[dict[str, Any]] = []
        for enr_id, (status, remarks) in changes.items():
            if enr_id not in roster:
                result.rejected.append(RejectedMark(student_program_enrollment_id=enr_id, reason="NOT_IN_ROSTER"))
                continue
            old = existing.get(enr_id)
            if old is not None and old.status == status:
                result.unchanged += 1
                continue
            rows.append(
                {
                    "student_program_enrollment_id": enr_id,
                    "status": status,
                    "source": old.source if old else source,
                    "marked_by": self.actor_id,
                    "remarks": (remarks or reason)[:255],
                }
            )
            if old is None:
                result.created += 1
            else:
                result.updated += 1
            await self._audit(
                "edit_finalized" if s.attendance_status == "finalized" else "edit",
                "student_class_attendance",
                old.id if old else None,
                {"status": old.status if old else None, "session_id": str(s.id), "enrolment_id": str(enr_id)},
                {"status": status, "session_id": str(s.id), "enrolment_id": str(enr_id), "reason": reason},
            )
        await self.marks.upsert_marks(s, rows)
        await self.db.flush()
        if rows:
            await self._emit(
                "attendance.edited_after_finalize",
                {"session_id": str(s.id), "changed": len(rows), "reason": reason},
                SESSION,
                s.id,
            )
            from app.services.attendance.summary_service import SummaryService

            await SummaryService(self.db, self.principal, self.request, self.inst).recompute(s.offering_id)
        return result

    async def auto_finalize(self) -> int:
        days = int(await self.att_setting("auto_finalize_days", 3))
        if days <= 0:
            return 0
        cutoff = await self.today() - timedelta(days=days)
        rows = (
            (
                await self.db.execute(
                    select(ClassSession)
                    .where(
                        ClassSession.institution_id == self.inst,
                        ClassSession.attendance_status == "taken",
                        ClassSession.session_date <= cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for s in rows:
            self._finalize_row(s, None)
        if rows:
            await self.db.flush()
            await self._audit(
                "auto_finalize", SESSION, None, None, {"sessions": len(rows), "cutoff": cutoff.isoformat()}
            )
        return len(rows)

    # ---- 4. QR ------------------------------------------------------------------------------------------------------
    async def issue_qr(self, session_id: uuid.UUID) -> QrIssueResponse:
        s = await self.sessions.get_one(session_id, for_update=True)
        await self.assert_mark(s)
        await self.assert_markable(s)
        if s.session_date != await self.today():
            raise rule("QR attendance runs on the day of the session", "NOT_TODAY")
        ttl = int(await self.att_setting("qr_ttl_seconds", 120))
        s.qr_token = secrets.token_urlsafe(24)[:32]
        s.qr_expires_at = now_utc() + timedelta(seconds=ttl)
        await self.db.flush()
        checked = (
            await self.db.execute(
                select(func.count()).where(
                    StudentClassAttendance.session_id == s.id,
                    StudentClassAttendance.session_date == s.session_date,
                    StudentClassAttendance.source == "qr",
                )
            )
        ).scalar_one()
        return QrIssueResponse(
            session_id=s.id,
            token=s.qr_token,
            expires_at=s.qr_expires_at,
            ttl_seconds=ttl,
            png_base64=_qr_png(s.qr_token),
            checked_in=int(checked),
        )

    async def _self_mark(self, s: ClassSession, source: str, remarks: str | None = None) -> CheckinResult:
        _, enrolment = await self.me()
        roster = {r[0] for r in await self.marks.roster(s)}
        labels = await self.session_labels(s)
        if enrolment.id not in roster:
            raise rule("You are not registered in this course", "NOT_REGISTERED")
        if s.attendance_status == "finalized":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Attendance of this session is finalized")
        existing = (await self.marks.marks(s)).get(enrolment.id)
        if existing is not None and existing.status in ("present", "late", "on_duty"):
            return CheckinResult(
                session_id=s.id,
                status=existing.status,
                source=existing.source,
                duplicate=True,
                course_code=labels["course_code"],
            )
        now = await self.local_now()
        start = datetime.combine(s.session_date, s.start_time, tzinfo=now.tzinfo)
        late_after = int(await self.att_setting("qr_late_minutes", 10))
        status = "late" if now > start + timedelta(minutes=late_after) else "present"
        await self.marks.upsert_marks(
            s,
            [
                {
                    "student_program_enrollment_id": enrolment.id,
                    "status": status,
                    "source": source,
                    "marked_by": self.actor_id,
                    "remarks": remarks,
                }
            ],
        )
        if s.attendance_status == "not_taken":
            s.status, s.attendance_status, s.attendance_taken_at = "conducted", "taken", now_utc()
        await self.db.flush()
        await self._emit(
            "attendance.marked",
            {
                "session_id": str(s.id),
                "offering_id": str(s.offering_id),
                "self_checkin": source,
                "student_program_enrollment_id": str(enrolment.id),
            },
            SESSION,
            s.id,
        )
        return CheckinResult(session_id=s.id, status=status, source=source, course_code=labels["course_code"])

    async def qr_checkin(self, body: QrCheckinRequest) -> CheckinResult:
        s = (
            await self.db.execute(
                select(ClassSession)
                .where(ClassSession.institution_id == self.inst, ClassSession.qr_token == body.token)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if s is None or s.qr_expires_at is None or s.qr_expires_at < now_utc():
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "The QR code has expired — scan the current one")
        if body.geo is not None:
            await self._assert_inside(s, body.geo.lat, body.geo.lng)
        return await self._self_mark(s, "qr")

    # ---- 5. geo -----------------------------------------------------------------------------------------------------
    async def _assert_inside(self, s: ClassSession, lat: float, lng: float) -> None:
        fence = await self.att_setting("geo_fence", None, s.college_id)
        if not isinstance(fence, dict) or fence.get("lat") is None:
            return
        dist = _haversine_m(float(fence["lat"]), float(fence["lng"]), lat, lng)
        if dist > float(fence.get("radius_m") or 200):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "You are outside the campus geo-fence",
                {"reason": "OUTSIDE_FENCE", "distance_m": round(dist)},
            )

    async def geo_checkin(self, body: GeoCheckinRequest) -> CheckinResult:
        s = await self.sessions.get_one(body.session_id, for_update=True)
        fence = await self.att_setting("geo_fence", None, s.college_id)
        if not isinstance(fence, dict) or fence.get("lat") is None:
            raise APIError(422, ErrorCode.VALIDATION, "No geo-fence is configured", {"reason": "NO_FENCE"})
        now = await self.local_now()
        start = datetime.combine(s.session_date, s.start_time, tzinfo=now.tzinfo)
        end = datetime.combine(s.session_date, s.end_time, tzinfo=now.tzinfo)
        if not (start - timedelta(minutes=10) <= now <= end):
            raise rule("Check-in is open only during the class", "OUTSIDE_SESSION_WINDOW")
        await self._assert_inside(s, body.lat, body.lng)
        return await self._self_mark(s, "app", "app check-in — pending faculty review")

    # ---- 6. device punches -----------------------------------------------------------------------------------------
    async def ingest_punches(self, device_id: uuid.UUID, body: StudentPunchIngest) -> StudentPunchResult:
        device = (
            await self.db.execute(select(AttendanceDevice).where(AttendanceDevice.id == device_id))
        ).scalar_one_or_none()
        if (
            device is None
            or not device.is_active
            or not secrets.compare_digest(device.token_hash, hashlib.sha256(body.device_token.encode()).hexdigest())
        ):
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid device token")
        if device.applies_to not in ("students", "both"):
            raise APIError(422, ErrorCode.VALIDATION, "This device records staff attendance only")
        device.last_seen_at = now_utc()
        source = "rfid" if device.device_type == "rfid" else "biometric"
        tz = await self.tz()
        room = None
        if device.location:
            room = (
                await self.db.execute(
                    select(Room).where(Room.institution_id == self.inst, Room.code == device.location.strip())
                )
            ).scalar_one_or_none()
        idents = sorted({p.identifier.strip() for p in body.punches})
        students = {
            k: v
            for st in (
                await self.db.execute(
                    select(Student).where(
                        Student.institution_id == self.inst,
                        Student.deleted_at.is_(None),
                        (Student.registration_number.in_(idents)) | (Student.enrolment_number.in_(idents)),
                    )
                )
            ).scalars()
            for k, v in ((st.registration_number, st), (st.enrolment_number, st))
            if k
        }
        out = StudentPunchResult()
        for p in body.punches:
            ident = p.identifier.strip()
            at = (p.at if p.at.tzinfo else p.at.replace(tzinfo=tz)).astimezone(tz)
            student = students.get(ident)
            if student is None:
                await self._unmatched(device, ident, at, "UNKNOWN_IDENTIFIER", out)
                continue
            enrolment = await self.enrollments.open_for(student.id)
            if enrolment is None:
                await self._unmatched(device, ident, at, "NO_ENROLMENT", out)
                continue
            stmt = select(ClassSession).where(
                ClassSession.institution_id == self.inst,
                ClassSession.session_date == at.date(),
                ClassSession.start_time <= (at + timedelta(minutes=15)).time(),
                ClassSession.end_time >= at.time(),
                ClassSession.status.in_(("scheduled", "conducted")),
            )
            if room is not None:
                stmt = stmt.where(ClassSession.room_id == room.id)
            candidates = [
                s
                for s in (await self.db.execute(stmt)).scalars().all()
                if enrolment.id in {r[0] for r in await self.marks.roster(s)}
            ]
            if len(candidates) != 1:
                await self._unmatched(
                    device, ident, at, "NO_SESSION" if not candidates else "AMBIGUOUS", out, len(candidates)
                )
                continue
            s = candidates[0]
            if s.attendance_status == "finalized":
                await self._unmatched(device, ident, at, "FINALIZED", out, 1)
                continue
            existing = (await self.marks.marks(s)).get(enrolment.id)
            if existing is not None and existing.status in ("present", "late", "on_duty"):
                out.duplicates += 1
                continue
            start = datetime.combine(s.session_date, s.start_time, tzinfo=tz)
            late_after = int(await self.att_setting("qr_late_minutes", 10))
            status = "late" if at > start + timedelta(minutes=late_after) else "present"
            await self.marks.upsert_marks(
                s,
                [
                    {
                        "student_program_enrollment_id": enrolment.id,
                        "status": status,
                        "source": source,
                        "marked_by": None,
                        "remarks": None,
                    }
                ],
            )
            if s.attendance_status == "not_taken":
                s.status, s.attendance_status, s.attendance_taken_at = "conducted", "taken", now_utc()
            out.marked += 1
        await self.db.flush()
        return out

    async def _unmatched(
        self,
        device: AttendanceDevice,
        ident: str,
        at: datetime,
        reason: str,
        out: StudentPunchResult,
        candidates: int = 0,
    ) -> None:
        row = UnmatchedPunch(identifier=ident, at=at, reason=reason, device_id=device.id, candidates=candidates)
        out.unmatched.append(row)
        await self._audit("unmatched", PUNCH, device.id, None, json.loads(row.model_dump_json()))

    async def unmatched_punches(self, days: int = 30) -> list[UnmatchedPunch]:
        since = now_utc() - timedelta(days=days)
        rows = (
            await self.db.execute(
                select(AuditLog)
                .where(
                    AuditLog.institution_id == self.inst,
                    AuditLog.record_type == PUNCH,
                    AuditLog.action == "unmatched",
                    AuditLog.occurred_at >= since,
                )
                .order_by(AuditLog.occurred_at.desc())
                .limit(500)
            )
        ).scalars()
        return [UnmatchedPunch.model_validate(r.new_values or {}) for r in rows]

    # ---- 7. offline batch ------------------------------------------------------------------------------------------
    async def offline_batch(self, body: OfflineBatch) -> OfflineBatchResult:
        from app.db.session import redis_client

        key = f"att:offline:{self.inst}:{self.actor_id}:{body.idempotency_key}"
        try:
            stored = await redis_client.get(key)
        except Exception:  # noqa: BLE001 - Redis down: process without replay protection
            stored = None
        if stored:
            out = OfflineBatchResult.model_validate_json(stored)
            out.replayed = True
            return out
        out = OfflineBatchResult(idempotency_key=body.idempotency_key)
        for item in body.items:
            try:
                async with self.db.begin_nested():
                    s = await self.sessions.get_one(item.session_id, for_update=True)
                    await self.assert_mark(s)
                    await self.assert_markable(s)
                    res = await self._apply(
                        s, BulkMarkRequest.model_validate(item.model_dump(exclude={"client_id", "session_id"}))
                    )
                out.items.append(
                    OfflineItemResult(client_id=item.client_id, session_id=item.session_id, ok=True, result=res)
                )
            except APIError as exc:
                code = (exc.details or {}).get("code") or exc.code
                out.items.append(
                    OfflineItemResult(
                        client_id=item.client_id,
                        session_id=item.session_id,
                        ok=False,
                        code=str(code),
                        message=exc.message,
                    )
                )
        with contextlib.suppress(Exception):  # Redis down: no replay protection
            await redis_client.set(key, out.model_dump_json(), ex=24 * 3600)
        return out

    # ---- follow-up (Phase 10 Beat flags missed sessions) ------------------------------------------------------------
    async def missing_sessions(self, scope: str | None = None, days: int = 14) -> list[ClassSession]:
        """Past sessions still ``not_taken`` (Phase 10 ``sessions.mark_missed`` flags them ``conducted``)."""
        today = await self.today()
        stmt = self.sessions.filtered(scope, date_from=today - timedelta(days=days), date_to=today - timedelta(days=1))
        stmt = stmt.where(
            ClassSession.status.in_(("conducted", "scheduled")), ClassSession.attendance_status == "not_taken"
        )
        return list((await self.db.execute(stmt.order_by(ClassSession.session_date.desc()).limit(500))).scalars().all())

    async def missing_digest(self) -> int:
        """Daily: a HOD digest of past sessions without attendance per department + a reminder to each teacher."""
        from app.models.hr import Staff
        from app.models.offerings import CourseOffering

        today = await self.today()
        rows = (
            await self.db.execute(
                select(ClassSession, CourseOffering.department_id)
                .join(CourseOffering, CourseOffering.id == ClassSession.offering_id)
                .where(
                    ClassSession.institution_id == self.inst,
                    ClassSession.attendance_status == "not_taken",
                    ClassSession.status.in_(("conducted", "scheduled")),
                    ClassSession.session_date < today,
                    ClassSession.session_date >= today - timedelta(days=14),
                )
            )
        ).all()
        by_dept: dict[uuid.UUID, int] = defaultdict(int)
        by_staff: dict[uuid.UUID, int] = defaultdict(int)
        for s, dept in rows:
            by_dept[dept] += 1
            if s.staff_id:
                by_staff[s.staff_id] += 1
        for dept, n in by_dept.items():
            await self._notify("attendance.missing_sessions", await self.hod_user_ids(dept), {"count": n, "days": 14})
        if by_staff:
            staff = await self._rows(Staff, list(by_staff))
            for sid, n in by_staff.items():
                st = staff.get(sid)
                if st is not None and st.user_id:
                    await self._notify("attendance.missing_sessions", [st.user_id], {"count": n, "days": 14})
        return len(rows)


__all__ = ["MarkingService"]
