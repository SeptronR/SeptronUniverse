"""Module scaffolder — Prompts/00_PREREQUISITE_Project_Setup.md §3.25.

    python scripts/scaffold_module.py hostel --feature hostel.core --permissions hostel [--phase 20] [--group CAMPUS]

Generates (never overwrites existing files):
  backend/app/models/<m>.py · app/schemas/<m>.py · app/repositories/<m>_repository.py · app/services/<m>_service.py
  app/services/<m>/visibility.py · app/api/v1/endpoints/<m>.py · app/features/<m>.py · scripts/verify/NN_<m>.ps1
  scripts/seeders/<m>.py · frontend/src/features/<m>/{api.ts,hooks.ts,types.ts,pages/<M>Page.tsx} · flutter/lib/features/<m>/
and prints the three manual registrations (models/__init__, features/__init__, api router include, nav entry).
"""

import argparse
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

BACKEND = _bootstrap.BACKEND_DIR
FRONTEND = _bootstrap.FRONTEND_DIR
FLUTTER = _bootstrap.REPO_ROOT / "flutter"


def pascal(name: str) -> str:
    return "".join(p.capitalize() for p in name.split("_"))


def write(path: Path, content: str, created: list[str], skipped: list[str]) -> None:
    if path.exists():
        skipped.append(str(path.relative_to(_bootstrap.REPO_ROOT)))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    created.append(str(path.relative_to(_bootstrap.REPO_ROOT)))


