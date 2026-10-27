"""Exam audit views — Prompts/37 §37.6 ``exam_audit_service`` (``exams:audit``; {exams.sessions}).

Per exam session, nine sections assembled from the exam tables plus ``audit_logs`` (read-only, never recomputed):

* ``marks`` — CIA assessments of the session's term (submitted / verified / locked with actors) and
  ``marks_change_requests`` decisions on their marks;
* ``qp_print`` — ``question_paper_print_log`` (who / when / copies / watermark / IP);
* ``custody`` — ``script_custody_log`` per bundle in time order; a step whose predecessor is missing (received without
  dispatch, handed over before receipt …) and a hand-over whose ``from`` is not the previous ``to`` are **gaps**;
* ``valuation`` — ``valuation_assignments`` (rounds, reassignments) and ``script_valuations`` submits (evaluators by
  dummy number only — never the student);
* ``moderation`` — ``moderation_actions`` with proposer / approver / affected count;
* ``decode`` — ``audit_logs`` decode rows with IP and whether the IP matched an ``exam_decode`` allow-list CIDR — COE
  (``exams:decode``), institution admin and auditor only (403 otherwise, e.g. the exam cell);
* ``runs`` — ``result_processing_runs`` with the ``config_snapshot`` hash and anomaly counts;
* ``publication`` — ``result_publications`` and result version chains (``supersedes_id``);
* ``post_result`` — ``reval_requests`` and ``malpractice_cases`` decisions.

The export is the Phase 36 registered report ``exams.audit_trail`` (``report.run``, PDF by default) — one section per
sheet / page — so peer teams and auditors get the same rendering and the run shows in the reports access log.
"""

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text

from app.core.jobs import enqueue
from app.enums.audit import CUSTODY_ORDER, DECODE_ACTIONS, EXAM_AUDIT_SECTIONS
from app.schemas.audit import AuditUser, ExamAuditEntry, ExamAuditOut, ExamAuditSummaryOut, JobQueuedOut
from app.services.audit.common import AuditBase, forbidden, mask_ip24, not_found, rule


