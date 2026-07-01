"""路由 - 常用业务场景管理"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Account
from app.models.misc import SceneRule
from app.routers.auth import get_login_user, templates
from app.services.scene_service import seed_builtin_scenes, get_scene_rules, get_scene_groups

router = APIRouter(prefix="/scenes", tags=["业务场景"])


def _ensure_seeded(company_id: int, db: Session):
    """确保内置场景已初始化"""
    count = db.query(SceneRule).filter(SceneRule.company_id == company_id).count()
    if count == 0:
        seed_builtin_scenes(company_id, db)


@router.get("/")
async def scene_list(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if not user.company_id:
        return RedirectResponse(url="/dashboard", status_code=302)

    # 首次访问自动初始化内置场景
    _ensure_seeded(user.company_id, db)

    scenes = get_scene_rules(user.company_id, db)
    groups = get_scene_groups(user.company_id, db)
    accounts = db.query(Account).filter(Account.company_id == user.company_id).order_by(Account.code).all()
    return templates(request, "scenes/list.html", {
        "user": user, "scenes": scenes, "groups": groups,
        "accounts": accounts,
        "category_list": sorted(groups.keys()),
    })


@router.post("/add")
async def scene_add(
    request: Request,
    name: str = Form(...),
    keywords: str = Form(""),
    debit_account_id: int = Form(...),
    credit_account_id: int = Form(...),
    category: str = Form("其他"),
    icon: str = Form("📄"),
    is_frequent: str = Form("0"),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    if not user.company_id:
        return JSONResponse({"success": False, "msg": "无权限"})
    debit = db.query(Account).filter(Account.id == debit_account_id, Account.company_id == user.company_id).first()
    credit = db.query(Account).filter(Account.id == credit_account_id, Account.company_id == user.company_id).first()
    if not debit or not credit:
        return JSONResponse({"success": False, "msg": "科目不存在"})

    max_sort = db.query(SceneRule.sort_order).filter(
        SceneRule.company_id == user.company_id,
    ).order_by(SceneRule.sort_order.desc()).first()
    next_sort = (max_sort[0] + 1) if max_sort and max_sort[0] is not None else 0

    rule = SceneRule(
        company_id=user.company_id,
        name=name, keywords=keywords,
        debit_account_code=debit.code, debit_account_name=debit.name,
        credit_account_code=credit.code, credit_account_name=credit.name,
        category=category, icon=icon,
        sort_order=next_sort, is_active=True,
        is_builtin=False, is_frequent=(is_frequent == "1"),
    )
    db.add(rule)
    db.commit()
    return JSONResponse({"success": True, "msg": "场景已添加"})


@router.post("/{scene_id}/edit")
async def scene_edit(
    scene_id: int,
    request: Request,
    name: str = Form(...),
    keywords: str = Form(""),
    debit_account_id: int = Form(...),
    credit_account_id: int = Form(...),
    category: str = Form("其他"),
    icon: str = Form("📄"),
    is_frequent: str = Form("0"),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    if not user.company_id:
        return JSONResponse({"success": False, "msg": "无权限"})
    rule = db.query(SceneRule).filter(
        SceneRule.id == scene_id, SceneRule.company_id == user.company_id,
    ).first()
    if not rule:
        return JSONResponse({"success": False, "msg": "场景不存在"})
    debit = db.query(Account).filter(Account.id == debit_account_id, Account.company_id == user.company_id).first()
    credit = db.query(Account).filter(Account.id == credit_account_id, Account.company_id == user.company_id).first()
    if not debit or not credit:
        return JSONResponse({"success": False, "msg": "科目不存在"})

    rule.name = name
    rule.keywords = keywords
    rule.debit_account_code = debit.code
    rule.debit_account_name = debit.name
    rule.credit_account_code = credit.code
    rule.credit_account_name = credit.name
    rule.category = category
    rule.icon = icon
    rule.is_frequent = (is_frequent == "1")
    db.commit()
    return JSONResponse({"success": True, "msg": "场景已更新"})


@router.post("/{scene_id}/delete")
async def scene_delete(scene_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    rule = db.query(SceneRule).filter(
        SceneRule.id == scene_id, SceneRule.company_id == user.company_id,
    ).first()
    if not rule:
        return JSONResponse({"success": False, "msg": "场景不存在"})
    if rule.is_builtin:
        return JSONResponse({"success": False, "msg": "内置场景不能删除，如需停用请编辑修改"})
    db.delete(rule)
    db.commit()
    return JSONResponse({"success": True, "msg": "场景已删除"})
