"""路由 - 用户管理"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, Company
from app.config import ROLES
from app.routers.auth import get_login_user, templates, require_active_company
from app.services.auth_service import hash_password, log_audit

router = APIRouter(prefix="/users", tags=["用户管理"])


def get_allowed_roles(current_user: User) -> dict:
    """根据当前用户返回可创建的角色列表"""
    if current_user.role == "super_admin":
        return {"company_admin": "公司管理员"}
    elif current_user.role == "company_admin":
        return {k: v for k, v in ROLES.items() if k not in ("super_admin", "company_admin")}
    else:
        return {}


@router.get("/")
async def user_list(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    query = db.query(User)
    if user.role == "super_admin":
        users = query.order_by(User.id).all()
        companies = {c.id: c.name for c in db.query(Company).all()}
    else:
        users = query.filter(User.company_id == user.company_id).order_by(User.id).all()
        companies = {}
    return templates(request, "users/list.html", {
        "users": users, "user": user, "roles": ROLES,
        "companies": companies,
    })


@router.get("/add")
async def user_add_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    allowed_roles = get_allowed_roles(user)
    # 超级管理员创建用户时，需要选择所属公司
    all_companies = []
    if user.role == "super_admin":
        all_companies = db.query(Company).order_by(Company.name).all()
    return templates(request, "users/form.html", {
        "user": user, "roles": ROLES,
        "allowed_roles": allowed_roles,
        "edit_mode": False,
        "all_companies": all_companies,
    })


@router.post("/add")
async def user_add(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(""),
    password: str = Form(...),
    role: str = Form(...),
    company_id: int = Form(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_company),
):
    allowed_roles = get_allowed_roles(current_user)
    if role not in allowed_roles:
        return RedirectResponse(url="/users/", status_code=302)

    # 确定所属公司
    if current_user.role == "super_admin":
        # 超级管理员必须选择公司
        if company_id <= 0:
            all_companies = db.query(Company).order_by(Company.name).all()
            return templates(request, "users/form.html", {
                "user": current_user, "roles": ROLES,
                "allowed_roles": allowed_roles, "edit_mode": False,
                "all_companies": all_companies,
                "error": "请选择所属公司",
            })
        target_company_id = company_id
    else:
        target_company_id = current_user.company_id

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        return templates(request, "users/form.html", {
            "user": current_user, "roles": ROLES,
            "allowed_roles": allowed_roles, "edit_mode": False,
            "error": "用户名已存在",
        })

    new_user = User(
        company_id=target_company_id,
        username=username,
        display_name=display_name or username,
        password_hash=hash_password(password),
        role=role,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/users/", status_code=302)


@router.get("/{user_id}/edit")
async def user_edit_page(user_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """编辑用户页面"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/users/", status_code=302)
    if user.role != "super_admin" and target.company_id != user.company_id:
        return RedirectResponse(url="/users/", status_code=302)
    return templates(request, "users/form.html", {
        "user": user, "roles": ROLES,
        "edit_mode": True, "target_user": target,
    })


@router.post("/{user_id}/edit")
async def user_edit(
    user_id: int,
    request: Request,
    display_name: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_company),
):
    """保存用户编辑（密码留空表示不修改）"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/users/", status_code=302)
    if current_user.role != "super_admin" and target.company_id != current_user.company_id:
        return RedirectResponse(url="/users/", status_code=302)

    changed = []
    if display_name:
        target.display_name = display_name
        changed.append("姓名")
    if password:
        target.password_hash = hash_password(password)
        changed.append("密码")

    db.commit()
    log_audit(db, current_user.id, current_user.username, "edit_user", "user", target.id,
              f"修改用户 {target.username}: {'/'.join(changed)}", company_id=current_user.company_id)
    return RedirectResponse(url="/users/", status_code=302)


# 角色等级（用于权限判断）
_ROLE_LEVEL = {"super_admin": 0, "company_admin": 1, "reviewer": 2, "inputer": 3, "viewer": 4}


def _can_manage(current_role: str, target_role: str) -> bool:
    """检查当前角色是否有权管理目标角色（高级别可管理低级别）"""
    cl = _ROLE_LEVEL.get(current_role, 99)
    tl = _ROLE_LEVEL.get(target_role, 99)
    return cl < tl


@router.post("/{user_id}/delete")
async def user_delete(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_active_company),
):
    """删除用户（高级权限可删除低级权限用户）"""
    if current_user.role not in ("super_admin", "company_admin"):
        return RedirectResponse(url="/users/", status_code=302)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/users/", status_code=302)
    # 不能删除自己
    if target.id == current_user.id:
        return RedirectResponse(url="/users/", status_code=302)
    # 检查同公司权限
    if current_user.role != "super_admin" and target.company_id != current_user.company_id:
        return RedirectResponse(url="/users/", status_code=302)
    # 高级别才能删除低级别
    if not _can_manage(current_user.role, target.role):
        return RedirectResponse(url="/users/", status_code=302)

    db.delete(target)
    db.commit()
    log_audit(db, current_user.id, current_user.username, "delete_user", "user", user_id,
              f"删除用户: {target.username}", company_id=current_user.company_id)
    return RedirectResponse(url="/users/", status_code=302)


@router.post("/{user_id}/unbind-wechat")
async def user_unbind_wechat(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_login_user),
):
    """超级管理员解除用户的微信号绑定"""
    if current_user.role != "super_admin":
        return RedirectResponse(url="/users/", status_code=302)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        return RedirectResponse(url="/users/", status_code=302)
    target.wechat_id = None
    target.wechat_bound_at = None
    db.commit()
    log_audit(db, current_user.id, current_user.username, "unbind_wechat", "user", user_id,
              f"超级管理员解除用户 {target.username} 的微信号绑定", company_id=current_user.company_id)
    return RedirectResponse(url="/users/", status_code=302)
