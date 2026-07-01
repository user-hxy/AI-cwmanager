"""月度财务快照服务 — 存储与聚合
第二层：结账时保存月度科目余额快照
第三层：季/半年/年报从快照聚合生成，无需扫描凭证分录
"""
import json, logging
from collections import defaultdict
from sqlalchemy.orm import Session
from app.models import Account, AccountBalance, Company
from app.models.misc import PeriodSummary
from app.standard_layouts import BS_LEFT_ASSETS, BS_RIGHT_LIABILITIES_EQUITY, INCOME_STATEMENT_ITEMS
logger = logging.getLogger(__name__)


def _prev_period(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    m -= 1
    if m == 0: m, y = 12, y - 1
    return f"{y}-{m:02d}"


def _next_period(period: str) -> str:
    y, m = int(period[:4]), int(period[5:7])
    m += 1
    if m > 12: m, y = 1, y + 1
    return f"{y}-{m:02d}"


def _periods_in_range(start: str, end: str):
    periods = []
    p = start
    while p <= end:
        periods.append(p)
        p = _next_period(p)
    return periods


# ==================== 第二层：保存快照 ====================

def save_period_summary(company_id: int, period: str, db: Session):
    """保存月度财务快照（结账时自动调用）"""
    accounts = {a.id: a for a in db.query(Account).filter(
        Account.company_id == company_id
    ).all()}

    balances = db.query(AccountBalance).filter(
        AccountBalance.company_id == company_id,
        AccountBalance.period == period,
    ).all()
    bal_map = {b.account_id: b for b in balances}

    if not balances:
        prev_p = _prev_period(period)
        prev_bals = db.query(AccountBalance).filter(
            AccountBalance.company_id == company_id,
            AccountBalance.period == prev_p,
        ).all()
        opening_map = {b.account_id: b.closing_balance for b in prev_bals}
        if not opening_map:
            comp = db.query(Company).filter(Company.id == company_id).first()
            if comp and comp.start_date and comp.start_date.strftime("%Y-%m") == period:
                sb = db.query(AccountBalance).filter(
                    AccountBalance.company_id == company_id, AccountBalance.period == period,
                ).all()
                for b in sb:
                    opening_map[b.account_id] = b.opening_balance
        from datetime import date
        from calendar import monthrange
        ey, em = int(period[:4]), int(period[5:7])
        from app.models import Voucher, VoucherEntry
        rows = db.query(VoucherEntry, Voucher).join(
            Voucher, VoucherEntry.voucher_id == Voucher.id
        ).filter(
            Voucher.company_id == company_id,
            Voucher.date >= date(ey, em, 1),
            Voucher.date <= date(ey, em, monthrange(ey, em)[1]),
            Voucher.status != "draft",
        ).all()
        debit_map, credit_map = defaultdict(float), defaultdict(float)
        for entry, _ in rows:
            if entry.direction == "借":
                debit_map[entry.account_id] += entry.amount
            else:
                credit_map[entry.account_id] += entry.amount
        for aid, acct in accounts.items():
            op = opening_map.get(aid, 0)
            d = debit_map.get(aid, 0)
            c = credit_map.get(aid, 0)
            cl = op + d - c if acct.direction == "借" else op + c - d
            bal_map[aid] = type('obj', (object,), {
                'opening_balance': op, 'debit_amount': d, 'credit_amount': c, 'closing_balance': cl,
            })()

    snap = {}
    for aid, acct in accounts.items():
        bal = bal_map.get(aid)
        if bal is None:
            continue
        snap[str(aid)] = {
            "code": acct.code, "name": acct.name,
            "category": acct.category, "direction": acct.direction,
            "opening": round(bal.opening_balance, 2),
            "debit": round(bal.debit_amount, 2),
            "credit": round(bal.credit_amount, 2),
            "closing": round(bal.closing_balance, 2),
        }

    rev = sum(info["closing"] for info in snap.values()
              if info["category"] == "损益" and info["direction"] == "贷"
              and info["code"] in ("5001", "5051", "5111", "5301"))
    cost = sum(info["closing"] for info in snap.values()
               if info["category"] == "损益" and any(info["code"].startswith(c) for c in ("5401", "5402", "5403")))
    sell = sum(info["closing"] for info in snap.values()
              if info["category"] == "损益" and any(info["code"].startswith(c) for c in ("5601",)))
    mgmt = sum(info["closing"] for info in snap.values()
               if info["category"] == "损益" and any(info["code"].startswith(c) for c in ("5602",)))
    fin = sum(info["closing"] for info in snap.values()
              if info["category"] == "损益" and any(info["code"].startswith(c) for c in ("5603",)))
    net = round(rev - cost - sell - mgmt - fin, 2)

    def _snap_total(categories):
        return round(sum(
            -info["closing"] if info["direction"] == "贷" else info["closing"]
            for info in snap.values() if info["category"] in categories
        ), 2)

    ta = _snap_total({"资产"})
    tl = _snap_total({"负债"})
    te = _snap_total({"权益"})

    existing = db.query(PeriodSummary).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period == period,
    ).first()
    if existing:
        existing.total_assets = ta
        existing.total_liabilities = tl
        existing.total_equity = te
        existing.revenue = rev
        existing.total_cost = cost
        existing.sell_expense = sell
        existing.mgmt_expense = mgmt
        existing.finance_expense = fin
        existing.net_profit = net
        existing.account_snapshot = json.dumps(snap, ensure_ascii=False)
    else:
        db.add(PeriodSummary(
            company_id=company_id, period=period,
            total_assets=ta, total_liabilities=tl, total_equity=te,
            revenue=rev, total_cost=cost,
            sell_expense=sell, mgmt_expense=mgmt,
            finance_expense=fin, net_profit=net,
            account_snapshot=json.dumps(snap, ensure_ascii=False),
        ))
    db.flush()


