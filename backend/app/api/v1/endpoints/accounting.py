"""Accounting & budget — Prompts/23 §23.8.

Each route carries its ``accounting.*`` feature; visibility narrows in the services (own / department / PI / college /
all; 404 otherwise). Posting replays, reconciliation imports, voucher exports, UC PDFs and year close answer ``202``
with a ``job_id``. Fixed paths precede parameterised ones.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.accounting import (
    AcctAccountIn,
    AcctAccountOut,
    AcctAccountUpdate,
    AcctDashboard,
    AcctJobAccepted,
    AcctMappings,
    AcctReverse,
    BudgetBulkAllocate,
    BudgetHeadIn,
    BudgetHeadOut,
    BudgetHeadUpdate,
    BudgetRevise,
    BudgetTransfer,
    ChartImport,
    ExpenseDecision,
    ExpensePay,
    ExpenseRecordIn,
    ExpenseRecordOut,
    ExpenseRecordUpdate,
    ExportOut,
    ExportRequest,
    GrantClose,
    GrantExpense,
    GrantLedgerIn,
    GrantLedgerOut,
    GrantReallocate,
    GrantReceipt,
    GstReportOut,
    IncomeRecordIn,
    IncomeRecordOut,
    IncomeRecordUpdate,
    LedgerLine,
    PeriodClose,
    ReconAddRecord,
    ReconciliationCreate,
    ReconciliationOut,
    ReconImport,
    ReconMatch,
    StatementOut,
    TrialBalanceOut,
    YearClose,
)
from app.schemas.common import Envelope
from app.services.accounting.budget_service import BudgetService
from app.services.accounting.chart_service import ChartService
from app.services.accounting.common import visibility_scopes
from app.services.accounting.finance_service import STATEMENTS, FinanceService
from app.services.accounting.grant_service import GrantService
from app.services.accounting.posting_service import PostingService
from app.services.accounting.reconciliation_service import ReconciliationService
from app.services.accounting.records_service import RecordsService
from app.utils.response import ok

router = APIRouter(tags=["accounting"])

A = "accounting"
MANAGE = any_permission_required((A, "manage"))
READ = any_permission_required((A, "view_all"), (A, "manage"))
VIEW = any_permission_required((A, "view"), (A, "view_all"), (A, "manage"), (A, "post"))
POST = any_permission_required((A, "post"), (A, "manage"), (A, "view_all"))
EXP = any_permission_required((A, "post"), (A, "approve"), (A, "view"), (A, "view_all"), (A, "manage"))
APPROVE = any_permission_required((A, "approve"), (A, "manage"))
RECON = any_permission_required((A, "reconcile"), (A, "view_all"), (A, "manage"))
EXPORT = any_permission_required((A, "export"), (A, "view_all"), (A, "manage"))
STMT = any_permission_required((A, "view_all"), (A, "manage"), ("reports", "export"))
GRANT = any_permission_required((A, "view"), (A, "view_all"), (A, "manage"), ("research", "view_all"))

CORE = [feature_required("accounting.core")]
BUDGETS = [feature_required("accounting.budgets")]
GRANTS = [feature_required("accounting.grants_ledger")]
GST = [feature_required("accounting.gst_reports")]
TALLY = [feature_required("accounting.tally_export")]


def _vis(principal: Principal, data: Any) -> dict[str, Any]:
    tabs = visibility_scopes(principal)
    res = ok(data)
    res.setdefault("meta", {})["visibility"] = {"self": True, "scopes": tabs, "default": tabs[-1] if tabs else "self"}
    return res


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(
        status_code=202, content=ok(AcctJobAccepted(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


def _file(content: bytes, fmt: str, name: str) -> Response:
    media = "application/pdf" if fmt == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'}
    )


# ---- chart ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/accounting/accounts/tree",
    summary="Chart of accounts with period balances",
    response_model=Envelope[list[AcctAccountOut]],
    dependencies=CORE,
)
async def accounts_tree(
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ChartService(db, principal, request).tree(date_from, date_to))


@router.post(
    "/accounting/accounts/import",
    summary="Import the IN template or a CSV chart",
    response_model=Envelope[dict[str, int]],
    dependencies=CORE,
)
async def accounts_import(
    body: ChartImport, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ChartService(db, principal, request).import_chart(body.template, body.csv))


@router.get(
    "/accounting/accounts",
    summary="Ledger accounts (flat)",
    response_model=Envelope[list[AcctAccountOut]],
    dependencies=CORE,
)
async def accounts(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ChartService(db, principal, request).accounts())


@router.post(
    "/accounting/accounts",
    status_code=201,
    summary="Add a ledger account",
    response_model=Envelope[AcctAccountOut],
    dependencies=CORE,
)
async def account_create(
    body: AcctAccountIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ChartService(db, principal, request).create(body))


@router.get(
    "/accounting/accounts/{id}", summary="Ledger account", response_model=Envelope[AcctAccountOut], dependencies=CORE
)
async def account_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ChartService(db, principal, request).get(id))


@router.put(
    "/accounting/accounts/{id}",
    summary="Edit / deactivate a ledger account",
    response_model=Envelope[AcctAccountOut],
    dependencies=CORE,
)
async def account_update(
    id: uuid.UUID,
    body: AcctAccountUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ChartService(db, principal, request).update(id, body))


@router.get(
    "/accounting/mappings",
    summary="Account mappings (fee heads, system keys, inventory categories)",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def mappings(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ChartService(db, principal, request).get_mappings())


@router.put(
    "/accounting/mappings",
    summary="Update account mappings",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def mappings_put(
    body: AcctMappings, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ChartService(db, principal, request).put_mappings(dict(body.mappings)))


@router.get(
    "/accounting/ledger/{account_id}",
    summary="Account ledger with source links",
    response_model=Envelope[list[LedgerLine]],
    dependencies=CORE,
)
async def ledger(
    account_id: uuid.UUID,
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FinanceService(db, principal, request).ledger(account_id, date_from, date_to))


@router.get(
    "/accounting/trial-balance", summary="Trial balance", response_model=Envelope[TrialBalanceOut], dependencies=CORE
)
async def trial_balance(
    request: Request,
    date_from: date = Query(..., alias="from"),
    date_to: date = Query(..., alias="to"),
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FinanceService(db, principal, request).trial_balance(date_from, date_to, college_id))


# ---- income ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/accounting/income", summary="Income records", response_model=Envelope[list[IncomeRecordOut]], dependencies=CORE
)
async def incomes(
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    source_type: str | None = None,
    account_id: uuid.UUID | None = None,
    principal: Principal = Depends(POST),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecordsService(db, principal, request).incomes(date_from, date_to, source_type, account_id))


@router.post(
    "/accounting/income",
    status_code=201,
    summary="Record income",
    response_model=Envelope[IncomeRecordOut],
    dependencies=CORE,
)
async def income_create(
    body: IncomeRecordIn, request: Request, principal: Principal = Depends(POST), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecordsService(db, principal, request).create_income(body))


@router.get(
    "/accounting/income/{id}", summary="Income record", response_model=Envelope[IncomeRecordOut], dependencies=CORE
)
async def income_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(POST), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = RecordsService(db, principal, request)
    svc.require("view_all", "post")
    return ok((await svc.income_outs([await svc.income_row(id)]))[0])


@router.put(
    "/accounting/income/{id}",
    summary="Edit a manual income record",
    response_model=Envelope[IncomeRecordOut],
    dependencies=CORE,
)
async def income_update(
    id: uuid.UUID,
    body: IncomeRecordUpdate,
    request: Request,
    principal: Principal = Depends(POST),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecordsService(db, principal, request).update_income(id, body))


@router.post(
    "/accounting/income/{id}/reverse",
    summary="Reverse an income record",
    response_model=Envelope[IncomeRecordOut],
    dependencies=CORE,
)
async def income_reverse(
    id: uuid.UUID,
    body: AcctReverse,
    request: Request,
    principal: Principal = Depends(POST),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecordsService(db, principal, request).reverse_income(id, body))


# ---- expenses -------------------------------------------------------------------------------------------------------------
@router.get(
    "/accounting/expenses",
    summary="Expenses (ScopeTabs)",
    response_model=Envelope[list[ExpenseRecordOut]],
    dependencies=CORE,
)
async def expenses(
    request: Request,
    department_id: uuid.UUID | None = None,
    status: str | None = None,
    budget_head_id: uuid.UUID | None = None,
    scope: str | None = Query(None, pattern="^(self|department|college|all)$"),
    manual_only: bool = False,
    principal: Principal = Depends(EXP),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(
        principal,
        await RecordsService(db, principal, request).expenses(
            department_id, status, budget_head_id, scope, manual_only
        ),
    )


@router.post(
    "/accounting/expenses",
    status_code=201,
    summary="Record an expense",
    response_model=Envelope[ExpenseRecordOut],
    dependencies=CORE,
)
async def expense_create(
    body: ExpenseRecordIn, request: Request, principal: Principal = Depends(EXP), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecordsService(db, principal, request).create_expense(body))


@router.get(
    "/accounting/expenses/{id}", summary="Expense", response_model=Envelope[ExpenseRecordOut], dependencies=CORE
)
async def expense_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EXP), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecordsService(db, principal, request).get_expense(id))


@router.put(
    "/accounting/expenses/{id}",
    summary="Edit a recorded expense",
    response_model=Envelope[ExpenseRecordOut],
    dependencies=CORE,
)
async def expense_update(
    id: uuid.UUID,
    body: ExpenseRecordUpdate,
    request: Request,
    principal: Principal = Depends(EXP),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecordsService(db, principal, request).update_expense(id, body))


@router.post(
    "/accounting/expenses/{id}/submit",
    summary="Submit for approval (workflow above the threshold)",
    response_model=Envelope[ExpenseRecordOut],
    dependencies=CORE,
)
async def expense_submit(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EXP), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecordsService(db, principal, request).submit(id))


@router.post(
    "/accounting/expenses/{id}/decide",
    summary="Approve / reject (below the threshold)",
    response_model=Envelope[ExpenseRecordOut],
    dependencies=CORE,
)
async def expense_decide(
    id: uuid.UUID,
    body: ExpenseDecision,
    request: Request,
    principal: Principal = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecordsService(db, principal, request).decide(id, body))


@router.post(
    "/accounting/expenses/{id}/pay",
    summary="Mark an approved expense paid",
    response_model=Envelope[ExpenseRecordOut],
    dependencies=CORE,
)
async def expense_pay(
    id: uuid.UUID,
    body: ExpensePay,
    request: Request,
    principal: Principal = Depends(POST),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecordsService(db, principal, request).pay(id, body))


# ---- postings ----------------------------------------------------------------------------------------------------------------
@router.post(
    "/accounting/postings/replay",
    status_code=202,
    summary="Rebuild automatic postings for a period (job)",
    response_model=Envelope[AcctJobAccepted],
    dependencies=CORE,
)
async def postings_replay(
    request: Request,
    date_from: date = Query(..., alias="from"),
    date_to: date = Query(..., alias="to"),
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _job(
        db, principal, "accounting.posting_replay", {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()}
    )


@router.get(
    "/accounting/postings/gaps",
    summary="Sources without postings",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=CORE,
)
async def postings_gaps(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PostingService(db, principal, request).gaps())


# ---- budgets -------------------------------------------------------------------------------------------------------------------
@router.get(
    "/accounting/budgets/me",
    summary="Budget heads of my department",
    response_model=Envelope[list[BudgetHeadOut]],
    dependencies=BUDGETS,
)
async def budgets_me(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).mine())


@router.get(
    "/accounting/budgets/utilisation",
    summary="Utilisation by department",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=BUDGETS,
)
async def budgets_utilisation(
    request: Request,
    year: uuid.UUID | None = None,
    college_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).utilisation(year, college_id, department_id))


@router.post(
    "/accounting/budgets/bulk",
    status_code=201,
    summary="Bulk allocate (draft heads)",
    response_model=Envelope[dict[str, Any]],
    dependencies=BUDGETS,
)
async def budgets_bulk(
    body: BudgetBulkAllocate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).bulk(body))


@router.post(
    "/accounting/budgets/transfer",
    summary="Transfer allocation between heads",
    response_model=Envelope[list[BudgetHeadOut]],
    dependencies=BUDGETS,
)
async def budgets_transfer(
    body: BudgetTransfer, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).transfer(body))


@router.post(
    "/accounting/budgets/submit",
    summary="Submit every draft head of a year (workflow)",
    response_model=Envelope[list[BudgetHeadOut]],
    dependencies=BUDGETS,
)
async def budgets_submit_all(
    request: Request,
    year: uuid.UUID | None = None,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).submit(None, year))


@router.get(
    "/accounting/budgets",
    summary="Budget heads (scoped)",
    response_model=Envelope[list[BudgetHeadOut]],
    dependencies=BUDGETS,
)
async def budgets(
    request: Request,
    year: uuid.UUID | None = None,
    college_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    status: str | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(principal, await BudgetService(db, principal, request).heads(year, college_id, department_id, status))


@router.post(
    "/accounting/budgets",
    status_code=201,
    summary="Create a budget head (draft)",
    response_model=Envelope[BudgetHeadOut],
    dependencies=BUDGETS,
)
async def budget_create(
    body: BudgetHeadIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).create(body))


@router.get(
    "/accounting/budgets/{id}", summary="Budget head", response_model=Envelope[BudgetHeadOut], dependencies=BUDGETS
)
async def budget_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).get(id))


@router.put(
    "/accounting/budgets/{id}",
    summary="Edit a budget head",
    response_model=Envelope[BudgetHeadOut],
    dependencies=BUDGETS,
)
async def budget_update(
    id: uuid.UUID,
    body: BudgetHeadUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).update(id, body))


@router.post(
    "/accounting/budgets/{id}/submit",
    summary="Submit a head (workflow)",
    response_model=Envelope[list[BudgetHeadOut]],
    dependencies=BUDGETS,
)
async def budget_submit(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).submit(id))


@router.post(
    "/accounting/budgets/{id}/approve",
    summary="Approve a head directly",
    response_model=Envelope[list[BudgetHeadOut]],
    dependencies=BUDGETS,
)
async def budget_approve(
    id: uuid.UUID, request: Request, principal: Principal = Depends(APPROVE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).approve([id]))


@router.post(
    "/accounting/budgets/{id}/revise",
    summary="Revise the allocation",
    response_model=Envelope[BudgetHeadOut],
    dependencies=BUDGETS,
)
async def budget_revise(
    id: uuid.UUID,
    body: BudgetRevise,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).revise(id, body))


@router.post(
    "/accounting/budgets/{id}/freeze",
    summary="Freeze a head",
    response_model=Envelope[BudgetHeadOut],
    dependencies=BUDGETS,
)
async def budget_freeze(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BudgetService(db, principal, request).freeze(id))


# ---- grants ---------------------------------------------------------------------------------------------------------------------
@router.get(
    "/accounting/grants",
    summary="Grant ledgers (own / all)",
    response_model=Envelope[list[GrantLedgerOut]],
    dependencies=GRANTS,
)
async def grants(
    request: Request, principal: Principal = Depends(GRANT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GrantService(db, principal, request).list_grants())


@router.post(
    "/accounting/grants",
    status_code=201,
    summary="Create a grant ledger",
    response_model=Envelope[GrantLedgerOut],
    dependencies=GRANTS,
)
async def grant_create(
    body: GrantLedgerIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GrantService(db, principal, request).create(body))


@router.get(
    "/accounting/grants/{id}/soe",
    summary="Statement of expenditure",
    response_model=Envelope[dict[str, Any]],
    dependencies=GRANTS,
)
async def grant_soe(
    id: uuid.UUID,
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(GRANT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrantService(db, principal, request).soe(id, date_from, date_to))


@router.get("/accounting/grants/{id}/uc.pdf", summary="Utilisation certificate (PDF)", dependencies=GRANTS)
async def grant_uc(
    id: uuid.UUID,
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(GRANT),
    db: AsyncSession = Depends(get_db),
) -> Response:
    from app.utils.pdf import simple_pdf

    title, lines = await GrantService(db, principal, request).uc_lines(id, date_from, date_to)
    return Response(content=simple_pdf(lines, title=title), media_type="application/pdf")


@router.get(
    "/accounting/grants/{id}", summary="Grant ledger", response_model=Envelope[GrantLedgerOut], dependencies=GRANTS
)
async def grant_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(GRANT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GrantService(db, principal, request).get(id))


@router.put(
    "/accounting/grants/{id}",
    summary="Edit a grant ledger",
    response_model=Envelope[GrantLedgerOut],
    dependencies=GRANTS,
)
async def grant_update(
    id: uuid.UUID,
    request: Request,
    name: str | None = None,
    funding_agency: str | None = None,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrantService(db, principal, request).update(id, name, funding_agency))


@router.post(
    "/accounting/grants/{id}/receipts",
    summary="Record a grant instalment",
    response_model=Envelope[GrantLedgerOut],
    dependencies=GRANTS,
)
async def grant_receipt(
    id: uuid.UUID,
    body: GrantReceipt,
    request: Request,
    principal: Principal = Depends(GRANT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrantService(db, principal, request).receipt(id, body))


@router.post(
    "/accounting/grants/{id}/expenses",
    summary="Record a grant expense (PI / accounts)",
    response_model=Envelope[GrantLedgerOut],
    dependencies=GRANTS,
)
async def grant_expense(
    id: uuid.UUID,
    body: GrantExpense,
    request: Request,
    principal: Principal = Depends(GRANT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrantService(db, principal, request).expense(id, body))


@router.post(
    "/accounting/grants/{id}/reallocate",
    summary="Reallocate between grant heads",
    response_model=Envelope[GrantLedgerOut],
    dependencies=GRANTS,
)
async def grant_reallocate(
    id: uuid.UUID,
    body: GrantReallocate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrantService(db, principal, request).reallocate(id, body))


@router.post(
    "/accounting/grants/{id}/close",
    summary="Close a grant (unspent → refund)",
    response_model=Envelope[GrantLedgerOut],
    dependencies=GRANTS,
)
async def grant_close(
    id: uuid.UUID,
    body: GrantClose,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrantService(db, principal, request).close(id, body))


# ---- reconciliation ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/accounting/reconciliations",
    summary="Bank reconciliations",
    response_model=Envelope[list[ReconciliationOut]],
    dependencies=CORE,
)
async def recons(
    request: Request, principal: Principal = Depends(RECON), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ReconciliationService(db, principal, request).list_recons())


@router.post(
    "/accounting/reconciliations",
    status_code=201,
    summary="Open a reconciliation (+ statement rows)",
    response_model=Envelope[ReconciliationOut],
    dependencies=CORE,
)
async def recon_create(
    body: ReconciliationCreate,
    request: Request,
    principal: Principal = Depends(RECON),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ReconciliationService(db, principal, request).create(body))


@router.get(
    "/accounting/reconciliations/{id}",
    summary="Reconciliation",
    response_model=Envelope[ReconciliationOut],
    dependencies=CORE,
)
async def recon_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RECON), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = ReconciliationService(db, principal, request)
    return ok(svc.out(await svc.row(id)))


@router.post(
    "/accounting/reconciliations/{id}/import",
    summary="Import statement rows (CSV) and auto-match",
    response_model=Envelope[ReconciliationOut],
    dependencies=CORE,
)
async def recon_import(
    id: uuid.UUID,
    body: ReconImport,
    request: Request,
    principal: Principal = Depends(RECON),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ReconciliationService(db, principal, request).import_csv(id, body.csv))


@router.post(
    "/accounting/reconciliations/{id}/match",
    summary="Match / explain a row",
    response_model=Envelope[ReconciliationOut],
    dependencies=CORE,
)
async def recon_match(
    id: uuid.UUID,
    body: ReconMatch,
    request: Request,
    principal: Principal = Depends(RECON),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ReconciliationService(db, principal, request).match(id, body))


@router.post(
    "/accounting/reconciliations/{id}/unmatch",
    summary="Undo a match",
    response_model=Envelope[ReconciliationOut],
    dependencies=CORE,
)
async def recon_unmatch(
    id: uuid.UUID,
    body: ReconMatch,
    request: Request,
    principal: Principal = Depends(RECON),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ReconciliationService(db, principal, request).match(id, body, unmatch=True))


@router.post(
    "/accounting/reconciliations/{id}/add-record",
    summary="Turn a row into a bank charge / interest record",
    response_model=Envelope[ReconciliationOut],
    dependencies=CORE,
)
async def recon_add(
    id: uuid.UUID,
    body: ReconAddRecord,
    request: Request,
    principal: Principal = Depends(RECON),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ReconciliationService(db, principal, request).add_record(id, body))


@router.post(
    "/accounting/reconciliations/{id}/close",
    summary="Close a reconciliation",
    response_model=Envelope[ReconciliationOut],
    dependencies=CORE,
)
async def recon_close(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RECON), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ReconciliationService(db, principal, request).close(id))


# ---- GST / exports / statements / periods / dashboard ------------------------------------------------------------------------------
@router.get(
    "/accounting/gst/summary",
    summary="GST summary for a month (YYYY-MM)",
    response_model=Envelope[GstReportOut],
    dependencies=GST,
)
async def gst_summary(
    request: Request,
    period: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FinanceService(db, principal, request).gst(period))


@router.get(
    "/accounting/gst/export",
    status_code=202,
    summary="GST CSV (job)",
    response_model=Envelope[AcctJobAccepted],
    dependencies=GST,
)
async def gst_export(
    request: Request,
    period: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _job(db, principal, "accounting.gst_export", {"period": period})


@router.get(
    "/accounting/exports", summary="Voucher exports", response_model=Envelope[list[ExportOut]], dependencies=TALLY
)
async def exports(
    request: Request, principal: Principal = Depends(EXPORT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FinanceService(db, principal, request).exports())


@router.post(
    "/accounting/exports",
    status_code=202,
    summary="Export vouchers (Tally XML / Zoho CSV / CSV; job)",
    response_model=Envelope[ExportOut],
    dependencies=TALLY,
)
async def export_create(
    body: ExportRequest, request: Request, principal: Principal = Depends(EXPORT), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    e = await FinanceService(db, principal, request).request_export(body)
    return JSONResponse(
        status_code=202,
        content=ok(ExportOut.model_validate(e, from_attributes=True).model_dump(mode="json"), message="Queued"),
    )


@router.get(
    "/accounting/exports/{id}",
    summary="Export (signed URL when ready)",
    response_model=Envelope[ExportOut],
    dependencies=TALLY,
)
async def export_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EXPORT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    rows = [e for e in await FinanceService(db, principal, request).exports() if e.id == id]
    if not rows:
        raise APIError(404, ErrorCode.NOT_FOUND, "Export not found")
    return ok(rows[0])


@router.get(
    "/accounting/statements/{kind}",
    summary="Receipts & payments / income & expenditure / balance summary",
    response_model=Envelope[StatementOut],
    dependencies=CORE,
)
async def statement(
    kind: str,
    request: Request,
    date_from: date = Query(..., alias="from"),
    date_to: date = Query(..., alias="to"),
    college_id: uuid.UUID | None = None,
    format: str = Query("json", pattern="^(json|pdf|xlsx)$"),
    principal: Principal = Depends(STMT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if kind not in STATEMENTS:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown statement")
    svc = FinanceService(db, principal, request)
    s = await svc.statement(kind, date_from, date_to, college_id)
    if format == "pdf":
        from app.utils.pdf import simple_pdf

        return _file(
            simple_pdf(await svc.statement_lines(s), title=kind.replace("_", " ").title()),
            "pdf",
            f"{kind}-{date_from}-{date_to}",
        )
    if format == "xlsx":
        return _file(await svc.statement_xlsx(s), "xlsx", f"{kind}-{date_from}-{date_to}")
    return ok(s)


@router.post(
    "/accounting/periods/close",
    summary="Close the books up to a date",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def period_close(
    body: PeriodClose, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FinanceService(db, principal, request).close_period(body.upto_date))


@router.post(
    "/accounting/years/close",
    status_code=202,
    summary="Financial / academic year close (job)",
    response_model=Envelope[AcctJobAccepted],
    dependencies=CORE,
)
async def year_close(
    body: YearClose, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return await _job(db, principal, "accounting.year_close", body.model_dump(mode="json"))


@router.get(
    "/accounting/dashboard", summary="Finance dashboard", response_model=Envelope[AcctDashboard], dependencies=CORE
)
async def dashboard(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FinanceService(db, principal, request).dashboard())


@router.post(
    "/accounting/attachments",
    status_code=201,
    summary="Upload a bill / voucher / receipt (returns the stored key)",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def attachment(
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(EXP),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.services.file_service import FileService

    saved = await FileService(db).save(
        file,
        "accounting",
        allowed_types=("application/pdf", "image/jpeg", "image/png", "image/webp"),
        max_mb=10,
        institution_id=principal.institution_id,
    )
    return ok({"document_url": saved.key})
