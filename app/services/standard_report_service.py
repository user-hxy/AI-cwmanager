"""标准财务报表计算服务 - 使用 standard_layouts.py 定义的标准格式
资产负债表：参照《财务报表2026年1.pdf》，列头为「年初数」「期末数」
- 年初数 = 本年度1月1日的余额（上年末结转）
- 期末数 = 所选截止月份的期末余额
利润表：参照《小企业会计准则》计算公式
"""
from sqlalchemy.orm import Session
from datetime import date
from calendar import monthrange
from collections import defaultdict
from app.models import Account, AccountBalance, Company, Voucher, VoucherEntry
from app.services.report_service import _get_opening_data, _get_period_voucher_activity
from app.standard_layouts import BS_LEFT_ASSETS, BS_RIGHT_LIABILITIES_EQUITY, INCOME_STATEMENT_ITEMS


def _get_year_start_balances(company_id, end_period, db, start_period=None):
    """获取所有账户的 year_start 和 closing 值
    所有值以正数表示：借方科目为正，贷方科目为正。

    参数：
    - start_period: 报告起始期间。为 None 时使用公司启用月份。
                    year_start = 该期间期初余额（即上一期期末余额）
    - end_period: 报告截止期间。closing = year_start + 期间净变动

    规则：
    - 如果 start_period 与公司启用月份相同，year_start 取启用期间 opening_balance（原始值）
    - 如果 start_period 不同（如查2月报表），year_start 取 start_period 的期初余额
    """
    comp = db.query(Company).filter(Company.id == company_id).first()
    if not comp or not comp.start_date:
        return {}

    start_period = start_period or comp.start_date.strftime("%Y-%m")
    launch_period = comp.start_date.strftime("%Y-%m")

    # 取 year_start 值：来自 start_period 的 opening_balance
    # 对于 launch_period 取原始 opening_balance；对于其他期间取 AccountBalance 的 opening_balance
    start_bals = db.query(AccountBalance).filter(
        AccountBalance.company_id == company_id,
        AccountBalance.period == start_period,
    ).all()
    start_data = {}
    for b in start_bals:
        if start_period == launch_period:
            # 启用期间：使用 opening_balance（用户输入的原始值）
            val = b.opening_balance
        else:
            # 非启用期间：使用本期的 opening_balance（即上一期的期末结转值）
            val = b.opening_balance
        if abs(val) > 0.001:
            start_data[b.account_id] = val

    # 如果 start_period 没有期初记录（如新启用科目），从上一期期末取值
    if not start_data:
        prev_period = _prev_period(start_period)
        if prev_period:
            prev_bals = db.query(AccountBalance).filter(
                AccountBalance.company_id == company_id,
                AccountBalance.period == prev_period,
            ).all()
            for b in prev_bals:
                if abs(b.closing_balance) > 0.001:
                    start_data[b.account_id] = b.closing_balance

    # 期间借贷发生额（从凭证分录直接计算）
    actual_start = start_period
    period_debit, period_credit = _get_period_voucher_activity(company_id, actual_start, end_period, db)

    accounts = {a.id: a for a in db.query(Account).filter(Account.company_id == company_id).all()}

    result = {}
    for aid, acct in accounts.items():
        year_start_val = start_data.get(aid, 0)

        debit = period_debit.get(aid, 0)
        credit = period_credit.get(aid, 0)

        if acct.direction == "借":
            closing = year_start_val + debit - credit
        else:
            closing = year_start_val + credit - debit

        result[aid] = {"year_start": year_start_val, "closing": closing, "acct": acct}

    return result


def _prev_period(period: str) -> str:
    """获取上一个期间"""
    y, m = int(period[:4]), int(period[5:7])
    m -= 1
    if m == 0:
        m = 12
        y -= 1
    return f"{y}-{m:02d}"


