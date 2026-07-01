"""企业财务健康度测评服务 - 多模型测评引擎

内置测评模型：
1. 杜邦分析模型 - 以净资产收益率(ROE)为核心
2.  Z值预警模型 - Altman Z-Score 破产风险预测
3. 综合评分模型 - 基于多项财务指标的百分制评分
4. 流动性评价模型 - 重点评估短期偿债能力
"""
from sqlalchemy.orm import Session
from datetime import date
from collections import defaultdict
from app.models import Account, AccountBalance, Voucher, VoucherEntry

# ============================================================
# 内置测评模型定义
# ============================================================
ASSESSMENT_MODELS = [
    {
        "id": "dupont",
        "name": "杜邦分析模型",
        "description": "以净资产收益率(ROE)为核心，逐层分解盈利能力、运营效率与财务杠杆，适合全面诊断企业综合财务状况。",
        "icon": "fa-chart-pie",
        "suitable_for": "适合全面财务诊断，尤其适用于制造、商贸等实体企业",
        "score_range": "0-100分",
    },
    {
        "id": "zscore",
        "name": "Z值预警模型",
        "description": "Altman Z-Score 破产风险预测模型，通过五项财务指标加权计算风险指数，判断企业短期破产风险。",
        "icon": "fa-exclamation-triangle",
        "suitable_for": "适合风险预警，重点关注企业偿债能力和破产风险",
        "score_range": "Z值：<1.8危险 1.8-3.0灰色 >3.0安全",
    },
    {
        "id": "composite",
        "name": "综合评分模型",
        "description": "从盈利能力、偿债能力、运营效率、成长潜力四个维度，按加权百分制综合评分，直观反映企业整体健康度。",
        "icon": "fa-star",
        "suitable_for": "适合管理层综合评估，适用各类企业",
        "score_range": "0-100分",
    },
    {
        "id": "liquidity",
        "name": "流动性评价模型",
        "description": "重点评估企业短期偿债能力和现金流状况，对资金链紧张风险进行量化分析。",
        "icon": "fa-water",
        "suitable_for": "适合资金密集型企业和短期偿债压力较大的企业",
        "score_range": "0-100分",
    },
]


def _get_balance_data(company_id: int, end_period: str, db: Session) -> dict:
    """获取资产负债表关键数据"""
    # 获取所有科目余额
    all_bals = db.query(AccountBalance).filter(
        AccountBalance.company_id == company_id,
        AccountBalance.period == end_period,
    ).all()
    accts = {a.id: a for a in db.query(Account).filter(Account.company_id == company_id).all()}

    # 按科目编码汇总余额（备抵科目：贷方方向的资产科目自动取负值）
    def _bal_by_prefix(prefixes):
        total = 0.0
        for b in all_bals:
            acct = accts.get(b.account_id)
            if not acct or not acct.is_detail:
                continue
            if any(acct.code.startswith(p) for p in prefixes):
                # 贷方方向的资产科目（备抵科目如累计折旧、减值准备）取负值
                if acct.category == "资产" and acct.direction == "贷":
                    total -= b.closing_balance
                else:
                    total += b.closing_balance
        return total

    # 计算关键财务数据
    data = {
        # 资产类
        "流动资产合计": _bal_by_prefix(["1001", "1002", "1012", "1101", "1121", "1122", "1123", "1131", "1132", "1221", "1231", "1401", "1402", "1403", "1404", "1405", "1407", "1408", "1411", "1421"]),
        "非流动资产合计": _bal_by_prefix(["1501", "1511", "1601", "1602", "1603", "1604", "1605", "1606", "1621", "1622", "1701", "1702", "1703", "1801", "1901"]),
        "资产总计": 0.0,
        # 负债类
        "流动负债合计": _bal_by_prefix(["2001", "2201", "2202", "2203", "2211", "2221", "2231", "2232", "2241"]),
        "非流动负债合计": _bal_by_prefix(["2401", "2501", "2701"]),
        "负债合计": 0.0,
        # 权益类
        "实收资本": _bal_by_prefix(["3001"]),
        "盈余公积": _bal_by_prefix(["3101"]),
        "未分配利润": _bal_by_prefix(["3103", "3104"]),
        "所有者权益合计": _bal_by_prefix(["3001", "3002", "3101", "3103", "3104"]),
    }
    data["资产总计"] = data["流动资产合计"] + data["非流动资产合计"]
    data["负债合计"] = data["流动负债合计"] + data["非流动负债合计"]
    data["负债和所有者权益合计"] = data["负债合计"] + data["所有者权益合计"]

    return data


