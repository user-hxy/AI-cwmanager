"""路由 - 银行回单导入"""
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import date
import os, json
from pathlib import Path
from app.database import get_db
from app.models import User, Voucher, VoucherEntry, Account, Company
from app.models.misc import BankReceipt, BankAccount, BankTemplate, KeyWordMapping, Attachment
from app.routers.auth import get_login_user, templates, require_active_company
from app.services.bank_parse import parse_receipt_pdf, match_keyword_to_account
from app.services.voucher_service import generate_voucher_no
from app.config import UPLOAD_DIR

router = APIRouter(prefix="/bank-receipts", tags=["银行回单"])


@router.get("/")
async def receipt_list(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    from app.services.period_helper import get_current_period
    default_period = get_current_period(request, db, user.company_id)
    y, m = int(default_period[:4]), int(default_period[5:7])
    from calendar import monthrange
    default_start = f"{default_period}-01"
    default_end = f"{default_period}-{monthrange(y, m)[1]:02d}"

    date_from = request.query_params.get("date_from", default_start)
    date_to = request.query_params.get("date_to", default_end)

    query = db.query(BankReceipt).filter(BankReceipt.company_id == user.company_id)
    if date_from:
        query = query.filter(BankReceipt.transaction_date >= date.fromisoformat(date_from))
    if date_to:
        query = query.filter(BankReceipt.transaction_date <= date.fromisoformat(date_to))
    receipts = query.order_by(BankReceipt.transaction_date.desc()).all()

    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == user.company_id).all()
    voucher_ids = [r.voucher_id for r in receipts if r.voucher_id]
    vouchers = {v.id: v for v in db.query(Voucher).filter(Voucher.id.in_(voucher_ids)).all()} if voucher_ids else {}
    msg = request.query_params.get("msg", "")
    return templates(request, "bank_receipts/list.html", {
        "receipts": receipts, "bank_accounts": bank_accounts, "user": user, "vouchers": vouchers, "msg": msg,
        "date_from": date_from, "date_to": date_to,
    })


@router.get("/import")
async def import_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    bank_accounts = db.query(BankAccount).filter(BankAccount.company_id == user.company_id).all()
    bank_templates = db.query(BankTemplate).filter(BankTemplate.is_active == True).all()
    return templates(request, "bank_receipts/import.html", {
        "user": user, "bank_accounts": bank_accounts, "bank_templates": bank_templates,
    })


