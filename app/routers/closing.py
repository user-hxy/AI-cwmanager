"""路由 - 期末处理（结转损益、月末结账、反结账、反结转）"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime
from app.database import get_db
from app.models import User, Voucher, Company
from app.models.misc import ClosingPeriod, AuditLog, ReportCache
from app.routers.auth import get_login_user, templates, require_active_company
from app.services.closing_service import carry_forward, reverse_carry_forward
from app.services.period_helper import get_target_period, get_period_range
from app.services.standard_report_service import generate_standard_balance_sheet, generate_standard_income_statement
from app.services.report_service import get_trial_balance
from app.services.report_pdf import export_balance_sheet_pdf, export_income_statement_pdf, export_trial_balance_pdf
from app.services.summary_service import save_period_summary, delete_period_summary
from app.routers.settings import get_setting
from app.config import BASE_DIR
import json, os

router = APIRouter(prefix="/closing", tags=["期末处理"])


def auto_save_closing_reports(company_id: int, period: str, db: Session):
    """月末结账时自动生成并缓存三大报表（资产负债表、利润表、科目汇总表）"""
    import traceback
    from datetime import datetime as dt
    company = db.query(Company).filter(Company.id == company_id).first()
    company_name = company.name if company else ""

    year = period[:4]
    reports_dir = BASE_DIR / "uploads" / "reports" / str(company_id) / year
    reports_dir.mkdir(parents=True, exist_ok=True)

    period_display = f"{int(period[:4])}年{int(period[5:7])}月"

    report_defs = [
        {
            "type": "balance_sheet",
            "title": f"资产负债表 ({period_display})",
            "generate": lambda: generate_standard_balance_sheet(company_id, period, period, db),
            "orientation_key": "bs_orientation",
            "default_ori": "L",
            "export_pdf": lambda d, ori: export_balance_sheet_pdf(d, orientation=ori),
        },
        {
            "type": "income_statement",
            "title": f"利润表 ({period_display})",
            "generate": lambda: generate_standard_income_statement(company_id, period, period, db),
            "orientation_key": "is_orientation",
            "default_ori": "P",
            "export_pdf": lambda d, ori: export_income_statement_pdf(d, orientation=ori),
        },
        {
            "type": "trial_balance",
            "title": f"科目汇总表 ({period_display})",
            "generate": lambda: get_trial_balance(company_id, period, period, db),
            "orientation_key": "tb_orientation",
            "default_ori": "P",
            "export_pdf": lambda d, ori: export_trial_balance_pdf(
                d, company_name, "", orientation=ori, period_display=period_display
            ),
        },
    ]

    for rdef in report_defs:
        try:
            data = rdef["generate"]()
            data["period_display"] = period_display

            # 生成PDF
            ori = get_setting(db, company_id, rdef["orientation_key"], rdef["default_ori"])
            buf = rdef["export_pdf"](data, ori)

            filename = f"{rdef['type']}_{period}.pdf"
            filepath = reports_dir / filename
            with open(filepath, "wb") as f:
                f.write(buf.getvalue())

            data_json = json.dumps(data, ensure_ascii=False, default=str)

            # 覆盖保存到 ReportCache
            existing = db.query(ReportCache).filter(
                ReportCache.company_id == company_id,
                ReportCache.report_type == rdef["type"],
                ReportCache.start_period == period,
                ReportCache.end_period == period,
            ).first()

            if existing:
                if existing.pdf_path and os.path.exists(existing.pdf_path):
                    try: os.remove(existing.pdf_path)
                    except: pass
                existing.data = data_json
                existing.title = rdef["title"]
                existing.period_type = "month"
                existing.pdf_path = str(filepath)
                existing.created_at = dt.now()
            else:
                cache = ReportCache(
                    company_id=company_id, report_type=rdef["type"],
                    period_type="month", start_period=period, end_period=period,
                    title=rdef["title"], data=data_json, pdf_path=str(filepath),
                )
                db.add(cache)
            db.flush()
        except Exception as e:
            import logging
            logging.warning(f"结账自动缓存[{rdef['type']}]跳过 (不影响结账): {e}")

    db.commit()

    # 保存月度财务快照（第二层）
    try:
        save_period_summary(company_id, period, db)
        db.commit()
    except Exception:
        db.rollback()





@router.post("/carry-forward")
async def do_carry_forward(request: Request, db: Session = Depends(get_db), user: User = Depends(require_active_company)):
    """执行损益结转"""
    if not user.company_id:
        return JSONResponse({"success": False, "msg": "无权限"})
    form = await request.form()
    period = form.get("period", "")
    ok, msg = carry_forward(user.company_id, user.id, period, db)
    return JSONResponse({"success": ok, "msg": msg})


@router.post("/reverse-carry-forward")
async def do_reverse_carry_forward(
    request: Request,
    reason: str = Form(""),
    period: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_active_company),
):
    """反结转"""
    if user.role not in ("company_admin", "super_admin"):
        return JSONResponse({"success": False, "msg": "无权限"})
    ok, msg = reverse_carry_forward(user.company_id, user.id, reason, period, db)
    return JSONResponse({"success": ok, "msg": msg})


@router.post("/month-end-close")
async def do_month_end_close(request: Request, db: Session = Depends(get_db), user: User = Depends(require_active_company)):
    """月末结账"""
    if not user.company_id:
        return JSONResponse({"success": False, "msg": "无权限"})
    form = await request.form()
    period = form.get("period", date.today().strftime("%Y-%m"))

    # 前置检查
    cp = db.query(ClosingPeriod).filter(
        ClosingPeriod.company_id == user.company_id,
        ClosingPeriod.period == period,
    ).first()
    if cp and cp.is_closed:
        return JSONResponse({"success": False, "msg": "本期已结账"})

    # 检查是否有未过账凭证
    unposted = db.query(Voucher).filter(
        Voucher.company_id == user.company_id,
        func.strftime("%Y-%m", Voucher.date) == period,
        Voucher.status.in_(["draft", "pending", "approved"]),
    ).count()
    if unposted > 0:
        return JSONResponse({"success": False, "msg": f"存在 {unposted} 张未过账凭证，请先过账"})

    # 检查损益是否已结转
    if not cp or not cp.is_carried_forward:
        return JSONResponse({"success": False, "msg": "损益尚未结转，请先执行结转"})

    # 检查借贷平衡：按科目方向汇总余额（借方科目余额 = 贷方科目余额的绝对值）
    from app.models import Account as AccountModel, AccountBalance
    accounts = {a.id: a for a in db.query(AccountModel).filter(AccountModel.company_id == user.company_id).all()}
    balances = db.query(AccountBalance).filter(
        AccountBalance.company_id == user.company_id,
        AccountBalance.period == period,
    ).all()
    debit_total = 0.0
    credit_total = 0.0
    for b in balances:
        acct = accounts.get(b.account_id)
        if not acct:
            continue
        if acct.direction == "借":
            debit_total += b.closing_balance
        else:
            # 贷方余额可能为正或负（部分备抵科目存负值），取绝对值汇总
            credit_total += abs(b.closing_balance)
    if abs(debit_total - credit_total) > 0.01:
        return JSONResponse({"success": False, "msg": f"科目余额表借贷不平衡（借方合计:{debit_total:.2f} 贷方合计:{credit_total:.2f} 差额:{debit_total-credit_total:.2f}），请检查当期凭证和结转状态"})

    # 执行结账
    if not cp:
        cp = ClosingPeriod(company_id=user.company_id, period=period, is_carried_forward=True)
    cp.is_closed = True
    cp.closed_by = user.id
    cp.closed_at = datetime.now()
    if not cp.id:
        db.add(cp)
    db.commit()

    # 审计日志
    db.add(AuditLog(
        company_id=user.company_id, user_id=user.id,
        username=user.username, action="month_end_close",
        target_type="closing", detail=f"期间{period}月末结账",
    ))
    db.commit()

    # 结账成功后自动缓存三大报表
    try:
        auto_save_closing_reports(user.company_id, period, db)
    except Exception:
        pass  # 报表缓存失败不影响结账结果

    return JSONResponse({"success": True, "msg": f"{period} 月末结账成功"})


@router.post("/reverse-close")
async def do_reverse_close(
    request: Request,
    reason: str = Form(""),
    period: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(require_active_company),
):
    """反结账"""
    if user.role not in ("company_admin", "super_admin"):
        return JSONResponse({"success": False, "msg": "无权限"})
    if not period:
        period = date.today().strftime("%Y-%m")
    cp = db.query(ClosingPeriod).filter(
        ClosingPeriod.company_id == user.company_id,
        ClosingPeriod.period == period,
    ).first()
    if not cp or not cp.is_closed:
        return JSONResponse({"success": False, "msg": "本期未结账"})

    cp.is_closed = False
    cp.closed_by = None
    cp.closed_at = None
    db.commit()

    # 反结账时清除已缓存的当月报表和快照
    try:
        cached_reports = db.query(ReportCache).filter(
            ReportCache.company_id == user.company_id,
            ReportCache.end_period == period,
        ).all()
        for r in cached_reports:
            if r.pdf_path and os.path.exists(r.pdf_path):
                try: os.remove(r.pdf_path)
                except: pass
            db.delete(r)
        delete_period_summary(user.company_id, period, db)
        db.commit()
    except Exception:
        pass

    db.add(AuditLog(
        company_id=user.company_id, user_id=user.id,
        username=user.username, action="reverse_close",
        target_type="closing",
        detail=f"反结账期间{period}, 原因:{reason}",
    ))
    db.commit()

    return JSONResponse({"success": True, "msg": f"{period} 反结账成功"})