def _get_income_data(company_id: int, end_period: str, db: Session) -> dict:
    """获取利润表关键数据（仅当期）"""
    ey, em = int(end_period[:4]), int(end_period[5:7])
    from calendar import monthrange
    start_date = date(ey, em, 1)
    end_date = date(ey, em, monthrange(ey, em)[1])

    entries = db.query(VoucherEntry, Voucher).join(
        Voucher, VoucherEntry.voucher_id == Voucher.id
    ).filter(
        Voucher.company_id == company_id,
        Voucher.date >= start_date, Voucher.date <= end_date,
        Voucher.source_type != "carry_forward",
        Voucher.status != "draft",
    ).all()

    accts = {a.id: a for a in db.query(Account).filter(
        Account.company_id == company_id, Account.category == "损益",
    ).all()}

    amt_by_acct = defaultdict(lambda: {"借": 0.0, "贷": 0.0})
    for entry, _ in entries:
        amt_by_acct[entry.account_id][entry.direction] += entry.amount

    def _net(aid):
        debit = amt_by_acct[aid]["借"]
        credit = amt_by_acct[aid]["贷"]
        acct = accts.get(aid)
        if acct and acct.direction == "贷":
            return credit - debit
        return debit - credit

    def _sum_prefix(prefixes):
        total = 0.0
        for aid, acct in accts.items():
            if not acct.is_detail:
                continue
            if any(acct.code.startswith(p) for p in prefixes):
                total += _net(aid)
        return total

    # 计算利润表关键项
    revenue = _sum_prefix(["5001", "5051"])  # 主营业务收入+其他业务收入
    cost = _sum_prefix(["5401", "5402"])     # 主营业务成本+其他业务成本
    tax = _sum_prefix(["5403"])              # 税金及附加
    sell_exp = _sum_prefix(["5601"])         # 销售费用
    mgmt_exp = _sum_prefix(["5602"])         # 管理费用
    fin_exp = _sum_prefix(["5603"])          # 财务费用
    invest_inc = _sum_prefix(["5111"])       # 投资收益
    other_inc = _sum_prefix(["5301"])        # 营业外收入
    other_loss = _sum_prefix(["5711"])       # 营业外支出
    tax_exp = _sum_prefix(["5801"])          # 所得税费用

    gross_profit = revenue - cost - tax
    operating_profit = gross_profit - sell_exp - mgmt_exp - fin_exp
    total_profit = operating_profit + invest_inc + other_inc - other_loss
    net_profit = total_profit - tax_exp

    return {
        "营业收入": revenue,
        "营业成本": cost,
        "毛利": gross_profit,
        "销售费用": sell_exp,
        "管理费用": mgmt_exp,
        "财务费用": fin_exp,
        "营业利润": operating_profit,
        "利润总额": total_profit,
        "净利润": net_profit,
    }


def _safe_div(a: float, b: float) -> float:
    """安全除法"""
    return round(a / b, 4) if abs(b) > 0.001 else 0.0


