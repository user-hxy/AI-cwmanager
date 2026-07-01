"""路由 - 发票管理"""
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime
import json
from pathlib import Path
from app.database import get_db
from app.models import User, Voucher, VoucherEntry, Account
from app.models.misc import Invoice, Attachment, AuditLog
from app.routers.auth import get_login_user, templates, require_active_company
from app.services.invoice_parse import parse_invoice_file
from app.services.voucher_service import generate_voucher_no
from app.config import UPLOAD_DIR

router = APIRouter(prefix="/invoices", tags=["发票管理"])


@router.get("/")
async def invoice_list(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    from app.services.period_helper import get_current_period
    default_period = get_current_period(request, db, user.company_id)
    y, m = int(default_period[:4]), int(default_period[5:7])
    from calendar import monthrange
    default_start = f"{default_period}-01"
    default_end = f"{default_period}-{monthrange(y, m)[1]:02d}"

    date_from = request.query_params.get("date_from", default_start)
    date_to = request.query_params.get("date_to", default_end)

    query = db.query(Invoice).filter(Invoice.company_id == user.company_id)
    from datetime import date
    if date_from:
        query = query.filter(Invoice.issue_date >= date.fromisoformat(date_from))
    if date_to:
        query = query.filter(Invoice.issue_date <= date.fromisoformat(date_to))
    invoices = query.order_by(Invoice.issue_date.desc()).all()

    voucher_ids = [inv.voucher_id for inv in invoices if inv.voucher_id]
    vouchers = {v.id: v for v in db.query(Voucher).filter(Voucher.id.in_(voucher_ids)).all()} if voucher_ids else {}
    msg = request.query_params.get("msg", "")
    return templates(request, "invoices/list.html", {
        "invoices": invoices, "user": user, "vouchers": vouchers, "msg": msg,
        "date_from": date_from, "date_to": date_to,
    })


@router.get("/import")
async def import_page(request: Request, user: User = Depends(get_login_user)):
    return templates(request, "invoices/import.html", {"user": user})


@router.post("/import")
async def import_invoice(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_active_company),
):
    content = await file.read()
    from datetime import datetime
    safe_name = f"invoice_{user.company_id}_{int(datetime.now().timestamp())}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name
    with open(file_path, "wb") as f:
        f.write(content)

    result = parse_invoice_file(file.filename, content)
    invoice_no = result.get("invoice_no", "")

    # 查重复：相同发票号码视为重复
    if invoice_no:
        dup = db.query(Invoice).filter(
            Invoice.company_id == user.company_id,
            Invoice.invoice_no == invoice_no,
        ).first()
        if dup:
            # 保存附件关联到原记录
            att = Attachment(
                company_id=user.company_id, source_type="invoice",
                source_id=dup.id, file_name=file.filename,
                file_path=str(file_path), file_size=len(content),
            )
            db.add(att)
            db.commit()
            return RedirectResponse(url="/invoices/?msg=跳过重复发票：" + invoice_no, status_code=302)

    # 判断解析是否成功
    has_key_info = bool(invoice_no or result.get("total_price", 0) > 0)
    parse_status = "parse_failed" if not has_key_info else "unverified"

    invoice = Invoice(
        company_id=user.company_id,
        invoice_type=result.get("invoice_type", "解析失败"),
        invoice_no=invoice_no,
        issue_date=date.today() if not result.get("issue_date") else date.fromisoformat(result["issue_date"].replace("/", "-")),
        buyer_name=result.get("buyer_name", ""),
        buyer_tax_id=result.get("buyer_tax_id", ""),
        seller_name=result.get("seller_name", ""),
        seller_tax_id=result.get("seller_tax_id", ""),
        total_amount=result.get("total_amount", 0),
        total_tax=result.get("total_tax", 0),
        total_price=result.get("total_price", 0),
        detail_items=json.dumps(result.get("detail_items", []), ensure_ascii=False),
        is_deductible="专用" in result.get("invoice_type", ""),
        verify_status=parse_status,
        file_path=str(file_path),
        status="unprocessed",
    )
    db.add(invoice)
    db.flush()

    att = Attachment(
        company_id=user.company_id, source_type="invoice",
        source_id=invoice.id, file_name=file.filename,
        file_path=str(file_path), file_size=len(content),
    )
    db.add(att)
    db.commit()
    return RedirectResponse(url="/invoices/?msg=导入成功", status_code=302)