def delete_period_summary(company_id: int, period: str, db: Session):
    """反结账时删除快照"""
    db.query(PeriodSummary).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period == period,
    ).delete()
    db.flush()


# ==================== 第三层：从快照聚合 ====================

def check_summaries_exist(company_id: int, start_period: str, end_period: str, db: Session) -> bool:
    """检查指定范围内所有月份的快照是否都存在"""
    periods = _periods_in_range(start_period, end_period)
    existing = set()
    for row in db.query(PeriodSummary.period).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period >= start_period,
        PeriodSummary.period <= end_period,
    ).all():
        existing.add(row[0])
    return all(p in existing for p in periods)


def aggregate_balance_sheet(company_id: int, start_period: str, end_period: str, db: Session):
    """从月度快照聚合生成资产负债表"""
    comp = db.query(Company).filter(Company.id == company_id).first()
    prev_p = _prev_period(start_period)
    prev_summary = db.query(PeriodSummary).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period == prev_p,
    ).first()
    end_summary = db.query(PeriodSummary).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period == end_period,
    ).first()
    if not end_summary or not end_summary.account_snapshot:
        return None
    end_snap = json.loads(end_summary.account_snapshot)
    prev_snap = {}
    if prev_summary and prev_summary.account_snapshot:
        prev_snap = json.loads(prev_summary.account_snapshot)

    def _sum_by_prefix(prefixes):
        ys, cl = 0.0, 0.0
        for aid_s, info in end_snap.items():
            if any(info["code"].startswith(p) for p in prefixes):
                pi = prev_snap.get(aid_s, {})
                ys += pi.get("closing", 0)
                cl += info["closing"]
        return ys, cl

    def _compute_section(items):
        result = []
        sec_ys, sec_cl = 0.0, 0.0
        cum_ys, cum_cl = 0.0, 0.0
        prev_is_calc = False
        for name, line_no, codes, item_type in items:
            if item_type == "calc":
                if prev_is_calc:
                    disp_ys, disp_cl = cum_ys, cum_cl
                else:
                    disp_ys, disp_cl = sec_ys, sec_cl
                result.append({"name": name, "line_no": line_no or "",
                               "year_start": disp_ys, "closing": disp_cl,
                               "is_total": True, "is_header": False})
                prev_is_calc = True
                continue
            elif item_type == "header":
                sec_ys = sec_cl = 0.0
                prev_is_calc = False
                result.append({"name": name, "line_no": "",
                               "year_start": "", "closing": "",
                               "is_total": False, "is_header": True})
                continue
            item_ys = item_cl = 0.0
            if codes:
                item_ys, item_cl = _sum_by_prefix(codes)
            is_ded = name.startswith("减：")
            disp_ys = -item_ys if (is_ded and item_ys) else item_ys
            disp_cl = -item_cl if (is_ded and item_cl) else item_cl
            if item_type != "display":
                sec_ys += disp_ys
                sec_cl += disp_cl
                cum_ys += disp_ys
                cum_cl += disp_cl
            result.append({"name": name, "line_no": line_no or "",
                           "year_start": disp_ys, "closing": disp_cl,
                           "is_total": False, "is_header": False})
            prev_is_calc = False
        return result, cum_ys, cum_cl

    left, ta_ys, ta_cl = _compute_section(BS_LEFT_ASSETS)
    right, tl_ys, tl_cl = _compute_section(BS_RIGHT_LIABILITIES_EQUITY)
    return {
        "title": "资产负债表", "company": comp.name if comp else "",
        "period": end_period,
        "left_items": left, "right_items": right,
        "total_assets": ta_cl, "total_assets_year_start": ta_ys,
        "total_liabilities_equity": tl_cl, "total_le_year_start": tl_ys,
    }


