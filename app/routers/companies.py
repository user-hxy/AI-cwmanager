"""路由 - 公司管理"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Company, User, Account
from app.models.misc import ClosingPeriod, AuditLog, AIPointBalance, AIRecharge
from app.routers.auth import get_login_user, templates
from app.routers.dashboard import get_closed_period_range
from app.services.auth_service import hash_password, log_audit
from app.config import DEFAULT_ACCOUNTS
from datetime import date

router = APIRouter(prefix="/companies", tags=["公司管理"])


@router.get("/")
async def company_list(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    companies = db.query(Company).order_by(Company.id).all()
    ai_data = {}
    for c in companies:
        c.closed_range = get_closed_period_range(c.id, db)
        bal = db.query(AIPointBalance).filter(AIPointBalance.company_id == c.id).first()
        ai_data[c.id] = bal.balance if bal else 0
    return templates(request, "companies/list.html", {"companies": companies, "user": user, "ai_data": ai_data})


@router.get("/add")
async def company_add_page(request: Request, user: User = Depends(get_login_user)):
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates(request, "companies/form.html", {"user": user, "edit_mode": False})


@router.post("/add")
async def company_add(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    tax_id: str = Form(""),
    start_date: str = Form(""),
    industry: str = Form(""),
    admin_username: str = Form(...),
    admin_password: str = Form(...),
    admin_display: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)

    try:
        # 检查公司编码和用户名是否已存在
        existing = db.query(Company).filter(Company.code == code).first()
        if existing:
            return templates(request, "companies/form.html", {
                "user": user, "edit_mode": False,
                "error": f"公司编码「{code}」已被使用",
            })
        existing_user = db.query(User).filter(User.username == admin_username).first()
        if existing_user:
            return templates(request, "companies/form.html", {
                "user": user, "edit_mode": False,
                "error": f"用户名「{admin_username}」已被使用",
            })

        company = Company(name=name, code=code, tax_id=tax_id, industry=industry)
        if start_date:
            company.start_date = date.fromisoformat(start_date)
        db.add(company)
        db.flush()

        admin = User(
            company_id=company.id,
            username=admin_username,
            display_name=admin_display or admin_username,
            password_hash=hash_password(admin_password),
            role="company_admin",
        )
        db.add(admin)

        for ac_code, ac_name, category, is_system, is_neg in DEFAULT_ACCOUNTS:
            if is_neg:
                direction = "贷"
            elif category in ("负债", "权益"):
                direction = "贷"
            elif category == "损益":
                from app.config import INCOME_ACCOUNT_CODES
                direction = "贷" if ac_code in INCOME_ACCOUNT_CODES else "借"
            else:
                direction = "借"
            acct = Account(
                company_id=company.id, code=ac_code, name=ac_name,
                category=category, direction=direction,
                is_detail=True, is_system=True, level=1,
            )
            db.add(acct)
        db.commit()

        log_audit(db, user.id, user.username, "create_company", "company", company.id,
                  f"创建公司: {name}")
        return RedirectResponse(url="/companies/", status_code=302)
    except Exception as e:
        db.rollback()
        return templates(request, "companies/form.html", {
            "user": user, "edit_mode": False,
            "error": f"创建失败: {str(e)}",
        })


@router.get("/{company_id}")
async def company_detail(request: Request, company_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    company = db.query(Company).filter(Company.id == company_id).first()
    company.closed_range = get_closed_period_range(company_id, db)
    users = db.query(User).filter(User.company_id == company_id).all()
    periods = db.query(ClosingPeriod).filter(ClosingPeriod.company_id == company_id).order_by(ClosingPeriod.period.desc()).all()
    bal = db.query(AIPointBalance).filter(AIPointBalance.company_id == company_id).first()
    ai_balance = bal.balance if bal else 0
    recharges = db.query(AIRecharge).filter(AIRecharge.company_id == company_id).order_by(AIRecharge.created_at.desc()).limit(20).all()
    return templates(request, "companies/detail.html", {
        "company": company, "users": users, "periods": periods,
        "user": user, "ai_balance": ai_balance, "recharges": recharges,
    })


@router.get("/edit/{company_id}")
async def company_edit_page(request: Request, company_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """编辑公司页面（含时效设置）"""
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        return RedirectResponse(url="/companies/", status_code=302)
    return templates(request, "companies/form.html", {"user": user, "edit_mode": True, "company": company})


@router.post("/edit/{company_id}")
async def company_edit_save(
    request: Request,
    company_id: int,
    name: str = Form(...),
    tax_id: str = Form(""),
    start_date: str = Form(""),
    industry: str = Form(""),
    contact_person: str = Form(""),
    contact_phone: str = Form(""),
    expiry_type: str = Form("permanent"),
    expiry_date: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """保存公司编辑（含时效设置）"""
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        return RedirectResponse(url="/companies/", status_code=302)

    company.name = name
    company.tax_id = tax_id
    company.industry = industry
    company.contact_person = contact_person
    company.contact_phone = contact_phone
    company.start_date = date.fromisoformat(start_date) if start_date else None

    # 时效设置
    company.expiry_type = expiry_type
    company.expiry_date = None
    if expiry_type == "fixed" and expiry_date:
        company.expiry_date = date.fromisoformat(expiry_date)

    db.commit()
    log_audit(db, user.id, user.username, "update_company", "company", company.id,
              f"编辑公司信息，使用时效: {company.expiry_display}")
    return RedirectResponse(url=f"/companies/{company_id}", status_code=302)


@router.post("/{company_id}/delete")
async def delete_company(
    company_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """删除公司及所有关联数据"""
    if user.role != "super_admin":
        return RedirectResponse(url="/companies/", status_code=302)
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        return RedirectResponse(url="/companies/", status_code=302)

    # 级联删除所有关联数据
    from app.models import Account, AccountBalance, Voucher, VoucherEntry
    from app.models.misc import (
        BankReceipt, Invoice, ClosingPeriod, Attachment, SceneRule,
        KeyWordMapping, SystemSetting, AuditLog, ReportCache,
    )

    # 1. 凭证分录
    voucher_ids = [v[0] for v in db.query(Voucher.id).filter(Voucher.company_id == company_id).all()]
    if voucher_ids:
        db.query(VoucherEntry).filter(VoucherEntry.voucher_id.in_(voucher_ids)).delete(synchronize_session=False)
    db.query(Voucher).filter(Voucher.company_id == company_id).delete()

    # 2. 科目与余额
    db.query(AccountBalance).filter(AccountBalance.company_id == company_id).delete()
    db.query(Account).filter(Account.company_id == company_id).delete()

    # 3. 银行回单、发票
    db.query(BankReceipt).filter(BankReceipt.company_id == company_id).delete()
    db.query(Invoice).filter(Invoice.company_id == company_id).delete()

    # 4. 业务场景、关键词映射
    db.query(SceneRule).filter(SceneRule.company_id == company_id).delete()
    db.query(KeyWordMapping).filter(KeyWordMapping.company_id == company_id).delete()

    # 5. 系统设置、审计日志、报表缓存
    db.query(SystemSetting).filter(SystemSetting.company_id == company_id).delete()
    db.query(ReportCache).filter(ReportCache.company_id == company_id).delete()
    db.query(AuditLog).filter(AuditLog.company_id == company_id).delete()

    # 6. 附件
    db.query(Attachment).filter(Attachment.company_id == company_id).delete()

    # 7. 结账记录
    db.query(ClosingPeriod).filter(ClosingPeriod.company_id == company_id).delete()

    # 8. 用户
    db.query(User).filter(User.company_id == company_id).delete()

    # 9. 最后删除公司本身
    db.delete(company)
    db.commit()

    log_audit(db, user.id, user.username, "delete_company", "company", company_id,
              f"删除公司: {company.name}")
    return RedirectResponse(url="/companies/", status_code=302)