@router.post("/import")
async def import_receipt(
    request: Request,
    file: UploadFile = File(...),
    bank_type: str = Form("auto"),
    bank_account_id: int = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(require_active_company),
):
    content = await file.read()
    from datetime import datetime
    safe_name = f"receipt_{user.company_id}_{int(datetime.now().timestamp())}_{file.filename}"
    file_path = UPLOAD_DIR / safe_name
    with open(file_path, "wb") as f:
        f.write(content)

    # 根据银行格式选择解析器
    from app.services.bank_parse import parse_receipt_pdf, parse_receipt_text, parse_jiangyan_receipt, parse_zheshang_receipt, auto_detect_bank

    if bank_type == "jiangyan":
        parse_func = lambda t: parse_jiangyan_receipt(t)
    elif bank_type == "zheshang":
        parse_func = lambda t: parse_zheshang_receipt(t)
    elif bank_type.startswith("template_"):
        tid = int(bank_type.replace("template_", ""))
        tmpl = db.query(BankTemplate).filter(BankTemplate.id == tid).first()
        if tmpl:
            parse_func = lambda t: parse_receipt_text(t, tmpl)
        else:
            parse_func = None
    elif bank_type == "auto":
        # 自动检测：先尝试内置解析器，再匹配模板
        import io
        raw_text = ""
        if file.filename.lower().endswith(".pdf"):
            from app.services.bank_parse import extract_text_from_pdf
            raw_text = extract_text_from_pdf(content)
        else:
            try:
                raw_text = content.decode("utf-8", errors="ignore")
            except:
                raw_text = str(content)
        detected = auto_detect_bank(raw_text)
        if detected == "jiangyan":
            parse_func = lambda t: parse_jiangyan_receipt(t)
        elif detected == "zheshang":
            parse_func = lambda t: parse_zheshang_receipt(t)
        else:
            # 尝试匹配自定义模板（根据银行名称关键词）
            matched = None
            for t in db.query(BankTemplate).filter(BankTemplate.is_active == True).all():
                if t.bank_name and t.bank_name in raw_text:
                    matched = t
                    break
            if matched:
                # 使用匹配到的模板的regex_rules解析
                rules = json.loads(matched.regex_rules) if matched.regex_rules else {}
                parse_func = lambda t, r=rules: _parse_with_rules(t, r)
            else:
                parse_func = None
    else:
        parse_func = None

    if file.filename.lower().endswith(".pdf"):
        if bank_type in ("jiangyan",):
            raw_text = ""
            try:
                from app.services.bank_parse import extract_text_from_pdf, clean_text, split_into_receipts
                raw_text = extract_text_from_pdf(content)
            except: pass
            if raw_text:
                clean_full = clean_text(raw_text)
                parts = split_into_receipts(clean_full)
                results = []
                for p in parts:
                    r = parse_jiangyan_receipt(p)
                    if r["amount"] > 0:
                        results.append(r)
                if not results:
                    results.append(parse_jiangyan_receipt(raw_text))
            else:
                results = [{"error": "无法提取文本", "amount": 0, "confidence": "低"}]
        else:
            results = parse_receipt_pdf(content)
    else:
        try:
            text = content.decode("utf-8", errors="ignore")
        except Exception:
            text = str(content)
        if parse_func:
            results = [parse_func(text)]
        else:
            results = [parse_receipt_text(text)]

    saved_count = 0
    dup_count = 0
    for result in results:
        txn_date = date.today() if not result.get("transaction_date") else date.fromisoformat(result["transaction_date"])
        amt = result.get("amount", 0)
        payer = result.get("payer_name", "")
        payee = result.get("payee_name", "")

        # 查重复：相同日期+金额+付款人+收款人视为重复
        dup = None
        if txn_date and amt > 0:
            dup = db.query(BankReceipt).filter(
                BankReceipt.company_id == user.company_id,
                BankReceipt.transaction_date == txn_date,
                BankReceipt.amount == amt,
                BankReceipt.payer_name == payer,
                BankReceipt.payee_name == payee,
            ).first()

        if dup:
            dup_count += 1
            continue

        receipt = BankReceipt(
            company_id=user.company_id,
            bank_account=result.get("payer_name", ""),
            payer_name=payer,
            payee_name=payee,
            amount=amt,
            transaction_date=txn_date,
            remark=result.get("remark", ""),
            fee=result.get("fee", 0),
            receipt_type=result.get("sub_type", ""),
            parse_confidence=result.get("confidence", "中"),
            raw_text=result.get("remark", ""),
            status="unprocessed",
        )
        db.add(receipt)
        saved_count += 1

    # 保存附件关联
    att = Attachment(
        company_id=user.company_id,
        source_type="bank_receipt",
        file_name=file.filename,
        file_path=str(file_path),
        file_size=len(content),
    )
    db.add(att)
    db.commit()

    msg = f"导入完成：新增{saved_count}条"
    if dup_count:
        msg += f"，跳过{dup_count}条重复"
    return RedirectResponse(url=f"/bank-receipts/?msg={msg}", status_code=302)


