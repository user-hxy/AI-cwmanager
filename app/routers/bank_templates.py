"""路由 - 银行回单模板管理 + 学习功能（仅超级管理员）"""
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import date, datetime
import json, re, io
from app.database import get_db
from app.models import User
from app.models.misc import BankTemplate
from app.routers.auth import get_login_user, templates
from app.config import UPLOAD_DIR

router = APIRouter(prefix="/bank-templates", tags=["回单模板"])


@router.get("/")
async def template_list(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    templates_list = db.query(BankTemplate).order_by(BankTemplate.bank_name, BankTemplate.name).all()
    return templates(request, "bank_templates/list.html", {"user": user, "templates": templates_list})


@router.get("/add")
async def template_add_page(request: Request, user: User = Depends(get_login_user)):
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates(request, "bank_templates/form.html", {"user": user, "edit_mode": False})


@router.post("/add")
async def template_add(
    request: Request,
    bank_name: str = Form(...),
    name: str = Form(...),
    regex_rules: str = Form(""),
    mapping_rules: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    tmpl = BankTemplate(
        company_id=None, bank_name=bank_name, name=name,
        regex_rules=regex_rules or "{}",
        mapping_rules=mapping_rules or "{}",
        is_active=True,
    )
    db.add(tmpl)
    db.commit()
    return RedirectResponse(url="/bank-templates/", status_code=302)


@router.get("/{template_id}/edit")
async def template_edit_page(template_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    tmpl = db.query(BankTemplate).filter(BankTemplate.id == template_id).first()
    if not tmpl:
        return RedirectResponse(url="/bank-templates/", status_code=302)
    return templates(request, "bank_templates/form.html", {"user": user, "edit_mode": True, "template": tmpl})


@router.post("/{template_id}/edit")
async def template_edit(
    template_id: int,
    request: Request,
    bank_name: str = Form(...),
    name: str = Form(...),
    regex_rules: str = Form(""),
    mapping_rules: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    tmpl = db.query(BankTemplate).filter(BankTemplate.id == template_id).first()
    if not tmpl:
        return RedirectResponse(url="/bank-templates/", status_code=302)
    tmpl.bank_name = bank_name
    tmpl.name = name
    tmpl.regex_rules = regex_rules or "{}"
    tmpl.mapping_rules = mapping_rules or "{}"
    db.commit()
    return RedirectResponse(url="/bank-templates/", status_code=302)


@router.post("/{template_id}/toggle")
async def template_toggle(template_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if user.role != "super_admin":
        return JSONResponse({"success": False})
    tmpl = db.query(BankTemplate).filter(BankTemplate.id == template_id).first()
    if tmpl:
        tmpl.is_active = not tmpl.is_active
        db.commit()
    return RedirectResponse(url="/bank-templates/", status_code=302)


@router.post("/{template_id}/delete")
async def template_delete(template_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    tmpl = db.query(BankTemplate).filter(BankTemplate.id == template_id).first()
    if tmpl:
        db.delete(tmpl)
        db.commit()
    return RedirectResponse(url="/bank-templates/", status_code=302)


# ====== 学习功能 ======

@router.get("/learn")
async def learn_page(request: Request, user: User = Depends(get_login_user)):
    """回单格式学习页面"""
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates(request, "bank_templates/learn.html", {"user": user})


@router.post("/learn/parse")
async def learn_parse(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """上传样本文件，提取文本供用户标记"""
    if user.role != "super_admin":
        return JSONResponse({"success": False, "msg": "无权限"})

    content = await file.read()

    # 提取PDF文本
    raw_text = ""
    if file.filename.lower().endswith(".pdf"):
        from app.services.bank_parse import extract_text_from_pdf, clean_text
        raw_text = extract_text_from_pdf(content)
        raw_text = clean_text(raw_text)
    else:
        try:
            raw_text = content.decode("utf-8", errors="ignore")
        except:
            raw_text = str(content)

    if not raw_text.strip():
        return JSONResponse({"success": False, "msg": "无法提取文本内容"})

    return JSONResponse({"success": True, "text": raw_text[:5000]})


@router.post("/learn/generate")
async def learn_generate(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """根据用户标记的样本数据生成正则规则"""
    if user.role != "super_admin":
        return JSONResponse({"success": False, "msg": "无权限"})

    form = await request.form()
    sample_text = form.get("sample_text", "")
    bank_name = form.get("bank_name", "").strip()
    template_name = form.get("template_name", "").strip()

    if not bank_name:
        bank_name = "自定义银行"
    if not template_name:
        template_name = f"{bank_name}模板"

    # 用户输入的各字段样例值
    fields = {
        "payer": ("payer_name", "付款人"),
        "payee": ("payee_name", "收款人"),
        "amount": ("amount", "金额"),
        "date": ("transaction_date", "日期"),
        "remark": ("remark", "备注/用途"),
        "fee": ("fee", "手续费"),
    }

    regex_rules = {}
    for key, (field_key, label) in fields.items():
        sample_val = form.get(f"sample_{key}", "").strip()
        if sample_val and sample_val in sample_text:
            # 自动生成正则：在文本中找到该样例值，提取前面的标签文字作为定位模式
            escaped = re.escape(sample_val)
            # 找到样例值前面的文字（作为定位标签）
            idx = sample_text.find(sample_val)
            if idx > 0:
                # 取前60个字符作为上下文
                context_start = max(0, idx - 60)
                prefix = sample_text[context_start:idx]
                # 清理前缀中的噪声
                prefix = re.sub(r'[\s:：]+$', '', prefix)
                # 取最后一个可见词作为标签
                label_match = re.findall(r'[\u4e00-\u9fffA-Za-z]+', prefix)
                label = label_match[-1] if label_match else label
                # 生成正则: 标签后的内容直到下一个中文字或空格
                regex = re.escape(label) + r'[：:]\s*([^\s,，]+)'
                regex_rules[key] = regex

    # 如果没有自动生成到规则，使用通用正则
    if not regex_rules.get("amount"):
        regex_rules["amount"] = r'金额[：:]\s*([\d,]+\.?\d*)'

    regex_json = json.dumps(regex_rules, ensure_ascii=False, indent=2)

    # 保存模板
    tmpl = BankTemplate(
        company_id=None,
        bank_name=bank_name,
        name=template_name,
        regex_rules=regex_json,
        mapping_rules="{}",
        is_active=True,
    )
    db.add(tmpl)
    db.commit()

    return JSONResponse({
        "success": True,
        "msg": f"模板创建成功！银行: {bank_name}",
        "regex_rules": regex_json,
        "template_id": tmpl.id,
    })
