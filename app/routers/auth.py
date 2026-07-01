"""路由 - 用户认证"""
from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.models import User, Company
from app.services.auth_service import hash_password, verify_password, create_token, decode_token, log_audit
from app.config import ROLES
from datetime import datetime

router = APIRouter(prefix="/auth", tags=["认证"])


@router.get("/login")
async def login_page(request: Request):
    token = request.cookies.get("access_token")
    if token:
        payload = decode_token(token)
        if payload:
            return RedirectResponse(url="/dashboard", status_code=302)
    return templates(request, "login.html")


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        func.lower(User.username) == username.lower().strip(),
        User.is_active == True,
    ).first()
    if not user or not verify_password(password, user.password_hash):
        return templates(request, "login.html", {"error": "用户名或密码错误"})

    token = create_token({"user_id": user.id, "username": user.username, "role": user.role})
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie(key="access_token", value=token, httponly=True, max_age=28800, path="/")
    log_audit(db, user.id, user.username, "login", "user", user.id, f"用户登录", company_id=user.company_id)
    return resp


@router.post("/change-password")
async def change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_user_from_cookie(request, db)
    if not user:
        return JSONResponse({"success": False, "msg": "未登录"})
    if len(new_password) < 6:
        return JSONResponse({"success": False, "msg": "新密码至少6位"})
    if not verify_password(old_password, user.password_hash):
        return JSONResponse({"success": False, "msg": "原密码错误"})
    user.password_hash = hash_password(new_password)
    db.commit()
    log_audit(db, user.id, user.username, "change_password", "user", user.id,
              "用户修改自己的密码", company_id=user.company_id)
    return JSONResponse({"success": True, "msg": "密码修改成功"})


@router.post("/switch-user")
async def switch_user(
    request: Request,
    target_user_id: int = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = get_user_from_cookie(request, db)
    if not current_user or not current_user.company_id:
        return JSONResponse({"success": False, "msg": "无权操作"})
    target = db.query(User).filter(
        User.id == target_user_id,
        User.company_id == current_user.company_id,
        User.is_active == True,
    ).first()
    if not target:
        return JSONResponse({"success": False, "msg": "目标用户不存在或不属于本企业"})
    if not verify_password(password, target.password_hash):
        return JSONResponse({"success": False, "msg": "密码错误"})
    token = create_token({"user_id": target.id, "username": target.username, "role": target.role})
    resp = JSONResponse({"success": True, "msg": f"已切换到 {target.display_name}"})
    resp.set_cookie(key="access_token", value=token, httponly=True, max_age=28800)
    return resp


@router.get("/company-users")
async def company_users(request: Request, db: Session = Depends(get_db)):
    current_user = get_user_from_cookie(request, db)
    if not current_user or not current_user.company_id:
        return JSONResponse({"users": []})
    users = db.query(User).filter(
        User.company_id == current_user.company_id,
        User.is_active == True,
    ).order_by(User.role, User.display_name).all()
    role_names = {"company_admin": "公司管理员", "inputer": "录入员", "reviewer": "审核员", "viewer": "查看者"}
    return JSONResponse({
        "users": [{"id": u.id, "username": u.username, "display_name": u.display_name, "role_name": role_names.get(u.role, u.role)} for u in users],
        "current_id": current_user.id,
    })


@router.get("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_cookie(request, db)
    if user:
        log_audit(db, user.id, user.username, "logout", "user", user.id, f"用户退出", company_id=user.company_id)
    resp = RedirectResponse(url="/auth/login", status_code=302)
    resp.delete_cookie("access_token", path="/")
    resp.delete_cookie("access_token", path="/auth/")  # 兼容旧版cookie路径
    return resp


@router.get("/current-user")
async def get_current_user(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_cookie(request, db)
    if not user:
        return JSONResponse({"username": "", "wechat_id": None})
    return JSONResponse({"username": user.username, "display_name": user.display_name, "wechat_id": user.wechat_id, "role": user.role})


def templates(request, name, context=None):
    from fastapi.templating import Jinja2Templates
    from app.database import SessionLocal
    tmpl = Jinja2Templates(directory="app/templates")
    ctx = {"request": request, "user": None, **(context or {})}
    if "company" not in ctx and "user" in ctx and ctx["user"] and ctx["user"].company_id:
        try:
            from app.models import Company
            db = SessionLocal()
            comp = db.query(Company).filter(Company.id == ctx["user"].company_id).first()
            if comp:
                ctx["company"] = comp
                ctx["company_expired"] = comp.is_expired
                ctx["company_expiry_display"] = comp.expiry_display
                if "show_setup" not in ctx and ctx["user"].role == "company_admin":
                    ctx["show_setup"] = not comp.is_initialized
            db.close()
        except Exception:
            pass
    return tmpl.TemplateResponse(name, ctx)


def get_login_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    return user


def get_user_from_cookie(request: Request, db: Session) -> User | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    return db.query(User).filter(User.id == payload.get("user_id")).first()


def require_active_company(user: User = Depends(get_login_user)) -> User:
    if user.company_id:
        from app.database import SessionLocal
        _db = SessionLocal()
        try:
            company = _db.query(Company).filter(Company.id == user.company_id).first()
            if company and company.is_expired:
                raise HTTPException(status_code=403, detail="企业使用权限已过期，无法执行写操作")
        finally:
            _db.close()
    return user
