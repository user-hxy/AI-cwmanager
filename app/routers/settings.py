"""路由 - 系统设置"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse, Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Company
from app.models.misc import SystemSetting
from app.routers.auth import get_login_user, templates, require_active_company
from io import BytesIO

router = APIRouter(prefix="/settings", tags=["系统设置"])


def get_setting(db: Session, company_id: int, key: str, default: str = "") -> str:
    s = db.query(SystemSetting).filter(
        SystemSetting.company_id == company_id,
        SystemSetting.setting_key == key,
    ).first()
    return s.setting_value if s else default


def set_setting(db: Session, company_id: int, key: str, value: str):
    s = db.query(SystemSetting).filter(
        SystemSetting.company_id == company_id,
        SystemSetting.setting_key == key,
    ).first()
    if s:
        s.setting_value = value
    else:
        db.add(SystemSetting(company_id=company_id, setting_key=key, setting_value=value))


@router.get("/")
async def settings_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if user.role == "super_admin":
        # 超级管理员全局配置（Deepseek API Key 等）
        return templates(request, "settings/global.html", {
            "user": user,
            "deepseek_api_key": get_setting(db, 0, "deepseek_api_key", ""),
        })
    if not user.company_id:
        return RedirectResponse(url="/dashboard", status_code=302)
    cid = user.company_id
    return templates(request, "settings/index.html", {
        "user": user,
        "cid": cid,
        "default_entries": get_setting(db, cid, "default_entries", "5"),
        "default_tax_rate": get_setting(db, cid, "default_tax_rate", "6"),
        "v_orientation": get_setting(db, cid, "voucher_orientation", "L"),
        "v_per_page": get_setting(db, cid, "voucher_per_page", "2"),
        "bs_orientation": get_setting(db, cid, "bs_orientation", "P"),
        "is_orientation": get_setting(db, cid, "is_orientation", "P"),
        "tb_orientation": get_setting(db, cid, "tb_orientation", "L"),
    })


@router.post("/save-global")
async def settings_save_global(
    request: Request,
    deepseek_api_key: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """保存全局配置（仅超级管理员）"""
    if user.role != "super_admin":
        return JSONResponse({"success": False, "msg": "无权限"})
    set_setting(db, 0, "deepseek_api_key", deepseek_api_key)
    db.commit()
    return JSONResponse({"success": True, "msg": "全局配置已保存"})


@router.get("/download-db")
async def download_database(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """下载数据库文件（仅超级管理员）"""
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    from app.config import BASE_DIR
    import os, time
    db_path = BASE_DIR / "finance.db"
    if not db_path.exists():
        return JSONResponse({"success": False, "msg": "数据库文件不存在"})
    # 关闭所有数据库连接以确保数据完整性
    from app.database import engine as _eng
    _eng.dispose()
    # 生成带时间戳的文件名
    ts = time.strftime("%Y%m%d_%H%M%S")
    from fastapi.responses import FileResponse
    return FileResponse(
        path=str(db_path),
        media_type="application/octet-stream",
        filename=f"finance_backup_{ts}.db",
        headers={"Content-Disposition": f"attachment; filename=finance_backup_{ts}.db"},
    )


@router.post("/save")
async def settings_save(
    request: Request,
    default_entries: int = Form(5),
    voucher_orientation: str = Form("L"),
    voucher_per_page: int = Form(2),
    bs_orientation: str = Form("P"),
    is_orientation: str = Form("P"),
    tb_orientation: str = Form("L"),
    default_tax_rate: int = Form(6),
    db: Session = Depends(get_db),
    user: User = Depends(require_active_company),
):
    if not user.company_id:
        return JSONResponse({"success": False, "msg": "无权限"})
    set_setting(db, user.company_id, "default_entries", str(default_entries))
    set_setting(db, user.company_id, "default_tax_rate", str(default_tax_rate))
    set_setting(db, user.company_id, "voucher_orientation", voucher_orientation)
    set_setting(db, user.company_id, "voucher_per_page", str(voucher_per_page))
    set_setting(db, user.company_id, "bs_orientation", bs_orientation)
    set_setting(db, user.company_id, "is_orientation", is_orientation)
    set_setting(db, user.company_id, "tb_orientation", tb_orientation)
    db.commit()
    return JSONResponse({"success": True, "msg": "设置已保存"})


@router.get("/pdf-preview")
async def pdf_preview(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """生成PDF预览"""
    if not user.company_id:
        return JSONResponse({"success": False})
    from app.services.voucher_pdf import VoucherPDF
    from datetime import date

    v_orientation = get_setting(db, user.company_id, "voucher_orientation", "L")
    v_per_page = int(get_setting(db, user.company_id, "voucher_per_page", "2"))

    company = db.query(Company).filter(Company.id == user.company_id).first()
    company_name = company.name if company else "示例公司"

    pdf = VoucherPDF(orientation=v_orientation)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    page_w = 297 if v_orientation == "L" else 210
    page_h = 210 if v_orientation == "L" else 297
    vw = page_w - 20
    vh = 86 if v_orientation == "L" else 62
    slot_h = (page_h - 20) / v_per_page

    class FakeObj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    sample_entries = [
        FakeObj(account_code="1002", account_name="银行存款", direction="借", amount=50000.00, summary="收到货款", sort_order=1),
        FakeObj(account_code="2001", account_name="短期借款", direction="贷", amount=50000.00, summary="收到货款", sort_order=2),
    ]
    sample_voucher = FakeObj(voucher_no="付-202602-0001", date=date(2026, 2, 6), summary="银行回单-付款", attachment_count=2)

    for i in range(min(v_per_page, 4)):
        x = (page_w - vw) / 2
        y = 10 + i * slot_h + (slot_h - vh) / 2
        if y < 8:
            y = 8
        pdf.draw_voucher(sample_voucher, sample_entries, company_name, "示例制单人", x, y,
                         reviewer_name="示例审核员", poster_name="示例过账员",
                         page_label="1/1")

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": "inline; filename=preview.pdf"})
