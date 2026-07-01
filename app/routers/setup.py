"""路由 - 企业初始化（期初余额设置）"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import date
from app.database import get_db
from app.models import Account, AccountBalance, Company, User
from app.routers.auth import get_login_user, templates, require_active_company

router = APIRouter(prefix="/setup", tags=["初始化"])


def is_company_initialized(db: Session, company_id: int) -> bool:
    """检查公司是否已完成初始化"""
    company = db.query(Company).filter(Company.id == company_id).first()
    return company.is_initialized if company else False


@router.get("/")
async def setup_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """期初设置页面（已初始化后仍可访问调整）"""
    if not user.company_id:
        return RedirectResponse(url="/dashboard", status_code=302)
    if user.role not in ("company_admin", "super_admin"):
        return RedirectResponse(url="/dashboard", status_code=302)

    company = db.query(Company).filter(Company.id == user.company_id).first()

    accounts = db.query(Account).filter(
        Account.company_id == user.company_id,
    ).order_by(Account.code).all()

    # 读取已存在的期初余额
    start_period = company.start_date.strftime("%Y-%m") if company.start_date else date.today().strftime("%Y-%m")
    existing_balances = {}
    if start_period:
        balances = db.query(AccountBalance).filter(
            AccountBalance.company_id == user.company_id,
            AccountBalance.period == start_period,
        ).all()
        for b in balances:
            existing_balances[b.account_id] = b.opening_balance

    # 按标准资产负债表布局分组
    from app.standard_layouts import BS_LEFT_ASSETS, BS_RIGHT_LIABILITIES_EQUITY

    def _group_accounts_by_layout(items, accts):
        """将账户按标准布局项目分组
        返回: [{"name","line_no","is_header":bool,"is_calc":bool,"is_display":bool,"accounts":list或None}]
        """
        result = []
        for name, line_no, codes, item_type in items:
            is_h = (item_type == 'header')
            is_c = (item_type == 'calc')
            is_d = (item_type == 'display')
            if codes is None:
                result.append({"name": name, "line_no": line_no or "", "is_header": is_h, "is_calc": True, "is_display": False, "accounts": None})
            elif not codes:
                result.append({"name": name, "line_no": line_no or "", "is_header": is_h, "is_calc": False, "is_display": is_d, "accounts": []})
            else:
                matched = [a for a in accts if any(a.code.startswith(p) for p in codes)]
                result.append({"name": name, "line_no": line_no or "", "is_header": is_h, "is_calc": False, "is_display": is_d, "accounts": matched or []})
        return result

    left_groups = _group_accounts_by_layout(BS_LEFT_ASSETS, accounts)
    right_groups = _group_accounts_by_layout(BS_RIGHT_LIABILITIES_EQUITY, accounts)

    start_date_str = company.start_date.isoformat() if company.start_date else ""

    return templates(request, "setup/index.html", {
        "user": user, "company": company,
        "accounts": accounts, "period": start_period,
        "existing_balances": existing_balances,
        "is_initialized": company.is_initialized,
        "left_groups": left_groups, "right_groups": right_groups,
        "start_date_str": start_date_str,
    })


@router.post("/save")
async def setup_save(request: Request, db: Session = Depends(get_db), user: User = Depends(require_active_company)):
    """保存期初余额设置及启用日期"""
    if not user.company_id or user.role not in ("company_admin", "super_admin"):
        return JSONResponse({"success": False, "msg": "无权限"})

    company = db.query(Company).filter(Company.id == user.company_id).first()
    if not company:
        return JSONResponse({"success": False, "msg": "公司不存在"})

    form = await request.form()

    # 更新启用日期
    start_date_str = form.get("start_date", "").strip()
    if start_date_str:
        try:
            new_start = date.fromisoformat(start_date_str)
            old_start = company.start_date
            company.start_date = new_start
        except ValueError:
            return JSONResponse({"success": False, "msg": "日期格式错误，请使用 YYYY-MM-DD"})
    else:
        new_start = company.start_date or date.today()

    start_period = new_start.strftime("%Y-%m")

    accounts = db.query(Account).filter(Account.company_id == user.company_id).all()

    # 先清理旧的余额记录
    db.query(AccountBalance).filter(
        AccountBalance.company_id == user.company_id,
        AccountBalance.period == start_period,
    ).delete()

    total_debit = 0.0
    total_credit = 0.0

    for acct in accounts:
        amount_str = form.get(f"balance_{acct.id}", "").strip()
        try:
            amount = float(amount_str) if amount_str else 0.0
        except ValueError:
            amount = 0.0

        bal = AccountBalance(
            company_id=user.company_id,
            account_id=acct.id,
            period=start_period,
            opening_balance=amount,
            debit_amount=0,
            credit_amount=0,
            closing_balance=amount,
        )
        db.add(bal)

        if amount != 0:
            if acct.category in ("资产", "成本"):
                total_debit += amount
            else:
                total_credit += amount

    # 校验借贷平衡
    if abs(total_debit - total_credit) > 0.01:
        db.rollback()
        return JSONResponse({
            "success": False,
            "msg": f"期初余额借贷不平衡: 借方={total_debit:.2f}, 贷方={total_credit:.2f}，请修正后重试",
        })

    company.is_initialized = True
    db.commit()
    return JSONResponse({"success": True, "msg": "期初设置已保存"})


@router.post("/skip")
async def setup_skip(request: Request, db: Session = Depends(get_db), user: User = Depends(require_active_company)):
    """跳过期初设置"""
    if not user.company_id or user.role not in ("company_admin", "super_admin"):
        return JSONResponse({"success": False, "msg": "无权限"})
    company = db.query(Company).filter(Company.id == user.company_id).first()
    if company:
        company.is_initialized = True
        start_period = company.start_date.strftime("%Y-%m") if company.start_date else date.today().strftime("%Y-%m")
        accounts = db.query(Account).filter(Account.company_id == user.company_id).all()
        for acct in accounts:
            existing = db.query(AccountBalance).filter(
                AccountBalance.company_id == user.company_id,
                AccountBalance.account_id == acct.id,
                AccountBalance.period == start_period,
            ).first()
            if not existing:
                db.add(AccountBalance(
                    company_id=user.company_id, account_id=acct.id,
                    period=start_period, opening_balance=0,
                    debit_amount=0, credit_amount=0, closing_balance=0,
                ))
        db.commit()
    return JSONResponse({"success": True, "msg": "已跳过"})
