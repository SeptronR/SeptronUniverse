"""Attainment configs — Prompts/17 §17.6 ``attainment_config_service``.

Effective config for a programme: programme row → the programme's regulation row (the batch's / latest active
``program_regulations``) → ``platform_settings['attainment_defaults']`` (revision ``0017``) → ``ATTAINMENT_DEFAULTS``.
Validation: level bands strictly ascending in both ``level`` and ``min_pct``; direct + indirect = 100; CIA + ESE = 100
(422 ``VALIDATION`` with a ``code``). Keys the DDL has no column for (``ese_apportion_strategy``,
``credit_weighted_po``, ``survey_thresholds``) are kept per scope in ``institution_settings`` (``obe`` /
``attainment_extras``). Every edit is audited (``obe:update_config`` old → new) — the history list reads those rows;
runs store the full effective config in ``config_snapshot``, so past runs stay reproducible.
"""

import uuid
from typing import Any

from sqlalchemy import select, text

from app.core.errors import APIError, ErrorCode
from app.enums.obe_attainment import ATTAINMENT_DEFAULTS
from app.models.academic import Batch, Program, ProgramRegulation, Regulation
from app.models.obe_attainment import AttainmentConfig
from app.models.platform import AuditLog, InstitutionSetting
from app.schemas.obe_attainment import AttainmentConfigIn, AttainmentConfigOut
from app.services.obe.common import ObeBase

COLUMNS = (
    "target_student_pct",
    "target_marks_pct",
    "levels",
    "direct_weight",
    "indirect_weight",
    "cia_weight_in_direct",
    "ese_weight_in_direct",
    "co_target_level",
    "po_target_level",
)
EXTRAS = ("ese_apportion_strategy", "credit_weighted_po", "survey_thresholds")


def _num(v: Any) -> Any:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return int(f) if f.is_integer() and not isinstance(v, float) else f