# ============================================================
# 杜邦分析模型
# ============================================================
def _assess_dupont(bd: dict, inc: dict) -> dict:
    """杜邦分析模型"""
    net_profit = inc.get("净利润", 0)
    revenue = inc.get("营业收入", 0)
    total_assets = bd.get("资产总计", 0)
    equity = bd.get("所有者权益合计", 0)

    # 核心指标
    roe = _safe_div(net_profit, equity) * 100  # 净资产收益率
    net_profit_margin = _safe_div(net_profit, revenue) * 100  # 净利率
    asset_turnover = _safe_div(revenue, total_assets)  # 资产周转率
    equity_multiplier = _safe_div(total_assets, equity)  # 权益乘数

    # 评分：ROE为最终结果，满分100
    # ROE > 15% 优秀, > 10% 良好, > 5% 一般, > 0% 及格
    if roe >= 15:
        score = 90 + min(10, (roe - 15) / 5 * 10)
    elif roe >= 10:
        score = 70 + (roe - 10) / 5 * 20
    elif roe >= 5:
        score = 50 + (roe - 5) / 5 * 20
    elif roe >= 0:
        score = 30 + roe / 5 * 20
    else:
        score = max(0, 30 + roe / 5 * 20)

    score = max(0, min(100, score))

    # 评级
    if score >= 85:
        level = "优秀"
    elif score >= 70:
        level = "良好"
    elif score >= 50:
        level = "一般"
    elif score >= 30:
        level = "关注"
    else:
        level = "风险"

    return {
        "score": round(score, 1),
        "level": level,
        "indicators": {
            "净资产收益率(ROE)": {"value": f"{roe:.2f}%", "desc": "衡量股东权益的回报水平", "standard": ">15%优秀"},
            "净利率": {"value": f"{net_profit_margin:.2f}%", "desc": "衡量销售收入的实际盈利能力", "standard": ">10%良好"},
            "资产周转率": {"value": f"{asset_turnover:.2f}", "desc": "衡量资产的使用效率", "standard": ">1.0良好"},
            "权益乘数": {"value": f"{equity_multiplier:.2f}", "desc": "衡量财务杠杆程度", "standard": "1.5-2.5合理"},
        },
        "details": {
            "净利润": f"{net_profit:,.2f}",
            "营业收入": f"{revenue:,.2f}",
            "资产总计": f"{total_assets:,.2f}",
            "所有者权益": f"{equity:,.2f}",
        },
        "suggestions": [],
    }


# ============================================================
# Z值预警模型
# ============================================================
def _assess_zscore(bd: dict, inc: dict) -> dict:
    """Z值预警模型 - Altman Z-Score（非上市公司版）"""
    total_assets = bd.get("资产总计", 0)
    current_assets = bd.get("流动资产合计", 0)
    current_liab = bd.get("流动负债合计", 0)
    total_liab = bd.get("负债合计", 0)
    equity = bd.get("所有者权益合计", 0)
    retained = bd.get("未分配利润", 0)
    net_profit = inc.get("净利润", 0)
    revenue = inc.get("营业收入", 0)

    # X1 = 营运资本/总资产
    working_capital = current_assets - current_liab
    x1 = _safe_div(working_capital, total_assets)
    # X2 = 留存收益/总资产
    x2 = _safe_div(retained, total_assets)
    # X3 = 息税前利润/总资产 (用利润总额代替)
    ebit = inc.get("利润总额", 0)
    x3 = _safe_div(ebit, total_assets)
    # X4 = 所有者权益/总负债
    x4 = _safe_div(equity, total_liab)
    # X5 = 营业收入/总资产
    x5 = _safe_div(revenue, total_assets)

    # 非上市公司Z值公式：Z = 0.717X1 + 0.847X2 + 3.107X3 + 0.420X4 + 0.998X5
    z = 0.717 * x1 + 0.847 * x2 + 3.107 * x3 + 0.420 * x4 + 0.998 * x5

    # 判断区间
    if z >= 3.0:
        level = "安全"
        score = 80 + min(20, (z - 3.0) / 2 * 20)
        suggestions = ["财务状况安全，破产风险较低"]
    elif z >= 1.8:
        level = "灰色"
        score = 40 + (z - 1.8) / 1.2 * 40
        suggestions = ["财务状况存在不确定性，建议关注关键风险指标"]
    else:
        level = "危险"
        score = max(0, 40 - (1.8 - z) / 1.8 * 40)
        suggestions = ["破产风险较高，建议立即采取改善措施"]

    score = max(0, min(100, score))

    return {
        "score": round(score, 1),
        "level": level,
        "z_value": round(z, 4),
        "indicators": {
            "X1(营运资本/总资产)": {"value": f"{x1:.4f}", "desc": "反映企业短期偿债能力", "standard": ">0.1"},
            "X2(留存收益/总资产)": {"value": f"{x2:.4f}", "desc": "反映企业累计盈利能力", "standard": ">0.1"},
            "X3(息税前利润/总资产)": {"value": f"{x3:.4f}", "desc": "反映资产盈利能力", "standard": ">0.05"},
            "X4(权益/负债)": {"value": f"{x4:.4f}", "desc": "反映资本结构稳定性", "standard": ">1.0"},
            "X5(营业收入/总资产)": {"value": f"{x5:.4f}", "desc": "反映资产运营效率", "standard": ">0.6"},
        },
        "suggestions": suggestions,
    }


