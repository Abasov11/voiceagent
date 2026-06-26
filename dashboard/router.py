"""Роутер дашборда: login, выход, страницы по ролям."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.auth import (
    COOKIE_MAX_AGE,
    COOKIE_NAME,
    can_see_all_managers,
    current_user,
    make_session_cookie,
    require_role,
    verify_password,
)
from shared.db import get_db
from shared.models import (
    CallSummary,
    DashboardRole,
    DashboardUser,
    Lead,
    LlmScore,
    Manager,
    ManagerCall,
    Transcript,
    ZvonarCall,
)
from shared.settings import get_settings

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> Response:
    user = db.scalar(select(DashboardUser).where(DashboardUser.email == email.lower()))
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Неверный email или пароль"},
            status_code=400,
        )
    cookie = make_session_cookie(user.id)
    redirect = RedirectResponse(url="/dashboard/", status_code=303)
    redirect.set_cookie(
        COOKIE_NAME,
        cookie,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="lax",
    )
    return redirect


@router.post("/logout")
def logout() -> Response:
    redirect = RedirectResponse(url="/dashboard/login", status_code=303)
    redirect.delete_cookie(COOKIE_NAME)
    return redirect


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    user: DashboardUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    from sqlalchemy import func

    from shared.models import ApiCallLog

    last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    manager_calls_q = db.query(ManagerCall).filter(ManagerCall.started_at >= last_24h)
    if not can_see_all_managers(user):
        manager_calls_q = manager_calls_q.filter(ManagerCall.manager_id == user.manager_id)
    manager_calls_24h = manager_calls_q.count()

    can_see_all = can_see_all_managers(user)
    zvonar_24h = (
        db.query(ZvonarCall).filter(ZvonarCall.started_at >= last_24h).count()
        if can_see_all
        else 0
    )
    leads_total = db.query(Lead).count() if can_see_all else 0
    leads_24h = (
        db.query(Lead).filter(Lead.created_at >= last_24h).count() if can_see_all else 0
    )
    interested_24h = (
        db.query(ZvonarCall)
        .filter(ZvonarCall.started_at >= last_24h, ZvonarCall.outcome == "interested")
        .count()
        if can_see_all
        else 0
    )
    avg_score = None
    if can_see_all:
        from shared.models import CallSummary as _CS
        avg_score = (
            db.query(func.avg(_CS.total_score))
            .filter(_CS.created_at >= last_24h)
            .scalar()
        )
    api_cost_cents_24h = 0
    api_errors_24h = 0
    cost_breakdown_24h = None
    cost_breakdown_7d = None
    cost_breakdown_30d = None
    if can_see_all:
        api_cost_cents_24h = (
            db.query(func.coalesce(func.sum(ApiCallLog.cost_cents), 0))
            .filter(ApiCallLog.created_at >= last_24h)
            .scalar()
            or 0
        )
        api_errors_24h = (
            db.query(ApiCallLog)
            .filter(ApiCallLog.created_at >= last_24h, ApiCallLog.status == "error")
            .count()
        )
        # Unit-economics из call_cost_breakdown — owner only.
        from shared.models import CallCostBreakdown as _CCB

        def _agg(since):
            row = (
                db.query(
                    func.coalesce(func.sum(_CCB.sip_cost_cents), 0),
                    func.coalesce(func.sum(_CCB.tts_cost_cents), 0),
                    func.coalesce(func.sum(_CCB.stt_cost_cents), 0),
                    func.coalesce(func.sum(_CCB.llm_cost_cents), 0),
                    func.coalesce(func.sum(_CCB.total_cost_cents), 0),
                    func.count(_CCB.id),
                )
                .filter(_CCB.created_at >= since)
                .first()
            )
            return {
                "sip":    int(row[0]) / 100,
                "tts":    int(row[1]) / 100,
                "stt":    int(row[2]) / 100,
                "llm":    int(row[3]) / 100,
                "total":  int(row[4]) / 100,
                "calls":  int(row[5]),
            }

        if user.role == DashboardRole.owner.value:
            now = datetime.now(timezone.utc)
            cost_breakdown_24h = _agg(now - timedelta(hours=24))
            cost_breakdown_7d  = _agg(now - timedelta(days=7))
            cost_breakdown_30d = _agg(now - timedelta(days=30))

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "active_page": "home",
            "user": user,
            "manager_calls_24h": manager_calls_24h,
            "zvonar_24h": zvonar_24h,
            "leads_total": leads_total,
            "leads_24h": leads_24h,
            "interested_24h": interested_24h,
            "avg_score": float(avg_score) if avg_score is not None else None,
            "api_cost_dollars_24h": round(int(api_cost_cents_24h) / 100, 2),
            "api_errors_24h": api_errors_24h,
            "cost_breakdown_24h": cost_breakdown_24h,
            "cost_breakdown_7d":  cost_breakdown_7d,
            "cost_breakdown_30d": cost_breakdown_30d,
        },
    )


def _manager_calls_query(
    db: Session,
    user: DashboardUser,
    *,
    manager_id: int | None,
    date_from: str | None,
    date_to: str | None,
    has_transcript: str | None,
):
    q = db.query(ManagerCall).order_by(ManagerCall.started_at.desc())
    if not can_see_all_managers(user):
        q = q.filter(ManagerCall.manager_id == user.manager_id)
    elif manager_id:
        q = q.filter(ManagerCall.manager_id == manager_id)
    if date_from:
        try:
            q = q.filter(ManagerCall.started_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(ManagerCall.started_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass
    if has_transcript == "yes":
        q = q.join(Transcript, isouter=False)
    elif has_transcript == "no":
        q = q.outerjoin(Transcript).filter(Transcript.id.is_(None))
    return q


@router.get("/manager-calls", response_class=HTMLResponse)
def manager_calls(
    request: Request,
    user: DashboardUser = Depends(current_user),
    db: Session = Depends(get_db),
    manager_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    has_transcript: str | None = None,
    page: int = 0,
    page_size: int = 50,
) -> Response:
    base_q = _manager_calls_query(
        db, user,
        manager_id=manager_id,
        date_from=date_from,
        date_to=date_to,
        has_transcript=has_transcript,
    )
    total = base_q.count()
    rows = base_q.offset(page * page_size).limit(page_size).all()
    managers = (
        db.query(Manager).order_by(Manager.name).all()
        if can_see_all_managers(user) else []
    )
    return templates.TemplateResponse(
        request,
        "manager_calls.html",
        {
            "active_page": "manager_calls",
            "user": user,
            "rows": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "managers": managers,
            "filters": {
                "manager_id": manager_id,
                "date_from": date_from or "",
                "date_to": date_to or "",
                "has_transcript": has_transcript or "",
            },
        },
    )


@router.get("/manager-calls.csv")
def manager_calls_csv(
    user: DashboardUser = Depends(require_role(
        DashboardRole.owner.value, DashboardRole.director.value, DashboardRole.rop.value
    )),
    db: Session = Depends(get_db),
    manager_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    has_transcript: str | None = None,
) -> Response:
    import csv, io
    rows = _manager_calls_query(
        db, user, manager_id=manager_id, date_from=date_from, date_to=date_to,
        has_transcript=has_transcript,
    ).limit(10000).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "started_at", "manager", "phone", "duration_s", "recording", "total_score", "funnel_stage"])
    for c in rows:
        w.writerow([
            c.id,
            c.started_at.isoformat() if c.started_at else "",
            c.manager.name if c.manager else "",
            c.phone or "",
            c.duration_s,
            c.recording_url_cloudinary or c.recording_url_remote or "",
            (c.summary.total_score if c.summary else ""),
            (c.summary.funnel_stage if c.summary else ""),
        ])
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="manager-calls.csv"'},
    )


@router.get("/manager-calls/{call_id}", response_class=HTMLResponse)
def manager_call_detail(
    call_id: int,
    request: Request,
    user: DashboardUser = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    call = db.get(ManagerCall, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="call not found")
    if not can_see_all_managers(user) and call.manager_id != user.manager_id:
        raise HTTPException(status_code=403, detail="forbidden")
    transcript = (
        db.query(Transcript).filter(Transcript.call_id == call.id).one_or_none()
    )
    scores = (
        db.query(LlmScore)
        .filter(LlmScore.call_id == call.id)
        .order_by(LlmScore.id)
        .all()
    )
    summary = (
        db.query(CallSummary).filter(CallSummary.call_id == call.id).one_or_none()
    )
    return templates.TemplateResponse(
        request,
        "manager_call_detail.html",
        {
            "active_page": "manager_calls",
            "user": user,
            "call": call,
            "transcript": transcript,
            "scores": scores,
            "summary": summary,
        },
    )


def _zvonar_query(
    db: Session,
    *,
    outcome: str | None,
    segment: str | None,
    date_from: str | None,
    date_to: str | None,
):
    q = db.query(ZvonarCall).order_by(ZvonarCall.started_at.desc())
    if outcome:
        q = q.filter(ZvonarCall.outcome == outcome)
    if segment:
        q = q.join(Lead, ZvonarCall.lead_id == Lead.id).filter(Lead.segment == segment)
    if date_from:
        try:
            q = q.filter(ZvonarCall.started_at >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(ZvonarCall.started_at <= datetime.fromisoformat(date_to))
        except ValueError:
            pass
    return q


@router.get("/zvonar", response_class=HTMLResponse)
def zvonar_calls(
    request: Request,
    user: DashboardUser = Depends(require_role(
        DashboardRole.owner.value, DashboardRole.director.value, DashboardRole.rop.value
    )),
    db: Session = Depends(get_db),
    outcome: str | None = None,
    segment: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 0,
    page_size: int = 50,
) -> Response:
    base_q = _zvonar_query(db, outcome=outcome, segment=segment, date_from=date_from, date_to=date_to)
    total = base_q.count()
    rows = base_q.offset(page * page_size).limit(page_size).all()
    return templates.TemplateResponse(
        request,
        "zvonar.html",
        {
            "active_page": "zvonar",
            "user": user,
            "rows": rows,
            "page": page,
            "page_size": page_size,
            "total": total,
            "filters": {
                "outcome": outcome or "",
                "segment": segment or "",
                "date_from": date_from or "",
                "date_to": date_to or "",
            },
        },
    )


@router.get("/zvonar.csv")
def zvonar_calls_csv(
    user: DashboardUser = Depends(require_role(
        DashboardRole.owner.value, DashboardRole.director.value, DashboardRole.rop.value
    )),
    db: Session = Depends(get_db),
    outcome: str | None = None,
    segment: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> Response:
    import csv, io
    rows = _zvonar_query(
        db, outcome=outcome, segment=segment, date_from=date_from, date_to=date_to
    ).limit(10000).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "started_at", "lead_id", "lead_name", "phone", "segment", "duration_s", "outcome"])
    for z in rows:
        w.writerow([
            z.id,
            z.started_at.isoformat() if z.started_at else "",
            z.lead_id,
            (z.lead.name if z.lead else "") or "",
            (z.lead.phone if z.lead else "") or "",
            (z.lead.segment if z.lead else "") or "",
            z.duration_s,
            z.outcome,
        ])
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="zvonar-calls.csv"'},
    )


@router.get("/leads", response_class=HTMLResponse)
def leads_list(
    request: Request,
    user: DashboardUser = Depends(current_user),
    db: Session = Depends(get_db),
    q: str = "",
    segment: str = "",
    page: int = 0,
    page_size: int = 50,
) -> Response:
    query = db.query(Lead).order_by(Lead.id.desc())
    if q:
        like = f"%{q}%"
        query = query.filter((Lead.phone.ilike(like)) | (Lead.name.ilike(like)))
    if segment:
        query = query.filter(Lead.segment == segment)
    total = query.count()
    rows = query.offset(page * page_size).limit(page_size).all()
    return templates.TemplateResponse(
        request,
        "leads.html",
        {
            "active_page": "leads",
            "user": user,
            "rows": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "q": q,
            "segment": segment,
        },
    )


@router.post("/leads/sync-alfa-crm")
async def leads_sync_alfa_crm(
    user: DashboardUser = Depends(require_role(DashboardRole.owner.value)),
) -> Response:
    from shared.alfacrm_sync import sync_all

    stats = await sync_all()
    redirect = RedirectResponse(url="/dashboard/leads", status_code=303)
    redirect.set_cookie(
        "flash",
        f"sync OK — total={stats['total']} new={stats['inserted']} upd={stats['updated']}",
        max_age=10,
    )
    return redirect


@router.post("/leads/upload-csv")
async def leads_upload_csv(
    user: DashboardUser = Depends(require_role(DashboardRole.owner.value)),
    file: UploadFile = File(...),
) -> Response:
    """Owner-only: ручной импорт CSV-базы лидов .

    Формат CSV — см. `zvonar/csv_loader.py`. Файл сохраняется во временную директорию,
    проходит через тот же loader. Возвращает flash с inserted/skipped/total.
    """
    import tempfile
    from pathlib import Path as _Path

    from zvonar.csv_loader import load_csv_stats

    if file is None:
        return RedirectResponse(url="/dashboard/leads", status_code=303)
    suffix = ".csv" if not (file.filename or "").lower().endswith(".csv") else ".csv"
    with tempfile.NamedTemporaryFile(prefix="leads-", suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = _Path(tmp.name)
    try:
        stats = load_csv_stats(tmp_path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    redirect = RedirectResponse(url="/dashboard/leads", status_code=303)
    redirect.set_cookie(
        "flash",
        f"CSV импорт — total={stats['total']} new={stats['inserted']} skipped={stats['skipped']}",
        max_age=10,
    )
    return redirect


@router.get("/users", response_class=HTMLResponse)
def users_list(
    request: Request,
    user: DashboardUser = Depends(require_role(DashboardRole.owner.value)),
    db: Session = Depends(get_db),
) -> Response:
    users = db.query(DashboardUser).order_by(DashboardUser.id).all()
    managers = db.query(Manager).order_by(Manager.id).all()
    return templates.TemplateResponse(
        request, "users.html", {"active_page": "users", "user": user, "users": users, "managers": managers}
    )


@router.post("/users/create")
def users_create(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("manager"),
    full_name: str = Form(""),
    manager_id: str = Form(""),
    user: DashboardUser = Depends(require_role(DashboardRole.owner.value)),
    db: Session = Depends(get_db),
) -> Response:
    from shared.auth import hash_password

    existing = db.scalar(select(DashboardUser).where(DashboardUser.email == email.lower()))
    if existing:
        redirect = RedirectResponse(url="/dashboard/users", status_code=303)
        redirect.set_cookie("flash", f"Пользователь {email} уже существует", max_age=10)
        return redirect

    new_user = DashboardUser(
        email=email.lower().strip(),
        password_hash=hash_password(password),
        full_name=full_name.strip() or None,
        role=role if role in [r.value for r in DashboardRole] else DashboardRole.manager.value,
        manager_id=int(manager_id) if manager_id else None,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    redirect = RedirectResponse(url="/dashboard/users", status_code=303)
    redirect.set_cookie("flash", f"Пользователь {email} создан", max_age=10)
    return redirect