class ExamAuditService(AuditBase):
    audit_module = "exams"

    def require_audit(self) -> None:
        self.require("exams:audit", "exams:manage")

    async def session(self, sid: uuid.UUID) -> dict[str, Any]:
        row = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, name, term_id, college_id, start_date, end_date, status FROM exam_sessions "
                        "WHERE id = :s AND institution_id = :i"
                    ),
                    {"s": sid, "i": self.inst},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise not_found("Exam session")
        p = self.principal
        colleges = [c for t, c in getattr(p, "scopes", []) if t == "college" and c]
        if colleges and not self.institution_wide() and row["college_id"] not in colleges:
            raise not_found("Exam session")
        return dict(row)

    async def _q(self, sql: str, **binds: Any) -> list[dict[str, Any]]:
        return [dict(r) for r in (await self.db.execute(text(sql), {"i": self.inst, **binds})).mappings().all()]

    async def _names(self, rows: list[dict[str, Any]], *cols: str) -> dict[uuid.UUID, str]:
        ids = [r.get(c) for r in rows for c in cols if r.get(c)]
        return await self.user_refs(ids)

    async def _staff_names(self, ids: list[Any]) -> dict[uuid.UUID, str]:
        wanted = [i for i in ids if i]
        if not wanted:
            return {}
        rows = await self._q(
            "SELECT id, concat_ws(' ', first_name, last_name) AS name FROM staff WHERE id = ANY(:ids)", ids=wanted
        )
        return {r["id"]: r["name"] for r in rows}

    @staticmethod
    def _who(uid: Any, names: dict[uuid.UUID, str]) -> AuditUser | None:
        return AuditUser(id=uid, name=names.get(uid)) if uid else None

    # ---- sections ---------------------------------------------------------------------------------------------------
    async def section(self, sid: uuid.UUID, section: str, paper_id: uuid.UUID | None = None) -> ExamAuditOut:
        self.require_audit()
        if section not in EXAM_AUDIT_SECTIONS:
            raise rule(f"Unknown section {section}", "UNKNOWN_SECTION", 422)
        if section == "decode" and not self.sees_decode():
            raise forbidden("Decode events are visible to the COE, institution admins and auditors only")
        s = await self.session(sid)
        fn = getattr(self, f"_s_{section}")
        entries, summary = await fn(s, paper_id)
        return ExamAuditOut(exam_session_id=sid, section=section, entries=entries, summary=summary)

    def _paper_filter(self, alias: str, paper_id: uuid.UUID | None) -> str:
        return f" AND {alias}.exam_paper_id = :p" if paper_id else ""

    async def _s_marks(
        self, s: dict[str, Any], paper_id: uuid.UUID | None
    ) -> tuple[list[ExamAuditEntry], dict[str, Any]]:
        rows = await self._q(
            "SELECT a.id, a.name, a.status, a.submitted_by, a.submitted_at, a.verified_by, a.verified_at, a.locked_by, "
            "a.locked_at, c.code AS course FROM offering_assessments a JOIN course_offerings o ON o.id = a.offering_id "
            "JOIN courses c ON c.id = o.course_id WHERE a.institution_id = :i AND o.term_id = :t ORDER BY c.code, a.name",
            t=s["term_id"],
        )
        changes = await self._q(
            "SELECT m.id, m.target_type, m.status, m.reason, m.requested_by, m.approved_by, m.created_at, m.applied_at, "
            "m.old_value, m.new_value FROM marks_change_requests m WHERE m.institution_id = :i AND ("
            "(m.target_type = 'internal_mark' AND m.target_id IN (SELECT im.id FROM internal_marks im JOIN "
            "offering_assessments a ON a.id = im.offering_assessment_id JOIN course_offerings o ON o.id = a.offering_id "
            "WHERE o.term_id = :t)) OR (m.target_type = 'course_result' AND m.target_id IN (SELECT r.id FROM "
            "student_course_results r WHERE r.exam_session_id = :s))) ORDER BY m.created_at",
            t=s["term_id"],
            s=s["id"],
        )
        names = await self._names(
            rows + changes, "submitted_by", "verified_by", "locked_by", "requested_by", "approved_by"
        )
        out: list[ExamAuditEntry] = []
        for r in rows:
            for step, by, at in (
                ("submitted", "submitted_by", "submitted_at"),
                ("verified", "verified_by", "verified_at"),
                ("locked", "locked_by", "locked_at"),
            ):
                if r.get(at):
                    out.append(
                        ExamAuditEntry(
                            at=r[at],
                            actor=self._who(r[by], names),
                            action=f"marks_{step}",
                            subject=f"{r['course']} · {r['name']}",
                        )
                    )
        for c in changes:
            out.append(
                ExamAuditEntry(
                    at=c["applied_at"] or c["created_at"],
                    actor=self._who(c["approved_by"] or c["requested_by"], names),
                    action=f"change_request_{c['status']}",
                    subject=c["target_type"],
                    details={
                        "reason": c["reason"],
                        "old": c["old_value"],
                        "new": c["new_value"],
                        "requested_by": str(c["requested_by"]),
                    },
                )
            )
        out.sort(key=lambda e: str(e.at))
        locked = sum(1 for r in rows if r["status"] == "locked")
        return out, {
            "assessments": len(rows),
            "locked": locked,
            "unlocked": len(rows) - locked,
            "change_requests": len(changes),
        }

    async def _s_qp_print(
        self, s: dict[str, Any], paper_id: uuid.UUID | None
    ) -> tuple[list[ExamAuditEntry], dict[str, Any]]:
        rows = await self._q(
            "SELECT l.printed_by, l.printed_at, l.copies, l.set_label, l.watermark_text, l.ip, p.paper_code FROM "
            "question_paper_print_log l JOIN exam_papers p ON p.id = l.exam_paper_id WHERE l.institution_id = :i AND "
            f"p.exam_session_id = :s{self._paper_filter('l', paper_id)} ORDER BY l.printed_at",
            s=s["id"],
            **({"p": paper_id} if paper_id else {}),
        )
        names = await self._names(rows, "printed_by")
        out = [
            ExamAuditEntry(
                at=r["printed_at"],
                actor=self._who(r["printed_by"], names),
                action="qp_printed",
                subject=f"{r['paper_code']} set {r['set_label']}",
                details={"copies": r["copies"], "watermark": r["watermark_text"]},
                ip_masked=mask_ip24(r["ip"]),
            )
            for r in rows
        ]
        return out, {"prints": len(rows), "copies": sum(int(r["copies"] or 0) for r in rows)}

    async def _s_custody(
        self, s: dict[str, Any], paper_id: uuid.UUID | None
    ) -> tuple[list[ExamAuditEntry], dict[str, Any]]:
        rows = await self._q(
            "SELECT c.bundle_id, b.bundle_number, c.action, c.from_staff_id, c.to_staff_id, c.at, c.location, c.remarks "
            "FROM script_custody_log c JOIN answer_script_bundles b ON b.id = c.bundle_id JOIN exam_papers p ON "
            f"p.id = b.exam_paper_id WHERE c.institution_id = :i AND p.exam_session_id = :s"
            f"{' AND b.exam_paper_id = :p' if paper_id else ''} ORDER BY c.bundle_id, c.at",
            s=s["id"],
            **({"p": paper_id} if paper_id else {}),
        )
        staff = await self._staff_names([r["from_staff_id"] for r in rows] + [r["to_staff_id"] for r in rows])
        out: list[ExamAuditEntry] = []
        gaps = 0
        last: dict[Any, dict[str, Any]] = {}
        for r in rows:
            prev = last.get(r["bundle_id"])
            gap = False
            idx = CUSTODY_ORDER.index(r["action"]) if r["action"] in CUSTODY_ORDER else -1
            if prev is None:
                gap = r["action"] != "created"
            else:
                pidx = CUSTODY_ORDER.index(prev["action"]) if prev["action"] in CUSTODY_ORDER else -1
                if (
                    r["action"] == "received"
                    and prev["action"] not in ("dispatched", "handed_over", "returned")
                    or r["action"] == "handed_over"
                    and prev.get("to_staff_id")
                    and r["from_staff_id"]
                    and r["from_staff_id"] != prev["to_staff_id"]
                    or idx >= 0
                    and pidx >= 0
                    and idx < pidx
                    and r["action"] not in ("handed_over", "returned", "received", "dispatched")
                ):
                    gap = True
            gaps += int(gap)
            last[r["bundle_id"]] = r
            out.append(
                ExamAuditEntry(
                    at=r["at"],
                    actor=AuditUser(id=r["to_staff_id"], name=staff.get(r["to_staff_id"]))
                    if r["to_staff_id"]
                    else None,
                    action=r["action"],
                    subject=f"bundle {r['bundle_number']}",
                    details={
                        "from": staff.get(r["from_staff_id"]),
                        "to": staff.get(r["to_staff_id"]),
                        "location": r["location"],
                        "remarks": r["remarks"],
                    },
                    gap=gap,
                )
            )
        return out, {"bundles": len(last), "steps": len(rows), "gaps": gaps}

    async def _s_valuation(
        self, s: dict[str, Any], paper_id: uuid.UUID | None
    ) -> tuple[list[ExamAuditEntry], dict[str, Any]]:
        assigns = await self._q(
            "SELECT va.id, va.valuation_round, va.status, va.assigned_at, va.submitted_at, va.evaluator_user_id, "
            "va.evaluator_type, b.bundle_number, p.paper_code FROM valuation_assignments va JOIN answer_script_bundles b "
            "ON b.id = va.bundle_id JOIN exam_papers p ON p.id = va.exam_paper_id WHERE va.institution_id = :i AND "
            f"p.exam_session_id = :s{self._paper_filter('va', paper_id)} ORDER BY va.assigned_at",
            s=s["id"],
            **({"p": paper_id} if paper_id else {}),
        )
        vals = await self._q(
            "SELECT sv.valuation_round, sv.evaluator_user_id, sv.marks, sv.submitted_at, a.dummy_number, a.status "
            "FROM script_valuations sv JOIN answer_scripts a ON a.id = sv.answer_script_id JOIN answer_script_bundles b "
            "ON b.id = a.bundle_id JOIN exam_papers p ON p.id = b.exam_paper_id WHERE sv.institution_id = :i AND "
            f"p.exam_session_id = :s{' AND b.exam_paper_id = :p' if paper_id else ''} ORDER BY sv.submitted_at LIMIT 2000",
            s=s["id"],
            **({"p": paper_id} if paper_id else {}),
        )
        names = await self._names(assigns + vals, "evaluator_user_id")
        out = [
            ExamAuditEntry(
                at=a["assigned_at"],
                actor=self._who(a["evaluator_user_id"], names),
                action=f"assigned_round_{a['valuation_round']}",
                subject=f"{a['paper_code']} bundle {a['bundle_number']}",
                details={"status": a["status"], "type": a["evaluator_type"], "submitted_at": a["submitted_at"]},
            )
            for a in assigns
        ]
        out += [
            ExamAuditEntry(
                at=v["submitted_at"],
                actor=self._who(v["evaluator_user_id"], names),
                action=f"valuation_round_{v['valuation_round']}",
                subject=f"script {v['dummy_number']}",
                details={"marks": float(v["marks"]) if v["marks"] is not None else None, "script_status": v["status"]},
            )
            for v in vals
        ]
        out.sort(key=lambda e: str(e.at))
        discrepancies = sum(1 for v in vals if v["status"] in ("discrepancy", "third_valuation"))
        return out, {"assignments": len(assigns), "valuations": len(vals), "discrepancies": discrepancies}

    async def _s_moderation(
        self, s: dict[str, Any], paper_id: uuid.UUID | None
    ) -> tuple[list[ExamAuditEntry], dict[str, Any]]:
        rows = await self._q(
            "SELECT m.action_type, m.rule, m.justification, m.proposed_by, m.approved_by, m.affected_count, m.status, "
            "m.created_at, m.updated_at, p.paper_code FROM moderation_actions m JOIN exam_papers p ON p.id = m.exam_paper_id "
            f"WHERE m.institution_id = :i AND p.exam_session_id = :s{self._paper_filter('m', paper_id)} ORDER BY m.created_at",
            s=s["id"],
            **({"p": paper_id} if paper_id else {}),
        )
        names = await self._names(rows, "proposed_by", "approved_by")
        out = [
            ExamAuditEntry(
                at=r["updated_at"] or r["created_at"],
                actor=self._who(r["approved_by"] or r["proposed_by"], names),
                action=f"moderation_{r['status']}",
                subject=f"{r['paper_code']} · {r['action_type']}",
                details={
                    "rule": r["rule"],
                    "justification": r["justification"],
                    "affected": r["affected_count"],
                    "proposed_by": names.get(r["proposed_by"]),
                },
            )
            for r in rows
        ]
        grace = await self._q(
            "SELECT COUNT(*) AS n FROM student_course_results WHERE institution_id = :i AND exam_session_id = :s AND grace_marks > 0",
            s=s["id"],
        )
        return out, {"actions": len(rows), "grace_awards": int(grace[0]["n"]) if grace else 0}

    async def _s_decode(
        self, s: dict[str, Any], paper_id: uuid.UUID | None
    ) -> tuple[list[ExamAuditEntry], dict[str, Any]]:
        papers = [r["id"] for r in await self._q("SELECT id FROM exam_papers WHERE exam_session_id = :s", s=s["id"])]
        rows = await self._q(
            "SELECT l.id, l.user_id, l.occurred_at, l.ip, l.record_id, l.new_values, EXISTS (SELECT 1 FROM ip_allowlists w "
            "WHERE w.institution_id = l.institution_id AND w.purpose = 'exam_decode' AND w.is_active AND l.ip <<= w.cidr) "
            "AS allowlisted FROM audit_logs l WHERE l.institution_id = :i AND l.action = ANY(:acts) AND "
            "(l.record_id = ANY(:papers) OR l.record_id = :s) ORDER BY l.occurred_at",
            acts=list(DECODE_ACTIONS),
            papers=[paper_id] if paper_id else papers or [uuid.uuid4()],
            s=s["id"],
        )
        names = await self._names(rows, "user_id")
        out = [
            ExamAuditEntry(
                at=r["occurred_at"],
                actor=self._who(r["user_id"], names),
                action="decode",
                subject=str(r["record_id"]),
                details={**dict(r["new_values"] or {}), "allowlist_match": bool(r["allowlisted"])},
                ip_masked=mask_ip24(r["ip"]),
                gap=not r["allowlisted"],
            )
            for r in rows
        ]
        return out, {"decodes": len(rows), "outside_allowlist": sum(1 for r in rows if not r["allowlisted"])}

    async def _s_runs(
        self, s: dict[str, Any], paper_id: uuid.UUID | None
    ) -> tuple[list[ExamAuditEntry], dict[str, Any]]:
        rows = await self._q(
            "SELECT id, run_type, status, triggered_by, verified_by, verified_at, approved_by, approved_at, published_at, "
            "stats, config_snapshot, checksum, created_at FROM result_processing_runs WHERE institution_id = :i AND "
            "exam_session_id = :s ORDER BY created_at",
            s=s["id"],
        )
        names = await self._names(rows, "triggered_by", "verified_by", "approved_by")
        out = []
        for r in rows:
            snap = (
                hashlib.sha256(json.dumps(r["config_snapshot"], sort_keys=True, default=str).encode()).hexdigest()[:16]
                if r["config_snapshot"]
                else None
            )
            stats = dict(r["stats"] or {})
            out.append(
                ExamAuditEntry(
                    at=r["created_at"],
                    actor=self._who(r["triggered_by"], names),
                    action=f"run_{r['run_type']}_{r['status']}",
                    subject=str(r["id"]),
                    details={
                        "config_hash": snap,
                        "checksum": r["checksum"],
                        "anomalies": stats.get("anomalies") or stats.get("anomaly_count"),
                        "verified_by": names.get(r["verified_by"]),
                        "approved_by": names.get(r["approved_by"]),
                        "published_at": r["published_at"],
                    },
                )
            )
        return out, {"runs": len(rows), "published": sum(1 for r in rows if r["status"] == "published")}

    async def _s_publication(
        self, s: dict[str, Any], paper_id: uuid.UUID | None
    ) -> tuple[list[ExamAuditEntry], dict[str, Any]]:
        pubs = await self._q(
            "SELECT run_id, published_by, published_at, audience, withheld_list FROM result_publications WHERE "
            "institution_id = :i AND exam_session_id = :s ORDER BY published_at",
            s=s["id"],
        )
        versions = await self._q(
            "SELECT r.id, r.supersedes_id, r.version, r.status, r.total_marks, r.letter_grade, r.updated_at, r.run_id FROM "
            "student_course_results r WHERE r.institution_id = :i AND r.exam_session_id = :s AND (r.version > 1 OR r.status = 'superseded') "
            "ORDER BY r.updated_at LIMIT 1000",
            s=s["id"],
        )
        names = await self._names(pubs, "published_by")
        out = [
            ExamAuditEntry(
                at=p["published_at"],
                actor=self._who(p["published_by"], names),
                action=f"published_{p['audience']}",
                subject=str(p["run_id"]),
                details={"withheld": len(p["withheld_list"] or [])},
            )
            for p in pubs
        ]
        out += [
            ExamAuditEntry(
                at=v["updated_at"],
                action=f"result_v{v['version']}_{v['status']}",
                subject=str(v["id"]),
                details={
                    "supersedes": str(v["supersedes_id"]) if v["supersedes_id"] else None,
                    "grade": v["letter_grade"],
                    "run_id": str(v["run_id"]),
                },
            )
            for v in versions
        ]
        out.sort(key=lambda e: str(e.at))
        return out, {"publications": len(pubs), "corrected_versions": sum(1 for v in versions if v["version"] > 1)}

    async def _s_post_result(
        self, s: dict[str, Any], paper_id: uuid.UUID | None
    ) -> tuple[list[ExamAuditEntry], dict[str, Any]]:
        reval = await self._q(
            "SELECT id, request_type, status, original_marks, revised_marks, delta, decided_by, decided_at, created_at "
            "FROM reval_requests WHERE institution_id = :i AND exam_session_id = :s ORDER BY created_at",
            s=s["id"],
        )
        mal = await self._q(
            "SELECT id, case_number, category, punishment, status, decided_by, decided_at, reported_at FROM malpractice_cases "
            "WHERE institution_id = :i AND exam_session_id = :s ORDER BY reported_at",
            s=s["id"],
        )
        names = await self._names(reval + mal, "decided_by")
        out = [
            ExamAuditEntry(
                at=r["decided_at"] or r["created_at"],
                actor=self._who(r["decided_by"], names),
                action=f"reval_{r['status']}",
                subject=r["request_type"],
                details={
                    "original": _f(r["original_marks"]),
                    "revised": _f(r["revised_marks"]),
                    "delta": _f(r["delta"]),
                },
            )
            for r in reval
        ]
        out += [
            ExamAuditEntry(
                at=m["decided_at"] or m["reported_at"],
                actor=self._who(m["decided_by"], names),
                action=f"malpractice_{m['status']}",
                subject=m["case_number"],
                details={"category": m["category"], "punishment": m["punishment"]},
            )
            for m in mal
        ]
        out.sort(key=lambda e: str(e.at))
        return out, {
            "reval_requests": len(reval),
            "malpractice_cases": len(mal),
            "open": sum(1 for m in mal if m["status"] not in ("decided", "closed", "appeal_decided")),
        }

    # ---- summary / export -------------------------------------------------------------------------------------------
    async def summary(self, sid: uuid.UUID) -> ExamAuditSummaryOut:
        self.require_audit()
        s = await self.session(sid)
        counts: dict[str, int] = {}
        gaps = 0
        for sec in EXAM_AUDIT_SECTIONS:
            if sec == "decode" and not self.sees_decode():
                continue
            entries, summary = await getattr(self, f"_s_{sec}")(s, None)
            counts[sec] = len(entries)
            gaps += int(summary.get("gaps") or 0) + int(summary.get("outside_allowlist") or 0)
        pub = await self._q(
            "SELECT MIN(published_at) AS p FROM result_publications WHERE institution_id = :i AND exam_session_id = :s",
            s=sid,
        )
        days = None
        if pub and pub[0]["p"] and s.get("end_date"):
            days = (pub[0]["p"].date() - s["end_date"]).days
        return ExamAuditSummaryOut(
            exam_session_id=sid,
            session_name=s["name"],
            sections=counts,
            open_gaps=gaps,
            days_to_publication=days,
            decode_visible=self.sees_decode(),
        )

    async def export(self, sid: uuid.UUID, sections: list[str] | None, fmt: str) -> JobQueuedOut:
        self.require_audit()
        await self.session(sid)
        wanted = [x for x in (sections or EXAM_AUDIT_SECTIONS) if x != "decode" or self.sees_decode()]
        params = {"exam_session_id": str(sid), "sections": ",".join(wanted)}
        job = await enqueue(
            self.db,
            self.principal,
            "report.run",
            {"key": "exams.audit_trail", "params": params, "format": fmt},
            task_name="jobs.report.run",
        )
        await self._audit(
            "audit_export", "exam_session", sid, None, {"key": "exams.audit_trail", "params": params, "format": fmt}
        )
        return JobQueuedOut(job_id=job.id, job_type="report.run", report_key="exams.audit_trail")

    async def export_sections(self, sid: uuid.UUID, sections: list[str] | None) -> list[dict[str, Any]]:
        """Provider of ``exams.audit_trail``: one section per audit section (rows flattened for the renderers)."""
        self.require_audit()
        s = await self.session(sid)
        out = []
        for sec in sections or EXAM_AUDIT_SECTIONS:
            if sec not in EXAM_AUDIT_SECTIONS or (sec == "decode" and not self.sees_decode()):
                continue
            entries, summary = await getattr(self, f"_s_{sec}")(s, None)
            out.append(
                {
                    "title": f"{s['name']} — {sec.replace('_', ' ')}",
                    "summary": summary,
                    "rows": [
                        {
                            "at": e.at,
                            "actor": e.actor.name if e.actor else None,
                            "action": e.action,
                            "subject": e.subject,
                            "details": json.dumps(e.details, default=str)[:500],
                            "ip": e.ip_masked,
                            "gap": e.gap,
                        }
                        for e in entries
                    ],
                }
            )
        return out


def _f(v: Any) -> float | None:
    return float(v) if v is not None else None
