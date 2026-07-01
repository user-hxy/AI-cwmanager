"""路由 - 企业财务健康度测评"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
import json
from datetime import datetime
from app.database import get_db
from app.models import User, Company
from app.models.misc import FinancialAssessment
from app.routers.auth import get_login_user, templates
from app.services.assessment_service import (
    ASSESSMENT_MODELS, run_assessment, run_all_models,
)
from app.services.period_helper import get_target_period, get_current_period

router = APIRouter(prefix="/assessment", tags=["财务健康度测评"])


@router.get("/")
async def assessment_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """财务健康度测评首页"""
    if not user.company_id or user.role not in ("company_admin", "super_admin"):
        return RedirectResponse(url="/dashboard", status_code=302)

    company = db.query(Company).filter(Company.id == user.company_id).first()
    period = get_current_period(request, db, user.company_id)

    # 获取该公司的历史测评记录
    histories = db.query(FinancialAssessment).filter(
        FinancialAssessment.company_id == user.company_id,
    ).order_by(FinancialAssessment.created_at.desc()).limit(20).all()

    # 最近一次测评结果
    latest = db.query(FinancialAssessment).filter(
        FinancialAssessment.company_id == user.company_id,
    ).order_by(FinancialAssessment.created_at.desc()).first()
    latest_data = None
    if latest:
        try:
            latest_data = json.loads(latest.result_data) if latest.result_data else None
        except (json.JSONDecodeError, TypeError):
            latest_data = None

    return templates(request, "assessment/assessment.html", {
        "user": user,
        "company": company,
        "period": period,
        "models": ASSESSMENT_MODELS,
        "histories": histories,
        "latest": latest,
        "latest_data": latest_data,
    })


@router.post("/run")
async def run_assessment_api(
    request: Request,
    period: str = Form(...),
    model_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """执行财务健康度测评"""
    if not user.company_id or user.role not in ("company_admin", "super_admin"):
        return JSONResponse({"success": False, "msg": "无权限"})

    try:
        if model_id:
            # 单模型测评
            result = run_assessment(user.company_id, period, model_id, db)
            model_name = next((m["name"] for m in ASSESSMENT_MODELS if m["id"] == model_id), model_id)
            result["model_name"] = model_name

            # 保存测评记录
            record = FinancialAssessment(
                company_id=user.company_id,
                model_id=model_id,
                period=period,
                score=result.get("score", 0),
                level=result.get("level", ""),
                result_data=json.dumps(result, ensure_ascii=False, default=str),
                created_by=user.id,
            )
            db.add(record)
            db.commit()

            return JSONResponse({
                "success": True,
                "msg": f"{model_name} 测评完成",
                "result": result,
                "record_id": record.id,
            })
        else:
            # 全部模型测评
            results = run_all_models(user.company_id, period, db)
            saved_ids = []
            for res in results:
                record = FinancialAssessment(
                    company_id=user.company_id,
                    model_id=res["model_id"],
                    period=period,
                    score=res.get("score", 0),
                    level=res.get("level", ""),
                    result_data=json.dumps(res, ensure_ascii=False, default=str),
                    created_by=user.id,
                )
                db.add(record)
                db.commit()
                saved_ids.append(record.id)

            return JSONResponse({
                "success": True,
                "msg": f"全部测评模型已完成",
                "results": results,
                "record_ids": saved_ids,
            })
    except ValueError as e:
        return JSONResponse({"success": False, "msg": str(e)})
    except Exception as e:
        return JSONResponse({"success": False, "msg": f"测评失败: {str(e)}"})


@router.get("/history")
async def assessment_history(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """测评历史记录"""
    if not user.company_id or user.role not in ("company_admin", "super_admin"):
        return RedirectResponse(url="/dashboard", status_code=302)

    company = db.query(Company).filter(Company.id == user.company_id).first()
    page = int(request.query_params.get("page", 1))
    per_page = 20
    offset = (page - 1) * per_page

    total = db.query(FinancialAssessment).filter(
        FinancialAssessment.company_id == user.company_id,
    ).count()

    records = db.query(FinancialAssessment).filter(
        FinancialAssessment.company_id == user.company_id,
    ).order_by(FinancialAssessment.created_at.desc()).offset(offset).limit(per_page).all()

    total_pages = (total + per_page - 1) // per_page

    return templates(request, "assessment/history.html", {
        "user": user,
        "company": company,
        "records": records,
        "models": {m["id"]: m["name"] for m in ASSESSMENT_MODELS},
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })


@router.get("/detail/{record_id}")
async def assessment_detail(
    record_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """查看测评详情"""
    if not user.company_id:
        return RedirectResponse(url="/dashboard", status_code=302)

    record = db.query(FinancialAssessment).filter(
        FinancialAssessment.id == record_id,
        FinancialAssessment.company_id == user.company_id,
    ).first()
    if not record:
        return RedirectResponse(url="/assessment/history", status_code=302)

    result_data = None
    if record.result_data:
        try:
            result_data = json.loads(record.result_data)
        except (json.JSONDecodeError, TypeError):
            pass

    model_info = next((m for m in ASSESSMENT_MODELS if m["id"] == record.model_id), None)
    company = db.query(Company).filter(Company.id == user.company_id).first()

    return templates(request, "assessment/detail.html", {
        "user": user,
        "company": company,
        "record": record,
        "result_data": result_data,
        "model_info": model_info,
    })


@router.post("/delete/{record_id}")
async def delete_assessment(
    record_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """删除测评记录"""
    if not user.company_id or user.role not in ("company_admin", "super_admin"):
        return JSONResponse({"success": False, "msg": "无权限"})

    record = db.query(FinancialAssessment).filter(
        FinancialAssessment.id == record_id,
        FinancialAssessment.company_id == user.company_id,
    ).first()
    if not record:
        return JSONResponse({"success": False, "msg": "记录不存在"})

    db.delete(record)
    db.commit()
    return JSONResponse({"success": True, "msg": "已删除"})