class AttainmentConfigService(ObeBase):
    async def platform_defaults(self) -> dict[str, Any]:
        row = (
            await self.db.execute(text("SELECT value FROM platform_settings WHERE key = 'attainment_defaults'"))
        ).scalar_one_or_none()
        out = dict(ATTAINMENT_DEFAULTS)
        if isinstance(row, dict):
            nested = row.get("defaults")
            out.update(nested if isinstance(nested, dict) else row)
        return out

    async def _extras_row(self) -> InstitutionSetting | None:
        return (
            await self.db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.college_id.is_(None),
                    InstitutionSetting.category == "obe",
                    InstitutionSetting.key == "attainment_extras",
                )
            )
        ).scalar_one_or_none()

    async def _extras(self, scope_id: uuid.UUID) -> dict[str, Any]:
        row = await self._extras_row()
        return dict(((row.value if row else None) or {}).get(str(scope_id)) or {})

    async def _row(self, scope_type: str, scope_id: uuid.UUID) -> AttainmentConfig | None:
        return (
            await self.db.execute(
                select(AttainmentConfig).where(
                    AttainmentConfig.institution_id == self.inst,
                    AttainmentConfig.scope_type == scope_type,
                    AttainmentConfig.scope_id == scope_id,
                )
            )
        ).scalar_one_or_none()

    async def regulation_of(self, program_id: uuid.UUID, batch_id: uuid.UUID | None = None) -> uuid.UUID | None:
        if batch_id is not None:
            rid = (
                await self.db.execute(
                    select(ProgramRegulation.regulation_id)
                    .join(Batch, Batch.program_regulation_id == ProgramRegulation.id)
                    .where(Batch.id == batch_id)
                )
            ).scalar_one_or_none()
            if rid:
                return rid
        return (
            await self.db.execute(
                select(ProgramRegulation.regulation_id)
                .where(ProgramRegulation.program_id == program_id, ProgramRegulation.deleted_at.is_(None))
                .order_by((ProgramRegulation.status == "active").desc(), ProgramRegulation.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    def _out(self, base: dict[str, Any], source: str, row: AttainmentConfig | None, extras: dict[str, Any]) -> dict:
        cfg = dict(base)
        if row is not None:
            for k in COLUMNS:
                cfg[k] = _num(getattr(row, k)) if k != "levels" else list(row.levels)
        cfg.update({k: v for k, v in extras.items() if k in EXTRAS and v is not None})
        cfg["source"] = source
        return cfg

    async def effective(
        self,
        program_id: uuid.UUID | None = None,
        regulation_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Plain dict (the run snapshot): every config key + ``source`` / ``scope_type`` / ``scope_id``."""
        base = await self.platform_defaults()
        if regulation_id is None and program_id is not None:
            regulation_id = await self.regulation_of(program_id, batch_id)
        if program_id is not None:
            row = await self._row("program", program_id)
            if row is not None:
                reg_cfg = await self.effective(None, regulation_id) if regulation_id else base
                out = self._out(reg_cfg, "program", row, await self._extras(program_id))
                return {**out, "scope_type": "program", "scope_id": str(program_id), "config_id": str(row.id)}
        if regulation_id is not None:
            row = await self._row("regulation", regulation_id)
            if row is not None:
                out = self._out(base, "regulation", row, await self._extras(regulation_id))
                return {**out, "scope_type": "regulation", "scope_id": str(regulation_id), "config_id": str(row.id)}
        out = self._out(base, "platform", None, {})
        return {**out, "scope_type": "platform", "scope_id": None, "config_id": None}

    async def _history(self, config_id: Any) -> list[dict[str, Any]]:
        if not config_id:
            return []
        rows = (
            await self.db.execute(
                select(
                    AuditLog.occurred_at, AuditLog.user_id, AuditLog.action, AuditLog.old_values, AuditLog.new_values
                )
                .where(
                    AuditLog.institution_id == self.inst,
                    AuditLog.record_type == "attainment_config",
                    AuditLog.record_id == uuid.UUID(str(config_id)),
                )
                .order_by(AuditLog.occurred_at.desc())
                .limit(50)
            )
        ).all()
        return [
            {"at": r[0].isoformat(), "by": str(r[1]) if r[1] else None, "action": r[2], "old": r[3], "new": r[4]}
            for r in rows
        ]

    def _to_out(self, cfg: dict[str, Any], history: list[dict[str, Any]]) -> AttainmentConfigOut:
        return AttainmentConfigOut(
            id=cfg.get("config_id"),
            scope_type=cfg.get("scope_type") or "platform",
            scope_id=cfg.get("scope_id"),
            source=cfg["source"],
            target_student_pct=float(cfg["target_student_pct"]),
            target_marks_pct=float(cfg["target_marks_pct"]),
            levels=cfg["levels"],
            direct_weight=int(cfg["direct_weight"]),
            indirect_weight=int(cfg["indirect_weight"]),
            cia_weight_in_direct=int(cfg["cia_weight_in_direct"]),
            ese_weight_in_direct=int(cfg["ese_weight_in_direct"]),
            co_target_level=float(cfg["co_target_level"]),
            po_target_level=float(cfg["po_target_level"]),
            ese_apportion_strategy=str(cfg.get("ese_apportion_strategy") or "question_wise"),
            credit_weighted_po=bool(cfg.get("credit_weighted_po")),
            survey_thresholds=cfg.get("survey_thresholds") or ATTAINMENT_DEFAULTS["survey_thresholds"],
            history=history,
        )

    async def get_effective(self, program_id: uuid.UUID, batch_id: uuid.UUID | None = None) -> AttainmentConfigOut:
        await self._scope_exists("program", program_id)
        cfg = await self.effective(program_id, batch_id=batch_id)
        return self._to_out(cfg, await self._history(cfg.get("config_id")))

    async def get(self, scope_type: str, scope_id: uuid.UUID) -> AttainmentConfigOut:
        await self._scope_exists(scope_type, scope_id)
        cfg = (
            await self.effective(program_id=scope_id)
            if scope_type == "program"
            else await self.effective(regulation_id=scope_id)
        )
        return self._to_out(cfg, await self._history(cfg.get("config_id")))

    async def _scope_exists(self, scope_type: str, scope_id: uuid.UUID) -> None:
        model: Any = Program if scope_type == "program" else Regulation
        if scope_type not in ("program", "regulation"):
            raise APIError(422, ErrorCode.VALIDATION, "scope_type must be program or regulation")
        hit = (
            await self.db.execute(select(model.id).where(model.id == scope_id, model.institution_id == self.inst))
        ).first()
        if hit is None:
            raise APIError(404, ErrorCode.NOT_FOUND, f"{scope_type.title()} not found")

    @staticmethod
    def validate(body: AttainmentConfigIn) -> None:
        levels = [(b.level, b.min_pct) for b in body.levels]
        if any(b[0] >= a[0] or b[1] >= a[1] for b, a in zip(levels, levels[1:], strict=False)):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Level bands must ascend in level and min_pct",
                {"code": "LEVELS_NOT_ASCENDING"},
            )
        if body.direct_weight + body.indirect_weight != 100:
            raise APIError(
                422, ErrorCode.VALIDATION, "Direct + indirect weights must add up to 100", {"code": "WEIGHTS_NOT_100"}
            )
        if body.cia_weight_in_direct + body.ese_weight_in_direct != 100:
            raise APIError(
                422, ErrorCode.VALIDATION, "CIA + ESE weights must add up to 100", {"code": "WEIGHTS_NOT_100"}
            )
        if body.survey_thresholds:
            t = sorted(body.survey_thresholds, key=lambda x: x.level)
            if any(b.min_mean >= a.min_mean for b, a in zip(t, t[1:], strict=False)):
                raise APIError(
                    422, ErrorCode.VALIDATION, "Survey thresholds must ascend", {"code": "THRESHOLDS_NOT_ASCENDING"}
                )

    async def put(self, body: AttainmentConfigIn) -> AttainmentConfigOut:
        if not self.can("obe", "configure"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "obe:configure required")
        await self._scope_exists(body.scope_type, body.scope_id)
        self.validate(body)
        row = await self._row(body.scope_type, body.scope_id)
        old = None
        values = {
            "target_student_pct": body.target_student_pct,
            "target_marks_pct": body.target_marks_pct,
            "levels": [b.model_dump() for b in body.levels],
            "direct_weight": body.direct_weight,
            "indirect_weight": body.indirect_weight,
            "cia_weight_in_direct": body.cia_weight_in_direct,
            "ese_weight_in_direct": body.ese_weight_in_direct,
            "co_target_level": body.co_target_level,
            "po_target_level": body.po_target_level,
        }
        if row is None:
            row = AttainmentConfig(
                institution_id=self.inst, scope_type=body.scope_type, scope_id=body.scope_id, **values
            )
            self.db.add(row)
        else:
            old = {k: _num(getattr(row, k)) if k != "levels" else row.levels for k in COLUMNS}
            old.update(await self._extras(body.scope_id))
            for k, v in values.items():
                setattr(row, k, v)
        extras = {
            "ese_apportion_strategy": body.ese_apportion_strategy,
            "credit_weighted_po": body.credit_weighted_po,
            "survey_thresholds": [t.model_dump() for t in body.survey_thresholds] if body.survey_thresholds else None,
        }
        await self._save_extras(body.scope_id, extras)
        await self.db.flush()
        await self._audit(
            "update_config" if old else "create_config", "attainment_config", row.id, old, {**values, **extras}
        )
        return await self.get(body.scope_type, body.scope_id)

    async def _save_extras(self, scope_id: uuid.UUID, extras: dict[str, Any]) -> None:
        row = await self._extras_row()
        data = dict((row.value if row else None) or {})
        data[str(scope_id)] = {k: v for k, v in extras.items() if v is not None}
        if row is None:
            self.db.add(
                InstitutionSetting(
                    institution_id=self.inst,
                    college_id=None,
                    category="obe",
                    key="attainment_extras",
                    value=data,
                    value_type="json",
                )
            )
        else:
            row.value = data

    async def list_configs(self, scope_type: str | None, scope_id: uuid.UUID | None) -> list[AttainmentConfigOut]:
        q = select(AttainmentConfig).where(AttainmentConfig.institution_id == self.inst)
        if scope_type:
            q = q.where(AttainmentConfig.scope_type == scope_type)
        if scope_id:
            q = q.where(AttainmentConfig.scope_id == scope_id)
        rows = (await self.db.execute(q.order_by(AttainmentConfig.updated_at.desc()))).scalars().all()
        base = await self.platform_defaults()
        out = []
        for r in rows:
            cfg = self._out(base, r.scope_type, r, await self._extras(r.scope_id))
            out.append(self._to_out({**cfg, "scope_type": r.scope_type, "scope_id": r.scope_id, "config_id": r.id}, []))
        if scope_type and scope_id and not rows:
            out.append(await self.get(scope_type, scope_id))
        return out