# ============================================================
# 综合评分模型
# ============================================================
def _assess_composite(bd: dict, inc: dict) -> dict:
    """综合评分模型 - 四维度加权评分"""
    total_assets = bd.get("资产总计", 0)
    current_assets = bd.get("流动资产合计", 0)
    current_liab = bd.get("流动负债合计", 0)
    total_liab = bd.get("负债合计", 0)
    equity = bd.get("所有者权益合计", 0)
    net_profit = inc.get("净利润", 0)
    revenue = inc.get("营业收入", 0)
    operating_profit = inc.get("营业利润", 0)

    # ---- 1. 盈利能力 (权重30%) ----
    roe = _safe_div(net_profit, equity) * 100
    net_margin = _safe_div(net_profit, revenue) * 100
    profit_score = 0
    profit_score += min(50, roe / 15 * 50)  # ROE满分50
    profit_score += min(50, net_margin / 10 * 50)  # 净利率满分50

    # ---- 2. 偿债能力 (权重25%) ----
    current_ratio = _safe_div(current_assets, current_liab)  # 流动比率
    debt_ratio = _safe_div(total_liab, total_assets) * 100  # 资产负债率
    debt_score = 0
    debt_score += min(50, current_ratio / 2 * 50)  # 流动比率2.0满分50
    # 资产负债率 40-60% 最佳
    if debt_ratio < 40:
        debt_score += min(50, debt_ratio / 40 * 50)
    elif debt_ratio <= 60:
        debt_score += 50
    else:
        debt_score += max(0, 50 - (debt_ratio - 60) / 40 * 50)

    # ---- 3. 运营效率 (权重25%) ----
    asset_turnover = _safe_div(revenue, total_assets)
    ops_score = min(100, asset_turnover / 2 * 100)

    # ---- 4. 成长潜力 (权重20%) ----
    growth_score = 50  # 默认中等分
    if operating_profit > 0 and net_profit > 0:
        growth_score = 80
    elif net_profit > 0:
        growth_score = 65
    elif net_profit < 0:
        growth_score = 30

    # 综合加权
    total_score = profit_score * 0.30 + debt_score * 0.25 + ops_score * 0.25 + growth_score * 0.20

    if total_score >= 85:
        level = "优秀"
    elif total_score >= 70:
        level = "良好"
    elif total_score >= 50:
        level = "一般"
    elif total_score >= 30:
        level = "关注"
    else:
        level = "风险"

    suggestions = []
    if current_ratio < 1.0:
        suggestions.append("流动比率低于1，短期偿债压力较大，建议增加流动资产或减少短期负债")
    if debt_ratio > 70:
        suggestions.append("资产负债率偏高，建议优化资本结构，控制负债规模")
    if asset_turnover < 0.5:
        suggestions.append("资产周转率偏低，建议提高资产使用效率，加快存货和应收款周转")
    if net_margin < 5:
        suggestions.append("净利率偏低，建议优化成本结构，提升盈利能力")
    if not suggestions:
        suggestions.append("整体财务状况良好，建议持续关注关键指标变化")

    return {
        "score": round(total_score, 1),
        "level": level,
        "indicators": {
            "盈利能力": {"value": f"{profit_score:.1f}/100", "desc": "基于ROE和净利率评价", "weight": "30%"},
            "偿债能力": {"value": f"{debt_score:.1f}/100", "desc": "基于流动比率和资产负债率评价", "weight": "25%"},
            "运营效率": {"value": f"{ops_score:.1f}/100", "desc": "基于资产周转率评价", "weight": "25%"},
            "成长潜力": {"value": f"{growth_score:.1f}/100", "desc": "基于盈利趋势评价", "weight": "20%"},
        },
        "details": {
            "流动比率": f"{current_ratio:.2f}",
            "资产负债率": f"{debt_ratio:.1f}%",
            "资产周转率": f"{asset_turnover:.2f}",
            "ROE": f"{roe:.2f}%",
        },
        "suggestions": suggestions,
    }