@router.get("/{invoice_id}/file")
async def view_invoice_file(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """查看发票原始文件"""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == user.company_id).first()
    if not invoice or not invoice.file_path:
        return JSONResponse({"error": "文件不存在"})
    fp = Path(invoice.file_path)
    if not fp.exists():
        return JSONResponse({"error": "文件不存在"})
    ext = fp.suffix.lower()
    if ext == ".pdf":
        return FileResponse(str(fp), media_type="application/pdf", filename=fp.name, headers={"Content-Disposition": "inline"})
    else:
        return FileResponse(str(fp), media_type="application/octet-stream", filename=fp.name)


@router.get("/{invoice_id}/create-voucher")
async def invoice_to_voucher_page(invoice_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """根据发票创建凭证 - 跳转到预填编辑页面"""
    from app.models import Company as CompanyModel
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == user.company_id).first()
    if not invoice:
        return RedirectResponse(url="/invoices/", status_code=302)

    company = db.query(CompanyModel).filter(CompanyModel.id == user.company_id).first()
    company_name = company.name if company else ""

    total = invoice.total_price or 0
    amount = invoice.total_amount or 0
    tax = invoice.total_tax or 0
    is_deductible = invoice.is_deductible

    # 判断发票方向：本公司是销售方（销项/开发票）还是购买方（进项/采购）
    is_sales_invoice = company_name and invoice.seller_name and company_name in invoice.seller_name

    entries_data = []
    if is_sales_invoice:
        # 销项发票（开发票场景）：借应收账款，贷主营业务收入+应交税费
        receivable_acct = db.query(Account).filter(
            Account.company_id == user.company_id, Account.code.like("1122%"), Account.is_detail == True
        ).first()
        if not receivable_acct:
            receivable_acct = db.query(Account).filter(
                Account.company_id == user.company_id, Account.code.like("1122%")
            ).first()
        income_acct = db.query(Account).filter(
            Account.company_id == user.company_id, Account.code.like("5001%"), Account.is_detail == True
        ).first()
        if not income_acct:
            income_acct = db.query(Account).filter(
                Account.company_id == user.company_id, Account.code.like("5001%")
            ).first()
        tax_acct = db.query(Account).filter(
            Account.company_id == user.company_id, Account.code == "2221", Account.is_detail == True
        ).first()
        if not tax_acct:
            tax_acct = db.query(Account).filter(
                Account.company_id == user.company_id, Account.code.like("2221%")
            ).first()

        if receivable_acct:
            entries_data.append({"account_id": receivable_acct.id, "direction": "借", "amount": total, "summary": invoice.buyer_name or invoice.seller_name or ""})
        if income_acct and amount > 0:
            entries_data.append({"account_id": income_acct.id, "direction": "贷", "amount": amount, "summary": "销售收入"})
        if tax_acct and tax > 0:
            entries_data.append({"account_id": tax_acct.id, "direction": "贷", "amount": tax, "summary": "销项税额"})
        # 默认凭证字为"转"
        default_voucher_word = "转"
    else:
        # 进项发票（采购场景）
        # 查找相关科目
        tax_acct = db.query(Account).filter(Account.company_id == user.company_id, Account.code == "2221", Account.is_detail == True).first()
        if not tax_acct:
            tax_acct = db.query(Account).filter(Account.company_id == user.company_id, Account.code.like("2221%")).first()
        bank_acct = db.query(Account).filter(Account.company_id == user.company_id, Account.code == "1002", Account.is_detail == True).first()
        payable_acct = db.query(Account).filter(Account.company_id == user.company_id, Account.code.like("2202%"), Account.is_detail == True).first()
        if not payable_acct:
            payable_acct = db.query(Account).filter(Account.company_id == user.company_id, Account.code.like("2202%")).first()

        # 判断费用/资产类型：从发票明细或销售方名称推断
        seller = (invoice.seller_name or "").lower()
        is_asset_purchase = any(kw in seller for kw in ["设备", "机器", "固定资产", "软件", "专利"])
        is_inventory_purchase = any(kw in seller for kw in ["商品", "库存", "材料", "原材料", "存货"])

        # 借方科目：根据采购类型选择
        if is_asset_purchase:
            # 固定资产/无形资产采购
            debit_acct = db.query(Account).filter(
                Account.company_id == user.company_id, Account.code.like("1601%"), Account.is_detail == True
            ).first()
            if not debit_acct:
                debit_acct = db.query(Account).filter(
                    Account.company_id == user.company_id, Account.code.like("1601%")
                ).first()
            debit_name = "固定资产"
        elif is_inventory_purchase:
            # 库存商品/原材料采购
            debit_acct = db.query(Account).filter(
                Account.company_id == user.company_id, Account.code.like("1405%"), Account.is_detail == True
            ).first()
            if not debit_acct:
                debit_acct = db.query(Account).filter(
                    Account.company_id == user.company_id, Account.code.like("1405%")
                ).first()
            if not debit_acct:
                debit_acct = db.query(Account).filter(
                    Account.company_id == user.company_id, Account.code.like("1403%")
                ).first()
            debit_name = "库存商品"
        else:
            # 费用类（默认）
            debit_acct = db.query(Account).filter(
                Account.company_id == user.company_id, Account.code.like("5602%"), Account.is_detail == True
            ).first()
            if not debit_acct:
                debit_acct = db.query(Account).filter(
                    Account.company_id == user.company_id, Account.code.like("5602%")
                ).first()
            debit_name = "费用"

        if is_deductible and amount > 0 and debit_acct:
            # 可抵扣专票：拆分为不含税金额+进项税
            entries_data.append({"account_id": debit_acct.id, "direction": "借", "amount": amount, "summary": invoice.seller_name or ""})
            if tax_acct:
                entries_data.append({"account_id": tax_acct.id, "direction": "借", "amount": tax, "summary": "进项税额"})
            # 贷方：默认应付账款（未付款），有银行存款则优先用银行存款
            if bank_acct:
                entries_data.append({"account_id": bank_acct.id, "direction": "贷", "amount": total, "summary": ""})
            elif payable_acct:
                entries_data.append({"account_id": payable_acct.id, "direction": "贷", "amount": total, "summary": invoice.seller_name or ""})
        else:
            # 不可抵扣或金额为0：全额入借方
            if debit_acct:
                entries_data.append({"account_id": debit_acct.id, "direction": "借", "amount": total, "summary": invoice.seller_name or ""})
            if bank_acct:
                entries_data.append({"account_id": bank_acct.id, "direction": "贷", "amount": total, "summary": ""})
            elif payable_acct:
                entries_data.append({"account_id": payable_acct.id, "direction": "贷", "amount": total, "summary": invoice.seller_name or ""})
        default_voucher_word = "付"

    accounts = db.query(Account).filter(Account.company_id == user.company_id, Account.is_detail == True).order_by(Account.code).all()
    from datetime import date
    voucher_date = invoice.issue_date if invoice.issue_date else date.today()
    return templates(request, "vouchers/invoice_form.html", {
        "user": user, "accounts": accounts, "invoice": invoice,
        "entries_data": entries_data, "today": voucher_date.isoformat(),
        "default_voucher_word": default_voucher_word,
    })
