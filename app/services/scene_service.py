"""常用业务场景服务"""
from sqlalchemy.orm import Session
from app.models import Account, Voucher
from app.models.misc import SceneRule
from app.scene_data import BUILTIN_SCENES


def seed_builtin_scenes(company_id: int, db: Session) -> int:
    """为企业初始化内置业务场景，返回新增数量"""
    existing_count = db.query(SceneRule).filter(
        SceneRule.company_id == company_id,
    ).count()
    if existing_count > 0:
        return 0

    accounts = {a.code: a for a in db.query(Account).filter(
        Account.company_id == company_id,
    ).all()}

    added = 0
    for idx, sd in enumerate(BUILTIN_SCENES):
        debit_acct = _match_account(sd["debit_code"], accounts)
        credit_acct = _match_account(sd["credit_code"], accounts)
        rule = SceneRule(
            company_id=company_id,
            name=sd["name"],
            keywords=sd["keywords"],
            debit_account_code=sd["debit_code"],
            debit_account_name=debit_acct.name if debit_acct else "",
            credit_account_code=sd["credit_code"],
            credit_account_name=credit_acct.name if credit_acct else "",
            category=sd["category"],
            icon=sd.get("icon", "📄"),
            sort_order=idx,
            is_active=True,
            is_builtin=True,
            is_frequent=sd.get("is_frequent", False),
        )
        db.add(rule)
        added += 1

    db.commit()
    return added


def _match_account(code_prefix: str, accounts: dict):
    """按编码前缀匹配科目"""
    for acct_code, acct in sorted(accounts.items()):
        if acct_code.startswith(code_prefix):
            return acct
    return None


def get_scene_rules(company_id: int, db: Session) -> list:
    """获取企业所有启用的业务场景"""
    return db.query(SceneRule).filter(
        SceneRule.company_id == company_id,
        SceneRule.is_active == True,
    ).order_by(SceneRule.sort_order, SceneRule.id).all()


def get_scene_groups(company_id: int, db: Session) -> dict:
    """按分组获取场景"""
    scenes = get_scene_rules(company_id, db)
    groups = {}
    for s in scenes:
        cat = s.category or "其他"
        if cat not in groups:
            groups[cat] = []
        groups[cat].append({
            "id": s.id,
            "name": s.name,
            "kw": s.keywords.split(",")[0] if s.keywords else s.name,
            "keywords": s.keywords or "",
            "debit_code": s.debit_account_code,
            "credit_code": s.credit_account_code,
            "icon": s.icon or "📄",
            "is_builtin": s.is_builtin,
            "is_frequent": s.is_frequent,
        })
    return groups


def get_frequent_scenes(company_id: int, db: Session) -> list:
    """获取常用场景（按使用频率排序）"""
    scenes = db.query(SceneRule).filter(
        SceneRule.company_id == company_id,
        SceneRule.is_active == True,
        SceneRule.is_frequent == True,
    ).order_by(SceneRule.sort_order).all()

    freq_scores = {}
    for s in scenes:
        first_kw = s.keywords.split(",")[0] if s.keywords else s.name
        count = db.query(Voucher).filter(
            Voucher.company_id == company_id,
            Voucher.summary.contains(first_kw),
        ).count()
        freq_scores[s.id] = count

    result = []
    for s in sorted(scenes, key=lambda x: -freq_scores.get(x.id, 0)):
        first_kw = s.keywords.split(",")[0] if s.keywords else s.name
        result.append({
            "id": s.id,
            "name": f"{s.icon or '📄'} {s.name}",
            "kw": first_kw,
        })
    return result
