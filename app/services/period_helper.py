"""期间辅助服务 - 自动定位到需要处理的月份"""
from datetime import date, datetime
from fastapi import Request
from sqlalchemy.orm import Session
from app.models import Company
from app.models.misc import ClosingPeriod


def get_target_period(db: Session, company_id: int, prefer_current: bool = False) -> str:
    """获取当前需要处理的会计期间

    规则：
    - 如果没有结账记录(新公司)，返回公司启用月份
    - 否则从启用月份开始，找第一个未结账的期间
    - 如果所有期间均已结账到当前月，返回当前月
    - 如果当前月已结账，返回下一个月（允许用户提前录入）
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company or not company.start_date:
        return date.today().strftime("%Y-%m")

    start_period = company.start_date.strftime("%Y-%m")
    today = date.today()
    today_period = today.strftime("%Y-%m")

    # 获取所有已结账期间
    closed_periods = set()
    records = db.query(ClosingPeriod).filter(
        ClosingPeriod.company_id == company_id
    ).all()
    for r in records:
        if r.is_closed:
            closed_periods.add(r.period)

    # 从启用月份开始往后找第一个未结账的期间
    year, month = int(start_period[:4]), int(start_period[5:7])
    max_iter = 60  # 最多找5年，防止死循环
    for _ in range(max_iter):
        p = f"{year}-{month:02d}"
        if p not in closed_periods:
            return p
        month += 1
        if month > 12:
            month = 1
            year += 1

    return today_period


def get_period_range(db: Session, company_id: int) -> tuple:
    """获取公司会计期间范围 (start_period, current_period)"""
    company = db.query(Company).filter(Company.id == company_id).first()
    start = company.start_date.strftime("%Y-%m") if company and company.start_date else date.today().strftime("%Y-%m")
    current = get_target_period(db, company_id)
    return start, current


def get_current_period(request: Request, db: Session, company_id: int) -> str:
    """获取当前会计期间（优先级：URL参数 > Cookie > 系统计算）"""
    period = request.query_params.get("period", "")
    if period:
        return period
    period = request.cookies.get("current_period", "")
    if period:
        return period
    return get_target_period(db, company_id)
