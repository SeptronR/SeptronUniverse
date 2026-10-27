"""Early-warning analytics (``analytics.early_warning``) — Prompts/35 §35.6 risk_analytics_service.

The scoring job stays in Phase 27 (``risk_service.compute`` → ``risk_flags``); this service reads it:

1. Cohorts over ``mv_risk_cohort`` (heat map by department / programme / batch / hostel / category × level, factor
   means, trend across terms) at department / college / institution scope; mentors (own scope) get the same cells from
   ``risk_flags`` restricted to their mentees / advisees. IQAC / auditor read aggregates only (no enrolment ids).
2. Student lists with filters (level, factor, unacknowledged, no intervention in N days) under the Phase 27 visibility
   (``MentoringService._owned_enrolment_predicate``: mentor → mentees / advisees, HOD → department, registrar → all).
3. Interventions are Phase 27 ``mentoring_sessions`` rows (``mode='intervention'``, ``concerns.items=[type]``) on the
   student's active mentor assignment, so the mentor timeline stays single-sourced; follow-up reminders; effectiveness
   (level change after the intervention within the term).
4. Alerts after each ``risk.computed``: department high share above ``risk.alert_threshold_pct`` → ``risk.cohort_alert``
   to HOD / registrar; ``high`` on two consecutive computations without an intervention within
   ``risk.intervention_due_days`` → ``risk.intervention_due`` to the mentor + HOD.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, text

from app.core.charts import ChartContext
from app.models.mentoring import MentorAssignment, MentoringSession, RiskFlag
from app.models.students import StudentProgramEnrollment
from app.services.analytics.common import AnalyticsBase, forbidden, not_found, now_utc, rule

__all__ = ["GROUP_COLUMNS", "RiskAnalyticsService"]

GROUP_COLUMNS: dict[str, tuple[str, str | None]] = {
    "department": ("department_id", "department"),
    "program": ("program_id", "program"),
    "batch": ("batch_id", "batch"),
    "hostel": ("hostel_id", "hostel"),
    "category": ("category", None),
}
FACTORS = ("attendance", "cia", "dues", "standing", "hostel", "engagement")
DEFAULT_TYPES = [
    "mentor_meeting",
    "guardian_call",
    "counselling",
    "fee_plan",
    "remedial_class",
    "hostel_warden",
    "other",
]


class RiskAnalyticsService(AnalyticsBase):
    module = "mentoring"
    audit_module = "mentoring"

    async def _mentoring(self) -> Any:
        from app.services.student_support.mentoring_service import MentoringService

        return MentoringService(self.db, self.principal, self.request, self.inst)

    def _require_view(self) -> None:
        if not (
            self.can("mentoring", "view_all") or self.can("mentoring", "manage") or self.can("accreditation", "view")
        ):
            raise forbidden("mentoring:view|view_all required")

    async def _term_id(self, term_id: uuid.UUID | None) -> uuid.UUID:
        return (await self.term_or_current(term_id)).id

    # ---- cohorts --------------------------------------------------------------------------------------------------------
    async def cohort(
        self, term_id: uuid.UUID | None, group_by: str, level: str | None, scope: str | None
    ) -> dict[str, Any]:
        self._require_view()
        if group_by not in GROUP_COLUMNS:
            raise rule("group_by must be department | program | batch | hostel | category", "BAD_GROUP", 422)
        tid = await self._term_id(term_id)
        resolved = await self.resolve_scope("mentoring", scope)
        col, kind = GROUP_COLUMNS[group_by]
        ctx = ChartContext(db=self.db, institution_id=self.inst, scope=resolved, dims={"term_id": tid}, service=self)
        if resolved.level == "self":
            rows = await self._own_cells(tid, col, level, resolved.enrollment_ids)
        else:
            pred, binds = ctx.where(
                alias="x",
                college="college_id",
                department="department_id",
                program="program_id",
                batch="batch_id",
                term="term_id",
                hostel="hostel_id",
            )
            lvl = " AND x.level = :lvl" if level else ""
            if level:
                binds["lvl"] = level
            sql = (
                f"SELECT x.{col} AS grp, x.level, SUM(x.students) AS n, SUM(x.acknowledged) AS ack, "
                + ", ".join(f"SUM(x.{f}_mean * x.students) AS {f}_w" for f in FACTORS)
                + f" FROM mv_risk_cohort x WHERE {pred}{lvl} GROUP BY 1, 2"
            )
            rows = [dict(r) for r in (await self.db.execute(text(sql), binds)).mappings().all()]
        cells: dict[Any, dict[str, Any]] = {}
        sums: dict[str, float] = dict.fromkeys(FACTORS, 0.0)
        total_n = 0.0
        for r in rows:
            c = cells.setdefault(
                r["grp"], {"group_id": r["grp"], "low": 0, "medium": 0, "high": 0, "total": 0, "_ack": 0}
            )
            n = int(r["n"] or 0)
            c[str(r["level"])] = c.get(str(r["level"]), 0) + n
            c["total"] += n
            c["_ack"] += int(r["ack"] or 0)
            total_n += n
            for f in FACTORS:
                sums[f] += float(r.get(f"{f}_w") or 0)
        names = await self._names(kind, [k for k in cells if k is not None])
        out_cells = []
        for k, c in cells.items():
            out_cells.append(
                {
                    "group": names.get(k, str(k) if k not in (None, "") else "—"),
                    "group_id": str(k) if isinstance(k, uuid.UUID) else k,
                    "low": c["low"],
                    "medium": c["medium"],
                    "high": c["high"],
                    "total": c["total"],
                    "acknowledged_pct": round(100.0 * c["_ack"] / c["total"], 2) if c["total"] else 0.0,
                }
            )
        return {
            "term_id": tid,
            "group_by": group_by,
            "scope": resolved.level,
            "cells": sorted(out_cells, key=lambda c: -c["high"]),
            "factor_means": {f: round(sums[f] / total_n, 3) if total_n else None for f in FACTORS},
            "trend": (await self.trend(scope))["points"],
            "aggregates_only": resolved.aggregates_only,
        }

    async def _own_cells(
        self, tid: uuid.UUID, col: str, level: str | None, enrols: list[uuid.UUID]
    ) -> list[dict[str, Any]]:
        if not enrols:
            return []
        src = {
            "department_id": "e.department_id",
            "program_id": "e.program_id",
            "batch_id": "e.batch_id",
            "hostel_id": "NULL::uuid",
            "category": "s.category",
        }[col]
        binds: dict[str, Any] = {"i": self.inst, "t": tid, "e": enrols}
        lvl = ""
        if level:
            lvl, binds["lvl"] = " AND f.level = :lvl", level
        sql = (
            f"SELECT {src} AS grp, f.level, COUNT(*) AS n, COUNT(*) FILTER (WHERE f.acknowledged_at IS NOT NULL) AS ack, "
            + ", ".join(f"SUM((f.factors -> '{x}' ->> 'value')::numeric) AS {x}_w" for x in FACTORS)
            + " FROM risk_flags f JOIN student_program_enrollments e ON e.id = f.student_program_enrollment_id "
            "JOIN students s ON s.id = e.student_id WHERE f.institution_id = :i AND f.term_id = :t "
            f"AND f.student_program_enrollment_id = ANY(:e){lvl} GROUP BY 1, 2"
        )
        return [dict(r) for r in (await self.db.execute(text(sql), binds)).mappings().all()]

    async def _names(self, kind: str | None, ids: list[Any]) -> dict[Any, str]:
        from app.services.analytics.chart_helpers import _LOOKUPS

        uids = [i for i in ids if isinstance(i, uuid.UUID)]
        if not kind or not uids:
            return {}
        res = await self.db.execute(text(_LOOKUPS[kind]), {"ids": uids})
        return {a: str(b) for a, b in res.all()}

    async def trend(self, scope: str | None) -> dict[str, Any]:
        self._require_view()
        resolved = await self.resolve_scope("mentoring", scope)
        if resolved.level == "self":
            if not resolved.enrollment_ids:
                return {"periods": [], "counts_by_level": {}, "points": []}
            rows = (
                (
                    await self.db.execute(
                        text(
                            "SELECT t.name AS period, t.start_date, f.level, COUNT(*) AS n FROM risk_flags f JOIN academic_terms t "
                            "ON t.id = f.term_id WHERE f.institution_id = :i AND f.student_program_enrollment_id = ANY(:e) "
                            "GROUP BY 1, 2, 3 ORDER BY 2"
                        ),
                        {"i": self.inst, "e": resolved.enrollment_ids},
                    )
                )
                .mappings()
                .all()
            )
        else:
            ctx = ChartContext(db=self.db, institution_id=self.inst, scope=resolved, service=self)
            pred, binds = ctx.where(
                alias="x",
                college="college_id",
                department="department_id",
                program="program_id",
                batch="batch_id",
                term=None,
                hostel="hostel_id",
            )
            rows = (
                (
                    await self.db.execute(
                        text(
                            "SELECT t.name AS period, t.start_date, x.level, SUM(x.students) AS n FROM mv_risk_cohort x "
                            f"JOIN academic_terms t ON t.id = x.term_id WHERE {pred} GROUP BY 1, 2, 3 ORDER BY 2"
                        ),
                        binds,
                    )
                )
                .mappings()
                .all()
            )
        periods: list[str] = []
        counts: dict[str, list[int]] = {"low": [], "medium": [], "high": []}
        by_period: dict[str, dict[str, int]] = {}
        for r in rows:
            p = str(r["period"])
            if p not in periods:
                periods.append(p)
            by_period.setdefault(p, {})[str(r["level"])] = int(r["n"] or 0)
        for p in periods:
            for lv in counts:
                counts[lv].append(by_period[p].get(lv, 0))
        points = [{"label": p, **by_period[p]} for p in periods]
        return {"periods": periods, "counts_by_level": counts, "points": points}

    # ---- student lists ------------------------------------------------------------------------------------------------
    async def student_list(
        self,
        *,
        term_id: uuid.UUID | None,
        level: str | None,
        department_id: uuid.UUID | None = None,
        program_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
        factor: str | None = None,
        unacknowledged: bool | None = None,
        no_intervention_days: int | None = None,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.is_student() or self.is_parent():
            raise forbidden("mentoring:manage|view_all required")
        tid = await self._term_id(term_id)
        ment = await self._mentoring()
        pred = await ment._owned_enrolment_predicate(RiskFlag.student_program_enrollment_id, scope)
        if pred is None:
            raise forbidden("mentoring:manage required")
        stmt = (
            select(RiskFlag, StudentProgramEnrollment)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.id == RiskFlag.student_program_enrollment_id)
            .where(RiskFlag.institution_id == self.inst, RiskFlag.term_id == tid, pred)
        )
        if level:
            stmt = stmt.where(RiskFlag.level == level)
        for col, v in (
            (StudentProgramEnrollment.department_id, department_id),
            (StudentProgramEnrollment.program_id, program_id),
            (StudentProgramEnrollment.batch_id, batch_id),
        ):
            if v:
                stmt = stmt.where(col == v)
        if unacknowledged:
            stmt = stmt.where(RiskFlag.acknowledged_at.is_(None))
        rows = (await self.db.execute(stmt.order_by(RiskFlag.score.desc()).limit(1000))).all()
        enrols = [f.student_program_enrollment_id for f, _ in rows]
        last = await self._last_interventions(enrols)
        mentors = await self._mentors(enrols)
        cards = await self.enrollment_cards(enrols)
        staff = await self.staff_cards(list(mentors.values()))
        agg = self.aggregates_only("mentoring")
        out = []
        cutoff = date.today() - timedelta(days=no_intervention_days) if no_intervention_days else None
        for f, e in rows:
            factors = f.factors or {}
            if factor and float((factors.get(factor) or {}).get("value") or 0) < 0.5:
                continue
            li = last.get(f.student_program_enrollment_id)
            if cutoff and li and li["held_on"] >= cutoff:
                continue
            card = cards.get(f.student_program_enrollment_id, {})
            out.append(
                {
                    "enrollment_id": None if agg else f.student_program_enrollment_id,
                    "student_name": None if agg else card.get("name"),
                    "registration_number": None if agg else card.get("registration_number"),
                    "department_id": e.department_id,
                    "program_id": e.program_id,
                    "batch_id": e.batch_id,
                    "score": float(f.score),
                    "level": f.level,
                    "factors": factors,
                    "mentor": (staff.get(mentors[f.student_program_enrollment_id]) or {}).get("name")
                    if f.student_program_enrollment_id in mentors
                    else None,
                    "mentor_staff_id": mentors.get(f.student_program_enrollment_id),
                    "last_intervention": li,
                    "acknowledged": f.acknowledged_at is not None,
                }
            )
        return out

    async def _mentors(self, enrols: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        if not enrols:
            return {}
        rows = await self.db.execute(
            select(MentorAssignment.student_program_enrollment_id, MentorAssignment.mentor_staff_id).where(
                MentorAssignment.student_program_enrollment_id.in_(enrols), MentorAssignment.status == "active"
            )
        )
        return dict(rows.tuples().all())

    async def _last_interventions(self, enrols: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        if not enrols:
            return {}
        rows = (
            await self.db.execute(
                select(MentorAssignment.student_program_enrollment_id, MentoringSession)
                .join(MentoringSession, MentoringSession.mentor_assignment_id == MentorAssignment.id)
                .where(
                    MentorAssignment.student_program_enrollment_id.in_(enrols), MentoringSession.mode == "intervention"
                )
                .order_by(MentoringSession.held_on.desc())
            )
        ).all()
        out: dict[uuid.UUID, dict[str, Any]] = {}
        for eid, s in rows:
            if eid in out:
                continue
            c = s.concerns or {}
            out[eid] = {
                "id": s.id,
                "held_on": s.held_on,
                "intervention_type": c.get("intervention_type") or ((c.get("items") or [None])[0]),
                "follow_up_on": s.follow_up_on,
            }
        return out

    # ---- interventions ------------------------------------------------------------------------------------------------
    async def log_intervention(
        self, enrollment_id: uuid.UUID, intervention_type: str, notes: str | None, follow_up_on: date | None
    ) -> dict[str, Any]:
        self.require_writer()
        if not self.can("mentoring", "manage"):
            raise forbidden("mentoring:manage required")
        types = await self.a_setting("risk", "intervention_types", DEFAULT_TYPES)
        if intervention_type not in (types or DEFAULT_TYPES):
            raise rule("Unknown intervention type", "BAD_INTERVENTION_TYPE", 422, allowed=types)
        ment = await self._mentoring()
        if await ment._can_see_enrolment(enrollment_id) is None:
            raise not_found("Student")
        a = (
            (
                await self.db.execute(
                    select(MentorAssignment)
                    .where(
                        MentorAssignment.institution_id == self.inst,
                        MentorAssignment.student_program_enrollment_id == enrollment_id,
                        MentorAssignment.status == "active",
                    )
                    .order_by(MentorAssignment.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        if a is None:
            raise rule("The student has no active mentor assignment", "NO_MENTOR")
        flag = (
            (
                await self.db.execute(
                    select(RiskFlag)
                    .where(RiskFlag.student_program_enrollment_id == enrollment_id)
                    .order_by(RiskFlag.computed_at.desc())
                )
            )
            .scalars()
            .first()
        )
        s = MentoringSession(
            institution_id=self.inst,
            mentor_assignment_id=a.id,
            held_on=date.today(),
            mode="intervention",
            notes=notes,
            concerns={
                "items": [intervention_type],
                "intervention_type": intervention_type,
                "logged_by": str(self.actor_id) if self.actor_id else None,
                "risk_level": flag.level if flag else None,
                "risk_flag_id": str(flag.id) if flag else None,
            },
            action_items=[],
            follow_up_on=follow_up_on,
            is_confidential=False,
        )
        self.db.add(s)
        await self.db.flush()
        await self._emit(
            "risk.intervention_logged",
            {"enrollment_id": str(enrollment_id), "session_id": str(s.id), "intervention_type": intervention_type},
            "mentoring_session",
            s.id,
        )
        return self._intervention_out(s, enrollment_id)

    def _intervention_out(self, s: MentoringSession, enrollment_id: uuid.UUID) -> dict[str, Any]:
        c = s.concerns or {}
        return {
            "id": s.id,
            "enrollment_id": enrollment_id,
            "intervention_type": c.get("intervention_type"),
            "notes": s.notes,
            "held_on": s.held_on,
            "follow_up_on": s.follow_up_on,
            "logged_by": c.get("logged_by"),
            "risk_level_at_log": c.get("risk_level"),
        }

    async def interventions(self, enrollment_id: uuid.UUID) -> list[dict[str, Any]]:
        ment = await self._mentoring()
        if await ment._can_see_enrolment(enrollment_id) is None:
            raise not_found("Student")
        rows = (
            (
                await self.db.execute(
                    select(MentoringSession)
                    .join(MentorAssignment, MentorAssignment.id == MentoringSession.mentor_assignment_id)
                    .where(
                        MentorAssignment.student_program_enrollment_id == enrollment_id,
                        MentoringSession.mode == "intervention",
                    )
                    .order_by(MentoringSession.held_on.desc())
                )
            )
            .scalars()
            .all()
        )
        return [self._intervention_out(s, enrollment_id) for s in rows]

    async def effectiveness(self, term_id: uuid.UUID | None, scope: str | None) -> dict[str, Any]:
        """Level now vs level at the time of the intervention (within the term), per intervention type."""
        self._require_view()
        tid = await self._term_id(term_id)
        ment = await self._mentoring()
        pred = await ment._owned_enrolment_predicate(RiskFlag.student_program_enrollment_id, scope)
        if pred is None:
            raise forbidden("mentoring:manage required")
        rows = (
            await self.db.execute(
                select(MentoringSession.concerns, RiskFlag.level)
                .join(MentorAssignment, MentorAssignment.id == MentoringSession.mentor_assignment_id)
                .join(
                    RiskFlag,
                    (RiskFlag.student_program_enrollment_id == MentorAssignment.student_program_enrollment_id)
                    & (RiskFlag.term_id == tid),
                )
                .where(MentoringSession.mode == "intervention", RiskFlag.institution_id == self.inst, pred)
            )
        ).all()
        rank = {"low": 0, "medium": 1, "high": 2}
        stats: dict[str, dict[str, int]] = {}
        for concerns, now_level in rows:
            c = concerns or {}
            t = str(c.get("intervention_type") or "other")
            was = c.get("risk_level")
            s = stats.setdefault(t, {"improved": 0, "same": 0, "worse": 0, "total": 0})
            s["total"] += 1
            if was in rank and now_level in rank:
                d = rank[now_level] - rank[was]
                s["improved" if d < 0 else "worse" if d > 0 else "same"] += 1
            else:
                s["same"] += 1
        return {"term_id": tid, "by_type": stats}

    # ---- alerts (after risk.computed) / reminders ---------------------------------------------------------------------------
    async def after_compute(self, term_id: uuid.UUID) -> dict[str, int]:
        threshold = float(await self.a_setting("risk", "alert_threshold_pct", 15))
        due_days = int(await self.a_setting("risk", "intervention_due_days", 14))
        term_name = await self.term_label(term_id)
        rows = (
            await self.db.execute(
                select(StudentProgramEnrollment.department_id, RiskFlag.level, func.count())
                .join(StudentProgramEnrollment, StudentProgramEnrollment.id == RiskFlag.student_program_enrollment_id)
                .where(RiskFlag.institution_id == self.inst, RiskFlag.term_id == term_id)
                .group_by(StudentProgramEnrollment.department_id, RiskFlag.level)
            )
        ).all()
        per: dict[Any, dict[str, int]] = {}
        for dep, lv, n in rows:
            per.setdefault(dep, {})[lv] = int(n)
        codes = await self.department_codes([d for d in per if d])
        alerts = 0
        for dep, counts in per.items():
            total = sum(counts.values())
            high = counts.get("high", 0)
            pct = round(100.0 * high / total, 2) if total else 0.0
            key = f"{term_id}:{dep}"
            prev = await self.meta("cohort_alert", key)
            if pct > threshold and not prev.get("open"):
                users = await self.role_users("hod", dep) + await self.role_users("registrar")
                await self._notify(
                    "risk.cohort_alert",
                    users,
                    {
                        "department": codes.get(dep, "—"),
                        "high": high,
                        "total": total,
                        "high_pct": pct,
                        "threshold": threshold,
                        "term": term_name,
                    },
                )
                await self._emit(
                    "risk.cohort_alert",
                    {"department_id": str(dep) if dep else None, "term_id": str(term_id), "high_pct": pct},
                    "academic_term",
                    term_id,
                )
                await self.put_meta("cohort_alert", key, {"open": True, "pct": pct, "at": now_utc().isoformat()})
                alerts += 1
            elif pct <= threshold and prev.get("open"):
                await self.put_meta("cohort_alert", key, {"open": False, "pct": pct, "at": now_utc().isoformat()})
        due = await self._intervention_due(term_id, due_days)
        return {"cohort_alerts": alerts, "intervention_due": due}

    async def _intervention_due(self, term_id: uuid.UUID, days: int) -> int:
        """Students ``high`` on two consecutive computations with no intervention within ``days`` → mentor + HOD."""
        highs = (
            (
                await self.db.execute(
                    select(RiskFlag).where(
                        RiskFlag.institution_id == self.inst, RiskFlag.term_id == term_id, RiskFlag.level == "high"
                    )
                )
            )
            .scalars()
            .all()
        )
        if not highs:
            return 0
        enrols = [f.student_program_enrollment_id for f in highs]
        last = await self._last_interventions(enrols)
        mentors = await self._mentors(enrols)
        cards = await self.enrollment_cards(enrols)
        cutoff = date.today() - timedelta(days=days)
        sent = 0
        for f in highs:
            eid = f.student_program_enrollment_id
            m = await self.meta("risk_streak", eid)
            streak = int(m.get("high_streak") or 0) + 1
            await self.put_meta("risk_streak", eid, {"high_streak": streak, "last": now_utc().isoformat()})
            li = last.get(eid)
            if streak < 2 or (li and li["held_on"] >= cutoff):
                continue
            reminded = await self.meta("intervention_alert", eid)
            if reminded.get("on") and date.fromisoformat(reminded["on"]) >= cutoff:
                continue
            card = cards.get(eid, {})
            users = [await self.staff_user(mentors.get(eid))] + await self.role_users("hod", card.get("department_id"))
            await self._notify("risk.intervention_due", users, {"student": card.get("name") or "", "days": days})
            await self._emit(
                "risk.intervention_due",
                {"enrollment_id": str(eid), "term_id": str(term_id)},
                "student_program_enrollment",
                eid,
            )
            await self.put_meta("intervention_alert", eid, {"on": date.today().isoformat()})
            sent += 1
        # students who left ``high`` restart their streak
        for r in (
            await self.db.execute(
                select(RiskFlag.student_program_enrollment_id).where(
                    RiskFlag.institution_id == self.inst, RiskFlag.term_id == term_id, RiskFlag.level != "high"
                )
            )
        ).all():
            m = await self.meta("risk_streak", r[0])
            if m.get("high_streak"):
                await self.put_meta("risk_streak", r[0], {"high_streak": 0, "last": now_utc().isoformat()})
        return sent

    async def follow_up_reminders(self) -> int:
        """Beat ``risk.intervention_reminders``: interventions whose follow-up date is today → the mentor."""
        rows = (
            await self.db.execute(
                select(MentoringSession, MentorAssignment)
                .join(MentorAssignment, MentorAssignment.id == MentoringSession.mentor_assignment_id)
                .where(
                    MentoringSession.institution_id == self.inst,
                    MentoringSession.mode == "intervention",
                    MentoringSession.follow_up_on == date.today(),
                )
            )
        ).all()
        n = 0
        cards = await self.enrollment_cards([a.student_program_enrollment_id for _, a in rows])
        for _s, a in rows:
            card = cards.get(a.student_program_enrollment_id, {})
            await self._notify(
                "risk.intervention_due",
                [await self.staff_user(a.mentor_staff_id)],
                {"student": card.get("name") or "", "days": 0},
            )
            n += 1
        return n

    async def export_rows(self, term_id: uuid.UUID | None, kind: str, scope: str | None) -> list[dict[str, Any]]:
        """``cohort`` (aggregates) | ``students`` (PII masked unless ``students:view_pii``) | ``iqac`` (aggregates only)."""
        if kind in ("cohort", "iqac"):
            c = await self.cohort(term_id, "department", None, scope)
            return [{k: v for k, v in cell.items() if k != "group_id"} for cell in c["cells"]]
        rows = await self.student_list(term_id=term_id, level=None, scope=scope)
        if not self.can("students", "view_pii"):
            for r in rows:
                if r.get("student_name"):
                    r["student_name"] = str(r["student_name"])[:1] + "•••"
        return [{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in r.items() if k != "factors"} for r in rows]
