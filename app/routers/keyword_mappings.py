"""路由 - 关键词科目映射管理"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Account
from app.models.misc import KeyWordMapping
from app.routers.auth import get_login_user, templates

router = APIRouter(prefix="/keyword-mappings", tags=["关键词映射"])


@router.get("/")
async def mapping_list(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if not user.company_id:
        return RedirectResponse(url="/dashboard", status_code=302)
    source_type = request.query_params.get("source_type", "")
    query = db.query(KeyWordMapping).filter(KeyWordMapping.company_id == user.company_id)
    if source_type:
        query = query.filter(KeyWordMapping.source_type == source_type)
    mappings = query.order_by(KeyWordMapping.source_type, KeyWordMapping.keyword).all()
    accounts = db.query(Account).filter(Account.company_id == user.company_id).order_by(Account.code).all()
    return templates(request, "keyword_mappings/list.html", {
        "user": user, "mappings": mappings, "accounts": accounts,
        "source_type": source_type,
    })


@router.get("/add")
async def mapping_add_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if not user.company_id:
        return RedirectResponse(url="/dashboard", status_code=302)
    accounts = db.query(Account).filter(Account.company_id == user.company_id).order_by(Account.code).all()
    return templates(request, "keyword_mappings/form.html", {
        "user": user, "accounts": accounts, "edit_mode": False,
    })


@router.post("/add")
async def mapping_add(
    request: Request,
    keyword: str = Form(...),
    account_id: int = Form(...),
    direction: str = Form("借"),
    source_type: str = Form("bank"),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    if not user.company_id:
        return JSONResponse({"success": False, "msg": "无权限"})
    acct = db.query(Account).filter(Account.id == account_id, Account.company_id == user.company_id).first()
    if not acct:
        return JSONResponse({"success": False, "msg": "科目不存在"})
    existing = db.query(KeyWordMapping).filter(
        KeyWordMapping.company_id == user.company_id,
        KeyWordMapping.keyword == keyword,
        KeyWordMapping.source_type == source_type,
    ).first()
    if existing:
        return JSONResponse({"success": False, "msg": f"关键词「{keyword}」已存在"})
    mapping = KeyWordMapping(
        company_id=user.company_id, keyword=keyword,
        account_code=acct.code, account_name=acct.name,
        direction=direction, source_type=source_type,
    )
    db.add(mapping)
    db.commit()
    return JSONResponse({"success": True, "msg": "规则已添加"})


@router.post("/{mapping_id}/edit")
async def mapping_edit(
    mapping_id: int,
    request: Request,
    keyword: str = Form(...),
    account_id: int = Form(...),
    direction: str = Form("借"),
    source_type: str = Form("bank"),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    if not user.company_id:
        return JSONResponse({"success": False, "msg": "无权限"})
    mapping = db.query(KeyWordMapping).filter(
        KeyWordMapping.id == mapping_id,
        KeyWordMapping.company_id == user.company_id,
    ).first()
    if not mapping:
        return JSONResponse({"success": False, "msg": "规则不存在"})
    acct = db.query(Account).filter(Account.id == account_id, Account.company_id == user.company_id).first()
    if not acct:
        return JSONResponse({"success": False, "msg": "科目不存在"})
    # 检查关键词重复（排除自身）
    dup = db.query(KeyWordMapping).filter(
        KeyWordMapping.company_id == user.company_id,
        KeyWordMapping.keyword == keyword,
        KeyWordMapping.source_type == source_type,
        KeyWordMapping.id != mapping_id,
    ).first()
    if dup:
        return JSONResponse({"success": False, "msg": f"关键词「{keyword}」已被其他规则使用"})
    mapping.keyword = keyword
    mapping.account_code = acct.code
    mapping.account_name = acct.name
    mapping.direction = direction
    mapping.source_type = source_type
    db.commit()
    return JSONResponse({"success": True, "msg": "规则已更新"})


@router.post("/{mapping_id}/delete")
async def mapping_delete(mapping_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    mapping = db.query(KeyWordMapping).filter(
        KeyWordMapping.id == mapping_id,
        KeyWordMapping.company_id == user.company_id,
    ).first()
    if not mapping:
        return JSONResponse({"success": False, "msg": "规则不存在"})
    db.delete(mapping)
    db.commit()
    return JSONResponse({"success": True, "msg": "规则已删除"})
