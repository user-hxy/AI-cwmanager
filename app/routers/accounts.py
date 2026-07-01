"""路由 - 科目管理"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Account, User
from app.routers.auth import get_login_user, templates, require_active_company

router = APIRouter(prefix="/accounts", tags=["科目管理"])


@router.get("/")
async def account_list(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if not user.company_id:
        return RedirectResponse(url="/dashboard", status_code=302)
    accounts = db.query(Account).filter(Account.company_id == user.company_id).order_by(Account.code).all()
    # 按类别分组
    categories = ["资产", "负债", "权益", "成本", "损益"]
    grouped = {}
    for cat in categories:
        grouped[cat] = [a for a in accounts if a.category == cat]
    return templates(request, "accounts/list.html", {"grouped": grouped, "categories": categories, "accounts": accounts, "user": user})


@router.get("/add")
async def account_add_page(request: Request, user: User = Depends(get_login_user)):
    if user.role not in ("super_admin", "company_admin"):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates(request, "accounts/form.html", {"user": user})


@router.post("/add")
async def account_add(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    category: str = Form(...),
    direction: str = Form("借"),
    parent_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_active_company),
):
    if user.role not in ("super_admin", "company_admin"):
        return RedirectResponse(url="/dashboard", status_code=302)
    acct = Account(
        company_id=user.company_id,
        code=code, name=name, category=category,
        direction=direction, is_detail=True,
        level=2, parent_id=int(parent_id) if parent_id else None,
    )
    db.add(acct)
    db.commit()
    return RedirectResponse(url="/accounts/", status_code=302)