def _sum_by_prefix(prefixes, balances, only_detail=True):
    """按科目编码前缀汇总，默认只统计末级科目避免重复计数"""
    ys = 0.0
    cl = 0.0
    for aid, data in balances.items():
        acct = data["acct"]
        if any(acct.code.startswith(p) for p in prefixes):
            # 只汇总末级科目(parent+child同时出现时仅取child)
            if only_detail and not acct.is_detail:
                continue
            ys += data["year_start"]
            cl += data["closing"]
    return ys, cl


def generate_standard_balance_sheet(company_id, start_period, end_period, db):
    """生成标准格式资产负债表
    列：年初数 = start_period 的期初余额，期末数 = end_period 的期末余额
    - 月度报表：期初=上月期末，期末=本月期末
    - 季度/半年报表：期初=期间首日余额，期末=期间末日余额
    - 全年度报表：期初=年初余额，期末=年末余额
    """
    balances = _get_year_start_balances(company_id, end_period, db, start_period)
    comp = db.query(Company).filter(Company.id == company_id).first()

    def _compute_section(items):
        """按节（header）分组计算
        - sec_ys/cl: 每节开始重置，累计当前节所有数据 → 用于节内小计
        - cum_ys/cl: 从不重置 → 用于跨节合计（如 负债合计=流动+长期）
        - prev_is_calc: 前一个非数据项是否为 calc，连续 calc 用 cum，否则用 sec
        """
        result = []
        sec_ys = 0.0
        sec_cl = 0.0
        cum_ys = 0.0
        cum_cl = 0.0
        prev_is_calc = False

        for name, line_no, codes, item_type in items:
            if item_type == 'calc':
                if prev_is_calc:
                    # 连续 calc（如 长期负债合计 后 负债合计）→ 累计合计
                    disp_ys = cum_ys
                    disp_cl = cum_cl
                else:
                    # 非连续 calc（header 或数据后第一个 calc）→ 节内小计
                    disp_ys = sec_ys
                    disp_cl = sec_cl
                result.append({
                    "name": name, "line_no": line_no or "",
                    "year_start": disp_ys, "closing": disp_cl,
                    "is_total": True, "is_header": False,
                })
                prev_is_calc = True
                continue

            elif item_type == 'header':
                # 新节开始：sec 重置，cum 保留
                sec_ys = 0.0
                sec_cl = 0.0
                prev_is_calc = False
                result.append({
                    "name": name, "line_no": "", "year_start": "", "closing": "",
                    "is_total": False, "is_header": True,
                })
                continue

            # 数据行或展示行
            item_ys = 0.0
            item_cl = 0.0
            if codes:
                item_ys, item_cl = _sum_by_prefix(codes, balances)

            is_deduction = name.startswith("减：")
            disp_ys = item_ys
            disp_cl = item_cl
            if is_deduction:
                disp_ys = -item_ys if item_ys else 0.0
                disp_cl = -item_cl if item_cl else 0.0

            if item_type != 'display':
                sec_ys += disp_ys
                sec_cl += disp_cl
                cum_ys += disp_ys
                cum_cl += disp_cl

            result.append({
                "name": name, "line_no": line_no or "",
                "year_start": disp_ys, "closing": disp_cl,
                "is_total": False, "is_header": False,
            })
            prev_is_calc = False


        return result, cum_ys, cum_cl

    left_items, total_assets_ys, total_assets_cl = _compute_section(BS_LEFT_ASSETS)
    right_items, total_le_ys, total_le_cl = _compute_section(BS_RIGHT_LIABILITIES_EQUITY)

    return {
        "title": "资产负债表", "company": comp.name if comp else "",
        "period": end_period,
        "left_items": left_items, "right_items": right_items,
        "total_assets": total_assets_cl,
        "total_assets_year_start": total_assets_ys,
        "total_liabilities_equity": total_le_cl,
        "total_le_year_start": total_le_ys,
    }