def aggregate_income_statement(company_id: int, start_period: str, end_period: str, db: Session):
    """从月度快照聚合生成利润表"""
    comp = db.query(Company).filter(Company.id == company_id).first()
    summaries = db.query(PeriodSummary).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period >= start_period,
        PeriodSummary.period <= end_period,
    ).order_by(PeriodSummary.period).all()

    year_start = f"{end_period[:4]}-01"
    year_summaries = db.query(PeriodSummary).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period >= year_start,
        PeriodSummary.period <= end_period,
    ).order_by(PeriodSummary.period).all()

    def _calc_values(rows, snap_key, prefix_filter):
        """从快照累计求和某类科目"""
        vals = {}
        for s in rows:
            snap = json.loads(getattr(s, snap_key) or "{}")
            for aid_s, info in snap.items():
                if info["category"] != "损益":
                    continue
                if prefix_filter and not any(info["code"].startswith(p) for p in prefix_filter):
                    continue
                key = info["code"]
                net_flow = info["debit"] - info["credit"] if info["direction"] == "借" else info["credit"] - info["debit"]
                vals[key] = vals.get(key, 0) + net_flow
        return vals

    # 期间累计 (本月数展示期间合计数)
    period_vals = _calc_values(summaries, "account_snapshot", None)
    # 本年累计
    year_vals = _calc_values(year_summaries, "account_snapshot", None)

    def _prefix_sum(prefixes, src):
        return round(sum(v for k, v in src.items() if any(k.startswith(p) for p in prefixes)), 2)

    def _build_item_map(src):
        d = {}
        for name, line_no, codes, item_type in INCOME_STATEMENT_ITEMS:
            if item_type == "data" and codes:
                d[name] = _prefix_sum(codes, src)
            elif item_type == "calc":
                d[name] = 0.0
        rev = d.get("一、主营业务收入", 0)
        cost = d.get("减：主营业务成本", 0)
        tax = d.get("主营业务税金及附加", 0)
        d["二、主营业务利润"] = round(rev - cost - tax, 2)
        other = d.get("加：其他业务利润", 0)
        sell = d.get("减：营业费用", 0)
        mgmt = d.get("管理费用", 0)
        fin = d.get("财务费用", 0)
        d["三、营业利润"] = round(d["二、主营业务利润"] + other - sell - mgmt - fin, 2)
        invest = d.get("加：投资收益", 0)
        o_inc = d.get("营业外收入", 0)
        o_loss = d.get("减：营业外支出", 0)
        d["四、利润总额"] = round(d["三、营业利润"] + invest + o_inc - o_loss, 2)
        tax_e = d.get("减：所得税", 0)
        d["五、净利润"] = round(d["四、利润总额"] - tax_e, 2)
        return d

    curr_map = _build_item_map(period_vals)
    accum_map = _build_item_map(year_vals)

    result = []
    for name, line_no, codes, item_type in INCOME_STATEMENT_ITEMS:
        result.append({
            "name": name, "line_no": line_no or "",
            "amount": curr_map.get(name, 0),
            "cumulative": accum_map.get(name, 0),
            "is_total": item_type == "calc",
            "is_header": item_type == "header",
        })

    return {
        "title": "利润表", "company": comp.name if comp else "",
        "period": f"{start_period} 至 {end_period}",
        "items": result,
        "p1": curr_map.get("二、主营业务利润", 0),
        "p2": curr_map.get("三、营业利润", 0),
        "p3": curr_map.get("四、利润总额", 0),
        "p4": curr_map.get("五、净利润", 0),
    }


def aggregate_trial_balance(company_id: int, start_period: str, end_period: str, db: Session):
    """从月度快照聚合生成科目汇总表"""
    comp = db.query(Company).filter(Company.id == company_id).first()
    start_summary = db.query(PeriodSummary).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period == start_period,
    ).first()
    end_summary = db.query(PeriodSummary).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period == end_period,
    ).first()
    summaries = db.query(PeriodSummary).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period >= start_period,
        PeriodSummary.period <= end_period,
    ).order_by(PeriodSummary.period).all()
    if not end_summary or not end_summary.account_snapshot:
        return None

    end_snap = json.loads(end_summary.account_snapshot)

    # 起点的 opening
    prev_p = _prev_period(start_period)
    prev_s = db.query(PeriodSummary).filter(
        PeriodSummary.company_id == company_id,
        PeriodSummary.period == prev_p,
    ).first()
    if prev_s and prev_s.account_snapshot:
        prev_snap = json.loads(prev_s.account_snapshot)
    elif start_summary and start_summary.account_snapshot:
        prev_snap = json.loads(start_summary.account_snapshot)
    else:
        prev_snap = {}

    # 汇总各月借贷发生额
    total_debit = defaultdict(float)
    total_credit = defaultdict(float)
    for s in summaries:
        snap = json.loads(s.account_snapshot or "{}")
        for aid_s, info in snap.items():
            total_debit[aid_s] += info["debit"]
            total_credit[aid_s] += info["credit"]

    result = []
    for aid_s, info in sorted(end_snap.items(), key=lambda x: x[1]["code"]):
        pi = prev_snap.get(aid_s, {})
        opening = pi.get("closing", 0)
        closing = info["closing"]
        debit = round(total_debit.get(aid_s, 0), 2)
        credit = round(total_credit.get(aid_s, 0), 2)

        if info["direction"] == "贷":
            opening = -opening if opening else 0.0
            closing = -closing if closing else 0.0

        if opening != 0 or debit != 0 or credit != 0 or closing != 0:
            result.append({
                "account_code": info["code"],
                "account_name": info["name"],
                "category": info["category"],
                "opening_balance": opening,
                "debit_amount": debit,
                "credit_amount": credit,
                "closing_balance": closing,
            })
    return sorted(result, key=lambda x: x["account_code"])
