"""路由 - 工作台仪表板"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import Voucher, Company, User as UserModel
from app.models.misc import BankReceipt, Invoice, ClosingPeriod
from app.routers.auth import get_login_user, get_user_from_cookie, templates
from app.services.period_helper import get_target_period, get_current_period
from app.routers.setup import is_company_initialized


def get_closed_period_range(company_id: int, db: Session) -> str:
    """获取公司已结账的账套时长，如 '2024年01月 - 2026年06月'
    只计算已结账(is_closed=True)的记录，按期间排序取首尾"""
    periods = db.query(ClosingPeriod.period).filter(
        ClosingPeriod.company_id == company_id,
        ClosingPeriod.is_closed == True,
    ).order_by(ClosingPeriod.period).all()
    periods = [p[0] for p in periods]
    if not periods:
        return ""
    def fmt(p):
        parts = p.split("-")
        return f"{parts[0]}年{parts[1]}月"
    return f"{fmt(periods[0])} - {fmt(periods[-1])}"

router = APIRouter(prefix="/dashboard", tags=["工作台"])


def get_dashboard_data(company_id: int, period: str, db: Session) -> dict:
    """获取仪表板数据"""
    data = {}

    # 凭证统计（仅当前期间）
    def _vcount(status):
        return db.query(Voucher).filter(
            Voucher.company_id == company_id,
            func.strftime("%Y-%m", Voucher.date) == period,
            Voucher.status == status,
        ).count()
    data["voucher_counts"] = {
        "draft": _vcount("draft"),
        "pending": _vcount("pending"),
        "approved": _vcount("approved"),
        "posted": _vcount("posted"),
    }

    # 原始凭证统计
    data["receipt_count"] = db.query(BankReceipt).filter(
        BankReceipt.company_id == company_id).count()
    data["invoice_count"] = db.query(Invoice).filter(
        Invoice.company_id == company_id).count()

    # 结转结账状态
    cp = db.query(ClosingPeriod).filter(
        ClosingPeriod.company_id == company_id,
        ClosingPeriod.period == period,
    ).first()
    data["is_carried_forward"] = cp.is_carried_forward if cp else False
    data["is_closed"] = cp.is_closed if cp else False

    # 各期间草稿数量（供导航提示）
    draft_periods = db.query(
        func.strftime("%Y-%m", Voucher.date).label("p"),
        func.count(Voucher.id).label("c")
    ).filter(
        Voucher.company_id == company_id,
        Voucher.status == "draft",
    ).group_by(func.strftime("%Y-%m", Voucher.date)).order_by(
        func.strftime("%Y-%m", Voucher.date).desc()
    ).all()
    data["draft_periods"] = draft_periods

    return data


@router.get("/")
async def dashboard(request: Request, db: Session = Depends(get_db)):
    from datetime import datetime
    user = get_user_from_cookie(request, db)
    if not user:
        return templates(request, "login.html", {})

    if user.role == "super_admin":
        # 超级管理员总览：所有公司详情、凭证数、当前记账月份
        company_count = db.query(Company).count()
        user_count = db.query(UserModel).count()
        voucher_count = db.query(Voucher).count()
        companies = db.query(Company).order_by(Company.id).all()
        company_list = []
        for c in companies:
            admin = db.query(UserModel).filter(
                UserModel.company_id == c.id, UserModel.role == "company_admin"
            ).first()
            v_count = db.query(Voucher).filter(Voucher.company_id == c.id).count()
            v_posted = db.query(Voucher).filter(
                Voucher.company_id == c.id, Voucher.status == "posted"
            ).count()
            v_draft = db.query(Voucher).filter(
                Voucher.company_id == c.id, Voucher.status == "draft"
            ).count()
            # 查找最后一个过账凭证的月份
            last_v = db.query(Voucher).filter(
                Voucher.company_id == c.id, Voucher.status == "posted"
            ).order_by(Voucher.date.desc()).first()
            last_posted_period = ""
            if last_v:
                last_posted_period = last_v.date.strftime("%Y-%m")
            # 查找最新结账记录
            cp = db.query(ClosingPeriod).filter(
                ClosingPeriod.company_id == c.id
            ).order_by(ClosingPeriod.period.desc()).first()
            current_status = "未开始"
            if cp:
                if cp.is_closed:
                    current_status = f"已结账至{cp.period}"
                elif cp.is_carried_forward:
                    current_status = f"已结转至{cp.period}"
            if last_posted_period:
                current_status = f"记账至{last_posted_period}"
            from datetime import date as dt_date
            expiry_info = ""
            if c.expiry_type == "fixed" and c.expiry_date:
                days_left = (c.expiry_date - dt_date.today()).days
                if days_left <= 30:
                    expiry_info = f"剩{days_left}天" if days_left > 0 else "已过期"
                elif days_left <= 90:
                    expiry_info = f"剩{days_left}天"
            closed_range = get_closed_period_range(c.id, db)
            company_list.append({
                "id": c.id, "name": c.name, "code": c.code,
                "admin_name": admin.display_name if admin else "",
                "voucher_count": v_count,
                "v_posted": v_posted,
                "v_draft": v_draft,
                "current_status": current_status,
                "start_date": c.start_date.strftime("%Y-%m") if c.start_date else "",
                "expiry_info": expiry_info,
                "expiry_date": c.expiry_date.isoformat() if c.expiry_date else "",
                "is_expired": c.is_expired,
                "closed_range": closed_range,
            })
        # 统计快到期企业数
        expiring = [c for c in company_list if c["expiry_info"] and "过期" not in c["expiry_info"]]
        expired = [c for c in company_list if c.get("is_expired")]
        return templates(request, "dashboard.html", {
            "user": user, "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "company_count": company_count, "user_count": user_count,
            "voucher_count": voucher_count, "company_list": company_list,
            "expiring_count": len(expiring), "expired_count": len(expired),
        })

    if user.company_id:
        period = get_current_period(request, db, user.company_id)
        # 如果用户指定的期间已结账，自动切换到下一个未结账期间
        url_period = request.query_params.get("period", "")
        if url_period:
            target = get_target_period(db, user.company_id)
            cp = db.query(ClosingPeriod).filter(
                ClosingPeriod.company_id == user.company_id,
                ClosingPeriod.period == url_period,
                ClosingPeriod.is_closed == True,
            ).first()
            if cp and target != url_period:
                return RedirectResponse(url=f"/dashboard?period={target}", status_code=302)
    else:
        from datetime import date
        today = date.today()
        period = f"{today.year}-{today.month:02d}"

    data = {}
    company = None
    show_setup = False
    closed_range = ""

    if user.company_id:
        company = db.query(Company).filter(Company.id == user.company_id).first()
        if company and not company.is_initialized and user.role == "company_admin":
            show_setup = True
        data = get_dashboard_data(user.company_id, period, db)
        closed_range = get_closed_period_range(user.company_id, db)

    resp = templates(request, "dashboard.html", {
        "user": user, "company": company,
        "period": period, "data": data,
        "show_setup": show_setup,
        "closed_range": closed_range,
    })
    resp.set_cookie(key="current_period", value=period, max_age=86400, path="/")
    return resp