def _compute_income_data(company_id, start_period, end_period, db, all_accounts):
    """计算利润表各项数据，返回 {name: amount}"""
    start_date = date(int(start_period[:4]), int(start_period[5:7]), 1)
    ey, em = int(end_period[:4]), int(end_period[5:7])
    end_date = date(ey, em, monthrange(ey, em)[1])

    entries = db.query(VoucherEntry, Voucher).join(
        Voucher, VoucherEntry.voucher_id == Voucher.id
    ).filter(
        Voucher.company_id == company_id,
        Voucher.date >= start_date, Voucher.date <= end_date,
        Voucher.source_type != "carry_forward",
        Voucher.status != "draft",
    ).all()

    amt_by_acct = defaultdict(lambda: {"借": 0.0, "贷": 0.0})
    for entry, _ in entries:
        amt_by_acct[entry.account_id][entry.direction] += entry.amount

    def _get_acct_net(aid):
        debit = amt_by_acct[aid]["借"]
        credit = amt_by_acct[aid]["贷"]
        acct = all_accounts.get(aid)
        if acct and acct.direction == "贷":
            return credit - debit
        return debit - credit

    def _sum_by_prefix(prefixes):
        total = 0.0
        for aid, acct in all_accounts.items():
            if not acct.is_detail:
                continue
            if any(acct.code.startswith(p) for p in prefixes):
                total += _get_acct_net(aid)
        return total

    data_vals = {}
    for name, line_no, codes, item_type in INCOME_STATEMENT_ITEMS:
        if item_type == 'data' and codes:
            data_vals[name] = _sum_by_prefix(codes)
        elif item_type == 'calc':
            data_vals[name] = 0.0

    rev = data_vals.get("一、主营业务收入", 0)
    cost = data_vals.get("减：主营业务成本", 0)
    tax = data_vals.get("主营业务税金及附加", 0)
    data_vals["二、主营业务利润"] = rev - cost - tax
    other_profit = data_vals.get("加：其他业务利润", 0)
    sell_exp = data_vals.get("减：营业费用", 0)
    mgmt_exp = data_vals.get("管理费用", 0)
    fin_exp = data_vals.get("财务费用", 0)
    data_vals["三、营业利润"] = data_vals["二、主营业务利润"] + other_profit - sell_exp - mgmt_exp - fin_exp
    invest = data_vals.get("加：投资收益", 0)
    other_inc = data_vals.get("营业外收入", 0)
    other_loss = data_vals.get("减：营业外支出", 0)
    data_vals["四、利润总额"] = data_vals["三、营业利润"] + invest + other_inc - other_loss
    tax_exp = data_vals.get("减：所得税", 0)
    data_vals["五、净利润"] = data_vals["四、利润总额"] - tax_exp
    return data_vals


def generate_standard_income_statement(company_id, start_period, end_period, db):
    """生成标准格式利润表（含本月数和本年累计数）"""
    comp = db.query(Company).filter(Company.id == company_id).first()
    accounts = {a.id: a for a in db.query(Account).filter(
        Account.company_id == company_id, Account.category == "损益",
    ).all()}

    # 本月数
    curr = _compute_income_data(company_id, start_period, end_period, db, accounts)

    # 本年累计数（从年初到期末）
    year_start = f"{end_period[:4]}-01"
    accum = _compute_income_data(company_id, year_start, end_period, db, accounts)

    # 构建输出
    result = []
    for name, line_no, codes, item_type in INCOME_STATEMENT_ITEMS:
        is_header = (item_type == 'header')
        is_total = (item_type == 'calc')
        result.append({
            "name": name, "line_no": line_no or "",
            "amount": curr.get(name, 0),
            "cumulative": accum.get(name, 0),
            "is_total": is_total, "is_header": is_header,
        })

    return {
        "title": "利润表", "company": comp.name if comp else "",
        "period": f"{start_period} 至 {end_period}",
        "items": result,
        "p1": curr.get("二、主营业务利润", 0),
        "p2": curr.get("三、营业利润", 0),
        "p3": curr.get("四、利润总额", 0),
        "p4": curr.get("五、净利润", 0),
    }
