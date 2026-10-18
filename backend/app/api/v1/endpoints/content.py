"""Question bank, blueprints, paper builder and study materials — Prompts/13 §13.8 (router included with
``feature_required("lms.question_bank")``; blueprints / papers {lms.blueprints_paper_builder}; study materials on
``materials_router`` with {lms.study_materials})."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.content import (
    BlueprintIn,
    BlueprintOut,
    PaperGenerateRequest,
    PaperOut,
    PaperUpdate,
    QuestionImportReport,
    QuestionIn,
    QuestionOut,
    StudyMaterialIn,
    StudyMaterialOut,
    SyllabusTopicIn,
    SyllabusTopicOut,
)
from app.services.assessment.content_service import ContentService
from app.utils.response import ok

router = APIRouter(tags=["question-bank"])
materials_router = APIRouter(tags=["study-materials"])

VIEW = any_permission_required(("lms", "view"), ("lms", "view_all"), ("lms", "manage"), ("exams", "view_all"))
MANAGE = any_permission_required(("lms", "manage"), ("lms", "grade"))
PAPERS = [feature_required("lms.blueprints_paper_builder")]


@router.get("/courses/{id}/syllabus-topics", summary="Syllabus topics", response_model=Envelope[list[SyllabusTopicOut]])
async def topics(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).topics(id))


@router.post("/courses/{id}/syllabus-topics", summary="Add a syllabus topic", response_model=Envelope[SyllabusTopicOut])
async def add_topic(
    id: uuid.UUID,
    body: SyllabusTopicIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).add_topic(id, body), message="Topic added")


@router.get("/questions", summary="Question bank (own + department shares)", response_model=Envelope[list[QuestionOut]])
async def questions(
    request: Request,
    course_id: uuid.UUID | None = None,
    co_id: uuid.UUID | None = None,
    difficulty: str | None = None,
    q: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).questions(course_id, co_id, difficulty, q, limit))


@router.post(
    "/questions",
    status_code=201,
    summary="Create a question (bilingual, options, answer key)",
    response_model=Envelope[QuestionOut],
)
async def create_question(
    body: QuestionIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).create_question(body), message="Question created")


@router.post(
    "/questions/import",
    summary="Import CSV (body,type,marks,difficulty,bloom,co_code,option_a..d,correct)",
    response_model=Envelope[QuestionImportReport],
)
async def import_questions(
    request: Request,
    course_id: uuid.UUID | None = None,
    file: UploadFile = File(...),
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    out = await ContentService(db, principal, request).import_csv(course_id, text)
    return ok(out, message=f"{out.created} imported, {len(out.failed)} failed")


@router.put("/questions/{id}", summary="Update a question (author)", response_model=Envelope[QuestionOut])
async def update_question(
    id: uuid.UUID,
    body: QuestionIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).update_question(id, body), message="Question updated")


@router.delete("/questions/{id}", summary="Delete a question (author; soft)", response_model=Envelope[None])
async def delete_question(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await ContentService(db, principal, request).delete_question(id)
    return ok(None, message="Question deleted")


@router.get("/blueprints", summary="Blueprints", dependencies=PAPERS, response_model=Envelope[list[BlueprintOut]])
async def blueprints(
    request: Request,
    course_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).blueprints(course_id))


@router.post(
    "/blueprints",
    summary="Create a blueprint (parts × count × marks = total)",
    dependencies=PAPERS,
    response_model=Envelope[BlueprintOut],
)
async def create_blueprint(
    body: BlueprintIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).create_blueprint(body), message="Blueprint created")


@router.post(
    "/question-papers/generate",
    summary="Generate a paper from a blueprint",
    dependencies=PAPERS,
    response_model=Envelope[PaperOut],
)
async def generate(
    body: PaperGenerateRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await ContentService(db, principal, request).generate(body)
    return ok(out, message="Generated" + (f" — shortfall in {len(out.shortfall)} part(s)" if out.shortfall else ""))


@router.get("/question-papers/{id}", summary="Question paper", dependencies=PAPERS, response_model=Envelope[PaperOut])
async def paper(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).paper(id))


@router.put(
    "/question-papers/{id}",
    summary="Edit a draft paper (frozen → 409)",
    dependencies=PAPERS,
    response_model=Envelope[PaperOut],
)
async def update_paper(
    id: uuid.UUID,
    body: PaperUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).update_paper(id, body), message="Paper saved")


@router.post("/question-papers/{id}/freeze", summary="Freeze", dependencies=PAPERS, response_model=Envelope[PaperOut])
async def freeze(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).freeze(id), message="Frozen")


@router.get(
    "/question-papers/{id}/print",
    summary="Print PDF (lang = primary | secondary | both)",
    dependencies=PAPERS,
    response_class=Response,
)
async def print_paper(
    id: uuid.UUID,
    request: Request,
    lang: str = Query("primary", pattern="^(primary|secondary|both)$"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> Response:
    pdf, title = await ContentService(db, principal, request).print_pdf(id, lang)
    safe = "".join(c for c in title if c.isalnum() or c in "-_ ")[:60] or "paper"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename={safe}.pdf"})


# ---- study materials ---------------------------------------------------------------------------------------------------------
@materials_router.get(
    "/study-materials/me",
    summary="Published materials of my offerings",
    response_model=Envelope[list[StudyMaterialOut]],
)
async def my_materials(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).my_materials())


@materials_router.get("/study-materials", summary="Study materials", response_model=Envelope[list[StudyMaterialOut]])
async def materials(
    request: Request,
    course_id: uuid.UUID | None = None,
    offering_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).materials(course_id, offering_id))


@materials_router.post("/study-materials", summary="Create a material", response_model=Envelope[StudyMaterialOut])
async def create_material(
    body: StudyMaterialIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).save_material(body), message="Material created")


@materials_router.put("/study-materials/{id}", summary="Update a material", response_model=Envelope[StudyMaterialOut])
async def update_material(
    id: uuid.UUID,
    body: StudyMaterialIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).save_material(body, id), message="Material updated")


@materials_router.post("/study-materials/{id}/publish", summary="Publish", response_model=Envelope[StudyMaterialOut])
async def publish_material(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ContentService(db, principal, request).publish_material(id), message="Published")