@router.get("/{receipt_id}/file")
async def view_receipt_file(receipt_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """查看银行回单原始文件"""
    receipt = db.query(BankReceipt).filter(BankReceipt.id == receipt_id, BankReceipt.company_id == user.company_id).first()
    if not receipt:
        return JSONResponse({"error": "回单不存在"})
    # 从Attachment查找对应文件
    att = db.query(Attachment).filter(
        Attachment.company_id == user.company_id,
        Attachment.source_type == "bank_receipt",
    ).order_by(Attachment.upload_time.desc()).first()
    if att and Path(att.file_path).exists():
        ext = Path(att.file_path).suffix.lower()
        if ext == ".pdf":
            return FileResponse(att.file_path, media_type="application/pdf", filename=att.file_name, headers={"Content-Disposition": "inline"})
        return FileResponse(att.file_path, media_type="application/octet-stream", filename=att.file_name)
    return JSONResponse({"error": "文件不存在"})


@router.get("/{receipt_id}/create-voucher")
async def receipt_to_voucher_page(receipt_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """根据回单创建凭证 - 跳转到预填编辑页面"""
    receipt = db.query(BankReceipt).filter(BankReceipt.id == receipt_id, BankReceipt.company_id == user.company_id).first()
    if not receipt:
        return RedirectResponse(url="/bank-receipts/", status_code=302)

    regenerate = request.query_params.get("regenerate", "0") == "1"
    if regenerate and receipt.voucher_id:
        # 检查公司是否过期
        company = db.query(Company).filter(Company.id == user.company_id).first()
        if company and company.is_expired:
            return RedirectResponse(url=f"/bank-receipts/?msg=企业使用权限已过期，无法执行写操作", status_code=302)
        # 重新生成：解除旧凭证引用，将状态重置为未处理
        old_voucher_id = receipt.voucher_id
        receipt.voucher_id = None
        receipt.status = "unprocessed"
        # 如果旧凭证是草稿或已提交状态，直接删除
        old_voucher = db.query(Voucher).filter(Voucher.id == old_voucher_id).first()
        if old_voucher and old_voucher.status in ("draft", "pending"):
            db.query(VoucherEntry).filter(VoucherEntry.voucher_id == old_voucher.id).delete()
            db.delete(old_voucher)
        db.commit()

    cash_acct = db.query(Account).filter(Account.company_id == user.company_id, Account.code == "1002", Account.is_detail == True).first()
    if not cash_acct:
        cash_acct = db.query(Account).filter(Account.company_id == user.company_id, Account.code == "1002").first()
    mappings = db.query(KeyWordMapping).filter(
        KeyWordMapping.company_id == user.company_id, KeyWordMapping.source_type == "bank",
    ).all()
    matched = match_keyword_to_account(receipt.remark or "", mappings)

    target_acct = None
    if matched:
        target_acct = db.query(Account).filter(
            Account.company_id == user.company_id, Account.code == matched["account_code"],
        ).first()

    if not target_acct:
        remark = receipt.remark or ""
        for keywords, code in [
            (["办公用品", "办公费", "文具"], "5602"), (["差旅费", "出差", "交通"], "5602"),
            (["工资", "薪酬", "社保"], "2211"), (["税", "缴税"], "2221"),
            (["采购", "商品", "库存"], "1405"), (["保险", "车辆", "加油", "维修"], "5602"),
        ]:
            if any(k in remark for k in keywords):
                target_acct = db.query(Account).filter(
                    Account.company_id == user.company_id, Account.code.like(f"{code}%"), Account.is_detail == True,
                ).first()
                if not target_acct:
                    target_acct = db.query(Account).filter(
                        Account.company_id == user.company_id, Account.code.like(f"{code}%"),
                    ).first()
                break

    amt = abs(receipt.amount)

    # 判断是收款还是付款：比较付款人/收款人与本公司名称
    from app.models import Company as CompanyModel
    company_rec = db.query(CompanyModel).filter(CompanyModel.id == user.company_id).first()
    company_name = company_rec.name if company_rec else ""

    # 付款人包含本公司名称 → 支出；收款人包含本公司名称 → 收入
    is_payment = False
    if receipt.payer_name and company_name:
        is_payment = company_name in receipt.payer_name
    elif receipt.payee_name and company_name:
        is_payment = not (company_name in receipt.payee_name)
    else:
        is_payment = True  # 无法判断时默认支出

    entries_data = []
    if cash_acct:
        # 支出：贷银行存款；收入：借银行存款
        entries_data.append({
            "account_id": cash_acct.id, "direction": "贷" if is_payment else "借",
            "amount": amt, "summary": "",
        })
    if target_acct and target_acct.id != (cash_acct.id if cash_acct else None):
        # 支出：借费用科目；收入：贷费用科目
        entries_data.append({
            "account_id": target_acct.id, "direction": "借" if is_payment else "贷",
            "amount": amt, "summary": receipt.remark or "",
        })

    accounts = db.query(Account).filter(Account.company_id == user.company_id, Account.is_detail == True).order_by(Account.code).all()
    from datetime import date
    voucher_date = receipt.transaction_date if receipt.transaction_date else date.today()
    return templates(request, "vouchers/bank_receipt_form.html", {
        "user": user, "accounts": accounts, "receipt": receipt,
        "entries_data": entries_data, "today": voucher_date.isoformat(),
        "regenerate": regenerate,
    })


@router.post("/{receipt_id}/delete")
async def delete_receipt(receipt_id: int, db: Session = Depends(get_db), user: User = Depends(require_active_company)):
    """删除银行回单"""
    if user.role not in ("inputer", "company_admin", "super_admin"):
        return RedirectResponse(url=f"/bank-receipts/?msg=无删除权限", status_code=302)
    receipt = db.query(BankReceipt).filter(
        BankReceipt.id == receipt_id, BankReceipt.company_id == user.company_id
    ).first()
    if not receipt:
        return RedirectResponse(url=f"/bank-receipts/?msg=回单不存在", status_code=302)
    # 解除关联凭证引用
    if receipt.voucher_id:
        receipt.voucher_id = None
    db.delete(receipt)
    db.commit()
    return RedirectResponse(url=f"/bank-receipts/?msg=删除成功", status_code=302)


def _parse_with_rules(text: str, rules: dict) -> dict:
    """使用自定义正则规则解析回单文本"""
    import re
    result = {"payer_name": "", "payee_name": "", "amount": 0.0,
              "transaction_date": "", "remark": "", "fee": 0.0,
              "sub_type": "custom", "confidence": "中"}
    field_map = {
        "payer": "payer_name", "payee": "payee_name",
        "amount": "amount", "date": "transaction_date",
        "remark": "remark", "fee": "fee",
    }
    for key, field in field_map.items():
        pattern = rules.get(key, "")
        if pattern:
            try:
                m = re.search(pattern, text)
                if m:
                    val = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else m.group(0).strip()
                    if field == "amount" or field == "fee":
                        try:
                            result[field] = float(val.replace(",", ""))
                        except:
                            pass
                    else:
                        result[field] = val
            except:
                pass
    if result["amount"] > 0 and result["payer_name"]:
        result["confidence"] = "高"
    return result
