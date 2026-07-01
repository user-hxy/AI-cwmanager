"""路由 - 报表管理"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Company
from app.models.misc import ReportCache
from app.routers.auth import get_login_user, templates
from app.routers.settings import get_setting
from app.services.report_service import (
    get_trial_balance,
    export_to_excel,
    export_to_excel_standard,
)
from app.services.standard_report_service import generate_standard_balance_sheet, generate_standard_income_statement
from app.services.summary_service import (
    check_summaries_exist,
    aggregate_balance_sheet,
    aggregate_income_statement,
    aggregate_trial_balance,
)
from app.services.report_pdf import (
    export_balance_sheet_pdf, export_income_statement_pdf, export_trial_balance_pdf,
)
from app.config import BASE_DIR
import os, shutil
from app.services.period_helper import get_target_period, get_current_period
from datetime import datetime, date as dt_date
import json

router = APIRouter(prefix="/reports", tags=["报表管理"])


def get_default_period(request: Request, db: Session) -> str:
    """获取默认会计期间（Cookie → 系统计算）"""
    from app.routers.auth import get_user_from_cookie
    user = get_user_from_cookie(request, db)
    if user and user.company_id:
        return get_current_period(request, db, user.company_id)
    return dt_date.today().strftime("%Y-%m")


def resolve_period(period_type: str, period_value: str) -> tuple:
    """将期间类型+值转为 (start, end, period_type, period_display)
    period_value 格式:
      month:     "2026-06"
      quarter:   "2026-2"
      half_year: "2026-H1" 或 "2026-H2"
      year:      "2026"
    返回: (start_ym, end_ym, period_type, period_display)
    """
    pv = period_value
    if period_type == "month":
        y, m = pv.split("-") if "-" in pv else (pv[:4], pv[4:6])
        pd = f"{y}年{int(m):02d}月"
        return (f"{y}-{m}", f"{y}-{m}", "month", pd)

    elif period_type == "quarter":
        parts = pv.split("-")
        y = parts[0]
        q = int(parts[1]) if len(parts) > 1 else 1
        sm = (q - 1) * 3 + 1
        em = q * 3
        pd = f"{y}年第{q}季度"
        return (f"{y}-{sm:02d}", f"{y}-{em:02d}", "quarter", pd)

    elif period_type == "half_year":
        parts = pv.split("-")
        y = parts[0]
        half = parts[1].upper() if len(parts) > 1 else "H1"
        if half == "H2":
            pd = f"{y}年下半年"
            return (f"{y}-07", f"{y}-12", "half_year", pd)
        else:
            pd = f"{y}年上半年"
            return (f"{y}-01", f"{y}-06", "half_year", pd)

    else:  # year
        y = pv[:4] if len(pv) >= 4 else pv
        pd = f"{y}年"
        return (f"{y}-01", f"{y}-12", "year", pd)


def parse_period_params(request: Request, db: Session) -> tuple:
    """从请求参数解析期间，返回 (start, end, period_type, period_value, period_display)
    始终返回有效的期间参数。
    """
    period_type = request.query_params.get("period_type", "")
    period_value = request.query_params.get("period_value", "")

    if period_type and period_value:
        start, end, pt, pd = resolve_period(period_type, period_value)
        return (start, end, pt, period_value, pd)

    # 默认当前会计期间
    default = get_default_period(request, db)
    return (default, default, "month", default, f"{int(default[:4])}年{int(default[5:7]):02d}月")


@router.get("/")
async def report_center(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    company = None
    if user.company_id:
        company = db.query(Company).filter(Company.id == user.company_id).first()
    return templates(request, "reports/index.html", {"user": user, "company": company})


def _report_context(request: Request, db: Session, user: User) -> dict:
    """生成报表页面公共上下文"""
    start, end, period_type, period_value, period_display = parse_period_params(request, db)
    company = db.query(Company).filter(Company.id == user.company_id).first()
    target_period = get_target_period(db, user.company_id)
    target_year = int(target_period[:4])
    return {
        "user": user, "company": company,
        "start": start, "end": end,
        "period_type": period_type, "period_value": period_value,
        "period_display": period_display,
        "target_period": target_period, "target_year": target_year,
    }


@router.get("/trial-balance")
async def trial_balance(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if not user.company_id:
        return templates(request, "login.html", {})
    ctx = _report_context(request, db, user)
    # 季/半年/年报优先从快照聚合
    if ctx["period_type"] != "month" and check_summaries_exist(user.company_id, ctx["start"], ctx["end"], db):
        data = aggregate_trial_balance(user.company_id, ctx["start"], ctx["end"], db)
        if data is not None:
            ctx["data"] = data
            return templates(request, "reports/trial_balance.html", ctx)
    ctx["data"] = get_trial_balance(user.company_id, ctx["start"], ctx["end"], db)
    return templates(request, "reports/trial_balance.html", ctx)


@router.get("/balance-sheet")
async def balance_sheet(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if not user.company_id:
        return templates(request, "login.html", {})
    ctx = _report_context(request, db, user)
    if ctx["period_type"] != "month" and check_summaries_exist(user.company_id, ctx["start"], ctx["end"], db):
        data = aggregate_balance_sheet(user.company_id, ctx["start"], ctx["end"], db)
        if data is not None:
            ctx["sheet"] = data
            return templates(request, "reports/balance_sheet.html", ctx)
    ctx["sheet"] = generate_standard_balance_sheet(user.company_id, ctx["start"], ctx["end"], db)
    return templates(request, "reports/balance_sheet.html", ctx)


@router.get("/income-statement")
async def income_statement(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if not user.company_id:
        return templates(request, "login.html", {})
    ctx = _report_context(request, db, user)
    if ctx["period_type"] != "month" and check_summaries_exist(user.company_id, ctx["start"], ctx["end"], db):
        data = aggregate_income_statement(user.company_id, ctx["start"], ctx["end"], db)
        if data is not None:
            ctx["statement"] = data
            return templates(request, "reports/income_statement.html", ctx)
    ctx["statement"] = generate_standard_income_statement(user.company_id, ctx["start"], ctx["end"], db)
    return templates(request, "reports/income_statement.html", ctx)


@router.get("/export")
async def export_report(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if not user.company_id:
        return Response("无权限")
    fmt = request.query_params.get("fmt", "excel")
    report_type = request.query_params.get("type", "balance")
    start, end, pt, pv, period_display = parse_period_params(request, db)

    if report_type == "balance":
        data = generate_standard_balance_sheet(user.company_id, start, end, db)
        data["period_display"] = period_display
        if fmt == "pdf":
            bs_ori = get_setting(db, user.company_id, "bs_orientation", "L")
            buf = export_balance_sheet_pdf(data, orientation=bs_ori)
            return Response(content=buf.getvalue(), media_type="application/pdf",
                            headers={"Content-Disposition": f"inline; filename=balance_sheet_{end}.pdf"})
        else:
            excel_bytes = export_to_excel_standard(data, report_type)
    elif report_type == "income":
        data = generate_standard_income_statement(user.company_id, start, end, db)
        data["period_display"] = period_display
        if fmt == "pdf":
            is_ori = get_setting(db, user.company_id, "is_orientation", "P")
            buf = export_income_statement_pdf(data, orientation=is_ori)
            return Response(content=buf.getvalue(), media_type="application/pdf",
                            headers={"Content-Disposition": f"inline; filename=income_statement_{end}.pdf"})
        else:
            excel_bytes = export_to_excel(data, report_type)
    else:
        from app.services.report_service import generate_cash_flow
        data = generate_cash_flow(user.company_id, start, end, db)
        if fmt == "pdf":
            buf = export_balance_sheet_pdf(data)
            return Response(content=buf.getvalue(), media_type="application/pdf",
                            headers={"Content-Disposition": f"inline; filename=report_{end}.pdf"})
        else:
            excel_bytes = export_to_excel(data, report_type)

    if fmt != "pdf":
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={report_type}_{end}.xlsx"},
        )


@router.get("/export-pdf")
async def export_report_pdf(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """导出报表PDF（使用系统设置中的方向配置）"""
    if not user.company_id:
        return Response("无权限")
    report_type = request.query_params.get("type", "balance")
    start, end, pt, pv, period_display = parse_period_params(request, db)

    company = db.query(Company).filter(Company.id == user.company_id).first()
    company_name = company.name if company else ""

    bs_ori = get_setting(db, user.company_id, "bs_orientation", "L")
    is_ori = get_setting(db, user.company_id, "is_orientation", "P")
    tb_ori = get_setting(db, user.company_id, "tb_orientation", "P")

    if report_type == "balance":
        data = generate_standard_balance_sheet(user.company_id, start, end, db)
        data["period_display"] = period_display
        buf = export_balance_sheet_pdf(data, orientation=bs_ori)
    elif report_type == "income":
        data = generate_standard_income_statement(user.company_id, start, end, db)
        data["period_display"] = period_display
        buf = export_income_statement_pdf(data, orientation=is_ori)
    else:
        data = get_trial_balance(user.company_id, start, end, db)
        buf = export_trial_balance_pdf(data, company_name, "", orientation=tb_ori, period_display=period_display)

    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename={report_type}_{end}.pdf"})


# ========== 历史报表管理 ==========


@router.get("/history")
async def report_history(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """历史报表查询"""
    if not user.company_id:
        return RedirectResponse(url="/dashboard", status_code=302)
    report_type = request.query_params.get("type", "")
    period_filter = request.query_params.get("period", "")
    query = db.query(ReportCache).filter(ReportCache.company_id == user.company_id)
    if report_type:
        query = query.filter(ReportCache.report_type == report_type)
    if period_filter:
        query = query.filter(ReportCache.period_type == period_filter)
    reports = query.order_by(ReportCache.created_at.desc()).all()
    report_types = {"trial_balance": "科目汇总表", "balance_sheet": "资产负债表", "income_statement": "利润表"}
    period_types = {"month": "月报", "quarter": "季报", "half_year": "半年报", "year": "年报"}
    return templates(request, "reports/history.html", {
        "user": user, "reports": reports,
        "report_type": report_type, "period_filter": period_filter,
        "report_types": report_types, "period_types": period_types,
    })


@router.post("/save")
async def save_report(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """保存当前报表（自动生成PDF并覆盖同类型同期间）"""
    if not user.company_id:
        return JSONResponse({"success": False, "msg": "无权限"})
    form = await request.form()
    report_type = form.get("type", "")
    period_type = form.get("period_type", "month")
    period_value = form.get("period_value", "")
    data_json = form.get("data", "{}")
    if not report_type or not period_value:
        return JSONResponse({"success": False, "msg": "参数不完整"})

    start, end, _, period_display = resolve_period(period_type, period_value)
    title = period_display if period_display else period_value

    # 生成PDF文件
    pdf_path = None
    if report_type in ("balance_sheet", "income_statement", "trial_balance"):
        try:
            reports_dir = BASE_DIR / "uploads" / "reports" / str(user.company_id) / start[:4]
            reports_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{report_type}_{start}_{end}.pdf"
            filepath = reports_dir / filename

            # 生成报表数据并导出PDF
            if report_type == "balance_sheet":
                from app.services.standard_report_service import generate_standard_balance_sheet
                data = generate_standard_balance_sheet(user.company_id, start, end, db)
                data["period_display"] = period_display
                ori = get_setting(db, user.company_id, "bs_orientation", "L")
                buf = export_balance_sheet_pdf(data, orientation=ori)
            elif report_type == "income_statement":
                from app.services.standard_report_service import generate_standard_income_statement
                data = generate_standard_income_statement(user.company_id, start, end, db)
                data["period_display"] = period_display
                ori = get_setting(db, user.company_id, "is_orientation", "P")
                buf = export_income_statement_pdf(data, orientation=ori)
            else:
                from app.services.report_service import get_trial_balance
                company = db.query(Company).filter(Company.id == user.company_id).first()
                data = get_trial_balance(user.company_id, start, end, db)
                ori = get_setting(db, user.company_id, "tb_orientation", "P")
                buf = export_trial_balance_pdf(data, company.name if company else "", "",
                                               orientation=ori, period_display=period_display)

            with open(filepath, "wb") as f:
                f.write(buf.getvalue())
            pdf_path = str(filepath)
        except Exception:
            pdf_path = None  # PDF生成失败不影响保存

    # 查重覆盖
    existing = db.query(ReportCache).filter(
        ReportCache.company_id == user.company_id,
        ReportCache.report_type == report_type,
        ReportCache.start_period == start,
        ReportCache.end_period == end,
    ).first()
    if existing:
        # 删除旧PDF
        if existing.pdf_path and os.path.exists(existing.pdf_path):
            try: os.remove(existing.pdf_path)
            except: pass
        existing.data = data_json
        existing.title = title
        existing.period_type = period_type
        existing.pdf_path = pdf_path
        existing.created_at = datetime.now()
        cache_obj = existing
    else:
        cache_obj = ReportCache(
            company_id=user.company_id, report_type=report_type,
            period_type=period_type, start_period=start, end_period=end,
            title=title, data=data_json, pdf_path=pdf_path,
        )
        db.add(cache_obj)
    db.commit()

    return JSONResponse({"success": True, "msg": "报表已保存", "has_pdf": pdf_path is not None})


@router.get("/load/{cache_id}")
async def load_report(cache_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """加载已保存的报表"""
    report = db.query(ReportCache).filter(
        ReportCache.id == cache_id, ReportCache.company_id == user.company_id
    ).first()
    if not report:
        return JSONResponse({"success": False, "msg": "报表不存在"})
    return JSONResponse({
        "success": True, "report": {
            "id": report.id, "type": report.report_type,
            "start": report.start_period, "end": report.end_period,
            "period_type": report.period_type,
            "title": report.title, "data": json.loads(report.data or "{}"),
        }
    })


@router.get("/download-pdf/{cache_id}")
async def download_report_pdf(cache_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """下载已保存报表的PDF"""
    report = db.query(ReportCache).filter(
        ReportCache.id == cache_id, ReportCache.company_id == user.company_id
    ).first()
    if not report or not report.pdf_path:
        return JSONResponse({"success": False, "msg": "PDF不存在"})
    if not os.path.exists(report.pdf_path):
        return JSONResponse({"success": False, "msg": "PDF文件已丢失"})
    from fastapi.responses import FileResponse
    return FileResponse(report.pdf_path, media_type="application/pdf",
                        filename=f"{report.title}.pdf")


@router.post("/delete/{cache_id}")
async def delete_report(cache_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """删除已保存的报表（同时删除PDF文件）"""
    report = db.query(ReportCache).filter(
        ReportCache.id == cache_id, ReportCache.company_id == user.company_id
    ).first()
    if not report:
        return JSONResponse({"success": False, "msg": "报表不存在"})
    # 删除关联PDF
    if report.pdf_path and os.path.exists(report.pdf_path):
        try:
            os.remove(report.pdf_path)
        except Exception:
            pass
    db.delete(report)
    db.commit()
    return JSONResponse({"success": True, "msg": "已删除"})


@router.get("/check-cache")
async def check_report_cache(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """检查指定期间是否已有缓存的报表"""
    if not user.company_id:
        return JSONResponse({"cached": False})
    report_type = request.query_params.get("type", "")
    period_type = request.query_params.get("period_type", "")
    period_value = request.query_params.get("period_value", "")
    if not period_type or not period_value:
        return JSONResponse({"cached": False})
    start, end, _, _ = resolve_period(period_type, period_value)
    cached = db.query(ReportCache).filter(
        ReportCache.company_id == user.company_id,
        ReportCache.report_type == report_type,
        ReportCache.start_period == start,
        ReportCache.end_period == end,
    ).first()
    if cached:
        return JSONResponse({
            "cached": True, "id": cached.id, "title": cached.title,
            "created_at": cached.created_at.isoformat() if cached.created_at else "",
        })
    return JSONResponse({"cached": False})