# ============================================================
# 流动性评价模型
# ============================================================
def _assess_liquidity(bd: dict, inc: dict) -> dict:
    """流动性评价模型"""
    total_assets = bd.get("资产总计", 0)
    current_assets = bd.get("流动资产合计", 0)
    current_liab = bd.get("流动负债合计", 0)
    total_liab = bd.get("负债合计", 0)
    equity = bd.get("所有者权益合计", 0)
    net_profit = inc.get("净利润", 0)

    current_ratio = _safe_div(current_assets, current_liab)
    # 速动比率 = (流动资产 - 存货)/流动负债，因无存货明细用近似值
    quick_ratio = _safe_div(current_assets * 0.7, current_liab)
    # 现金比率（用货币资金近似）
    cash_ratio_val = _safe_div(current_assets * 0.3, current_liab)
    # 营运资本比率
    working_capital = current_assets - current_liab
    wc_ratio = _safe_div(working_capital, current_liab)

    # 评分
    cr_score = min(40, current_ratio / 2.0 * 40)  # 流动比率 40分
    qr_score = min(30, quick_ratio / 1.0 * 30)    # 速动比率 30分
    wc_score = min(30, max(0, wc_ratio * 15))     # 营运资本 30分
    total = cr_score + qr_score + wc_score

    if total >= 80:
        level = "充裕"
    elif total >= 60:
        level = "正常"
    elif total >= 40:
        level = "关注"
    else:
        level = "紧张"

    suggestions = []
    if current_ratio < 1.0:
        suggestions.append("流动比率低于1，短期偿债能力不足，建议增加流动资产或安排再融资")
    elif current_ratio < 1.5:
        suggestions.append("流动比率偏低，建议关注现金流状况，保持合理的资金储备")
    if quick_ratio < 0.5:
        suggestions.append("速动比率偏低，快速变现能力不足，建议减少库存积压")
    if working_capital < 0:
        suggestions.append("营运资本为负，存在资金链断裂风险，建议立即采取措施改善流动性")
    if not suggestions:
        suggestions.append("流动性状况良好，资金链安全")

    return {
        "score": round(total, 1),
        "level": level,
        "indicators": {
            "流动比率": {"value": f"{current_ratio:.2f}", "desc": "衡量短期偿债能力", "standard": "1.5-2.0"},
            "速动比率": {"value": f"{quick_ratio:.2f}", "desc": "衡量快速变现能力", "standard": "0.5-1.0"},
            "营运资本": {"value": f"{working_capital:,.2f}", "desc": "衡量日常运营资金", "standard": ">0"},
            "资产负债率": {"value": f"{_safe_div(total_liab, total_assets)*100:.1f}%", "desc": "衡量整体负债水平", "standard": "40-60%"},
        },
        "suggestions": suggestions,
    }


# ============================================================
# 测评引擎入口
# ============================================================
ASSESSMENT_FUNCTIONS = {
    "dupont": _assess_dupont,
    "zscore": _assess_zscore,
    "composite": _assess_composite,
    "liquidity": _assess_liquidity,
}


def run_assessment(company_id: int, period: str, model_id: str, db: Session) -> dict:
    """执行指定模型的财务健康度测评"""
    bd = _get_balance_data(company_id, period, db)
    inc = _get_income_data(company_id, period, db)

    func = ASSESSMENT_FUNCTIONS.get(model_id)
    if not func:
        raise ValueError(f"未知的测评模型: {model_id}")

    result = func(bd, inc)
    result["model_id"] = model_id
    result["period"] = period
    result["company_id"] = company_id
    result["balance_data"] = bd
    result["income_data"] = inc
    return result


def run_all_models(company_id: int, period: str, db: Session) -> list:
    """运行所有测评模型，返回结果列表"""
    bd = _get_balance_data(company_id, period, db)
    inc = _get_income_data(company_id, period, db)

    results = []
    for model in ASSESSMENT_MODELS:
        func = ASSESSMENT_FUNCTIONS[model["id"]]
        result = func(bd, inc)
        result["model_id"] = model["id"]
        result["model_name"] = model["name"]
        result["period"] = period
        results.append(result)

    return results