def templates(m: str, feature: str, perm: str, phase: str, group: str) -> dict[Path, str]:
    M = pascal(m)
    return {
        BACKEND
        / "app"
        / "models"
        / f"{m}.py": f'''"""{M} models — copy the tables of the phase section from Database_Schema.sql (never retype names)."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import CollegeScopedMixin, TenantModelMixin


class {M}(TenantModelMixin, CollegeScopedMixin, Base):
    __tablename__ = "{m}"  # TODO: real table name from Database_Schema.sql

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
''',
        BACKEND
        / "app"
        / "schemas"
        / f"{m}.py": f'''"""{M} request/response schemas (snake_case, from_attributes)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class {M}Create(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    college_id: uuid.UUID | None = None


class {M}Update(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    status: str | None = None
    version: int


class {M}Response(ORMModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    college_id: uuid.UUID | None
    code: str
    name: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
''',
        BACKEND
        / "app"
        / "repositories"
        / f"{m}_repository.py": f'''"""{M} repository (all SQL for the module lives here)."""

from app.models.{m} import {M}
from app.repositories.base import BaseRepository


class {M}Repository(BaseRepository[{M}]):
    model = {M}
    module = "{perm}"
''',
        BACKEND / "app" / "services" / m / "__init__.py": f'"""{M} service package (visibility registrations)."""\n',
        BACKEND
        / "app"
        / "services"
        / m
        / "visibility.py": f'''"""Visibility registration for ``{perm}`` (docs/Authorization_and_Visibility.md)."""

from app.core.authz.visibility import ModuleVisibility, register_module
from app.models.{m} import {M}

register_module(
    ModuleVisibility(
        module="{perm}",
        model={M},
        self_predicate=None,  # e.g. lambda p, m: m.user_id == p.id
        scope_columns={{"institution": "institution_id", "college": "college_id"}},
    )
)
''',
        BACKEND
        / "app"
        / "services"
        / f"{m}_service.py": f'''"""{M} business rules (numbered docstrings), audit and domain events."""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.{m}.visibility  # noqa: F401
from app.core import events
from app.core.audit import log_audit
from app.core.authz.dependencies import Principal
from app.models.{m} import {M}
from app.repositories.{m}_repository import {M}Repository
from app.schemas.{m} import {M}Create, {M}Update
from app.utils.pagination import PageParams


class {M}Service:
    def __init__(self, db: AsyncSession, principal: Principal):
        self.db, self.principal = db, principal
        self.repo = {M}Repository(db, principal)

    async def list(self, params: PageParams, scope: str | None = None) -> tuple[list[{M}], Any, Any]:
        rows, pagination = await self.repo.list(params, scope)
        return rows, pagination, self.repo.visibility_meta()

    async def get(self, id: uuid.UUID) -> {M}:
        return await self.repo.get(id)

    async def create(self, body: {M}Create, request: Request) -> {M}:
        """1. Codes are unique per institution (DB constraint → 409 CONFLICT)."""
        obj = await self.repo.create(institution_id=self.principal.institution_id, created_by=self.principal.id, **body.model_dump())
        await log_audit(self.db, principal=self.principal, module="{perm}", action="create", record_type="{m}", record_id=obj.id, new=body.model_dump(mode="json"), request=request)
        await events.emit(self.db, institution_id=self.principal.institution_id, event_type="{m}.created", payload={{"id": str(obj.id)}}, aggregate_type="{m}", aggregate_id=obj.id, actor_user_id=self.principal.id)
        return obj

    async def update(self, id: uuid.UUID, body: {M}Update, request: Request) -> {M}:
        """2. Optimistic lock: body.version must match (409 STALE_VERSION)."""
        obj = await self.repo.get(id, for_update=True)
        values = body.model_dump(exclude_unset=True, exclude={{"version"}})
        obj = await self.repo.update(obj, expected_version=body.version, **values)
        await log_audit(self.db, principal=self.principal, module="{perm}", action="update", record_type="{m}", record_id=obj.id, new=values, request=request)
        return obj

    async def delete(self, id: uuid.UUID, request: Request) -> None:
        obj = await self.repo.get(id, for_update=True)
        await self.repo.soft_delete(obj, self.principal.id)
        await log_audit(self.db, principal=self.principal, module="{perm}", action="delete", record_type="{m}", record_id=obj.id, request=request)
''',
        BACKEND
        / "app"
        / "api"
        / "v1"
        / "endpoints"
        / f"{m}.py": f'''"""{M} endpoints — every route: permission_required + ok() envelope; the router is included with feature_required("{feature}")."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.{m} import {M}Create, {M}Response, {M}Update
from app.services.{m}_service import {M}Service
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(prefix="/{m.replace('_', '-')}", tags=["{m}"])


@router.get("", summary="List {m}")
async def list_{m}(
    params: PageParams = Depends(page_params),
    scope: str | None = Query(None, pattern="^(self|own|department|college|all)$"),
    principal: Principal = Depends(permission_required("{perm}", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await {M}Service(db, principal).list(params, scope)
    return ok([{M}Response.model_validate(r) for r in rows], pagination=pagination, visibility=visibility)


@router.get("/{{id}}", summary="Get {m}")
async def get_{m}(id: uuid.UUID, principal: Principal = Depends(permission_required("{perm}", "view")), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok({M}Response.model_validate(await {M}Service(db, principal).get(id)))


@router.post("", status_code=201, summary="Create {m}")
async def create_{m}(
    body: {M}Create,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("{perm}", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    obj = await {M}Service(db, principal).create(body, request)
    response = ok({M}Response.model_validate(obj), message="Created")
    await store(request, response, db, 201)
    return response


@router.put("/{{id}}", summary="Update {m} (If-Match via body.version)")
async def update_{m}(id: uuid.UUID, body: {M}Update, request: Request, principal: Principal = Depends(permission_required("{perm}", "update")), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok({M}Response.model_validate(await {M}Service(db, principal).update(id, body, request)), message="Updated")


@router.delete("/{{id}}", summary="Soft-delete {m}")
async def delete_{m}(id: uuid.UUID, request: Request, principal: Principal = Depends(permission_required("{perm}", "delete")), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await {M}Service(db, principal).delete(id, request)
    return ok(None, message="Deleted")
''',
        BACKEND
        / "app"
        / "features"
        / f"{m}.py": f'''"""Feature keys registered by the {m} module (docs/Feature_Flags.md)."""

from app.core.features import register_feature

register_feature(key="{feature}", group="{m}", name="{M}", description="TODO: copy from docs/Feature_Flags.md", default_enabled=True, min_plan_tier="starter")
''',
        BACKEND
        / "scripts"
        / "verify"
        / f"{phase}_{m}.ps1": f"""# API verification — Phase {phase} {m} (per role; dot-sources _common.ps1). Run from backend/: .\\scripts\\verify\\{phase}_{m}.ps1
param([string]$BaseUrl = "http://localhost:8000/api/v1")
. "$PSScriptRoot/_common.ps1" -BaseUrl $BaseUrl

$admin = Login "admin@demo-uni.local" (Get-DemoPassword "institution_admin")
$list = Call $admin GET "/{m.replace('_', '-')}?page=1&page_size=5"
Assert ($list.success -eq $true) "envelope success"
Assert ($null -ne $list.meta.visibility) "meta.visibility present"
Write-Host "PHASE {phase} {m}: PASS"
""",
        BACKEND
        / "scripts"
        / "seeders"
        / f"{m}.py": f'''"""Demo seed for ``--only {m}`` (depends on ``base``)."""

from seed_demo_institution import SeedContext, seeder


@seeder("{m}", after=["base"])
async def seed_{m}(ctx: SeedContext) -> None:
    # TODO: idempotent demo rows via ctx.get_or_create(Model, defaults=..., **lookup)
    return None
''',
        FRONTEND
        / "src"
        / "features"
        / m
        / "types.ts": f"""import type {{ components }} from '@/api/generated/openapi';

export type {M} = components['schemas']['{M}Response'];
export type {M}Create = components['schemas']['{M}Create'];
export type {M}Update = components['schemas']['{M}Update'];
""",
        FRONTEND
        / "src"
        / "features"
        / m
        / "api.ts": f"""import {{ api }} from '@/api/axios';
import type {{ Envelope, ListParams }} from '@/utils/types';
import type {{ {M}, {M}Create, {M}Update }} from './types';

const BASE = '/{m.replace('_', '-')}';

export const {m}Api = {{
  list: (params: ListParams) => api.get<Envelope<{M}[]>>(BASE, {{ params }}) as unknown as Promise<Envelope<{M}[]>>,
  get: (id: string) => api.get<Envelope<{M}>>(`${{BASE}}/${{id}}`) as unknown as Promise<Envelope<{M}>>,
  create: (body: {M}Create) => api.post<Envelope<{M}>>(BASE, body) as unknown as Promise<Envelope<{M}>>,
  update: (id: string, body: {M}Update) => api.put<Envelope<{M}>>(`${{BASE}}/${{id}}`, body) as unknown as Promise<Envelope<{M}>>,
  remove: (id: string) => api.delete<Envelope<null>>(`${{BASE}}/${{id}}`) as unknown as Promise<Envelope<null>>,
}};
""",
        FRONTEND
        / "src"
        / "features"
        / m
        / "hooks.ts": f"""import {{ useMutation, useQuery, useQueryClient }} from '@tanstack/react-query';
import type {{ ListParams }} from '@/utils/types';
import {{ {m}Api }} from './api';
import type {{ {M}Create, {M}Update }} from './types';

const KEY = '{perm}';

export const use{M}List = (params: ListParams) => useQuery({{ queryKey: [KEY, params], queryFn: () => {m}Api.list(params) }});
export const use{M} = (id: string) => useQuery({{ queryKey: [KEY, id], queryFn: () => {m}Api.get(id), enabled: !!id }});
export const useCreate{M} = () => {{
  const qc = useQueryClient();
  return useMutation({{ mutationFn: (body: {M}Create) => {m}Api.create(body), onSuccess: () => qc.invalidateQueries({{ queryKey: [KEY] }}) }});
}};
export const useUpdate{M} = () => {{
  const qc = useQueryClient();
  return useMutation({{ mutationFn: ({{ id, body }}: {{ id: string; body: {M}Update }}) => {m}Api.update(id, body), onSuccess: () => qc.invalidateQueries({{ queryKey: [KEY] }}) }});
}};
""",
        FRONTEND
        / "src"
        / "features"
        / m
        / "pages"
        / f"{M}Page.tsx": f"""import {{ useState }} from 'react';
import {{ PageHeader }} from '@/components/shared/PageHeader';
import {{ DataTable }} from '@/components/shared/DataTable';
import {{ ScopeTabs }} from '@/components/shared/ScopeTabs';
import {{ use{M}List }} from '../hooks';
import type {{ {M} }} from '../types';

export default function {M}Page() {{
  const [page, setPage] = useState(1);
  const [scope, setScope] = useState<string | undefined>(undefined);
  const query = use{M}List({{ page, page_size: 25, scope }});
  const visibility = query.data?.meta.visibility;
  return (
    <div className="space-y-4">
      <PageHeader title="{M}" description="TODO: describe the module" />
      {{visibility && <ScopeTabs visibility={{visibility}} value={{scope}} onChange={{setScope}} />}}
      <DataTable<{M}>
        columns={{[
          {{ header: 'Code', accessorKey: 'code' }},
          {{ header: 'Name', accessorKey: 'name' }},
          {{ header: 'Status', accessorKey: 'status' }},
        ]}}
        data={{query.data?.data ?? []}}
        pagination={{query.data?.meta.pagination}}
        onPageChange={{setPage}}
        isLoading={{query.isLoading}}
      />
    </div>
  );
}}
""",
        FLUTTER
        / "lib"
        / "features"
        / m
        / "README.md": f"# {m}\n\nFlutter feature folder (data/domain/application/presentation) — screens registered in `lib/core/router/screen_registry.dart` by the phase prompt's NN.10.\n",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("module", help="snake_case module name, e.g. hostel")
    ap.add_argument("--feature", required=True, help="feature key the router is gated on, e.g. hostel.core")
    ap.add_argument("--permissions", required=True, help="permission module, e.g. hostel")
    ap.add_argument("--phase", default="NN", help="two-digit phase number for the verification script name")
    ap.add_argument("--group", default="CAMPUS", help="NAV_GROUPS title for the nav entry hint")
    args = ap.parse_args()

    m = args.module.lower()
    created: list[str] = []
    skipped: list[str] = []
    for path, content in templates(m, args.feature, args.permissions, args.phase.zfill(2), args.group).items():
        write(path, content, created, skipped)

    M = pascal(m)
    print("created:")
    for c in created:
        print(f"  + {c}")
    if skipped:
        print("skipped (already exist):")
        for s in skipped:
            print(f"  = {s}")
    print(
        "\nmanual registrations:\n"
        f"  1. backend/app/models/__init__.py:      from app.models import {m}  # noqa: F401\n"
        f"  2. backend/app/features/__init__.py:    from app.features import {m}  # noqa: F401\n"
        f'  3. backend/app/api/v1/router.py:        api_router.include_router({m}.router, dependencies=[feature_required("{args.feature}")])\n'
        f'  4. backend/scripts/phase_manifest.py:   PHASES["{args.phase.zfill(2)}"] = [...tables...]\n'
        f"  5. frontend/src/nav.ts ({args.group}):   {{ label: '{M}', to: '/{m.replace('_', '-')}', icon: Boxes, module: '{args.permissions}', feature: '{args.feature}' }}\n"
        f"  6. frontend/src/routes/index.tsx:       lazy route for features/{m}/pages/{M}Page.tsx inside FeatureRoute + PermissionRoute"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
