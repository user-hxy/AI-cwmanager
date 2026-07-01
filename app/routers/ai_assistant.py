"""AI智能助手路由 — Deepseek驱动，点数计费"""
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date
from app.database import get_db
from app.models import User, Company
from app.models.misc import AIConversation, AIPointBalance, AIRecharge, AITrainingExample
from app.routers.auth import get_login_user, templates

router = APIRouter(prefix="/ai", tags=["AI助手"])

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
POINT_PRICE = 0.01
TOKEN_RATIO = 0.3

# ==================== 完整知识库 ====================
KNOWLEDGE_BASE = """
你是AI财务管理系统的内置财务AI助手。你的职责是即时执行用户的操作指令，或回答财务问题。执行操作时不提问不确认，直接用默认值完成并在回复中说明。

========== 一、完整知识库 ==========

科目体系（小企业会计准则）:
资产类(借): 1001库存现金 1002银行存款 1122应收账款 1123预付账款 1221其他应收款 1403原材料 1405库存商品 1601固定资产 1602累计折旧(贷)
负债类(贷): 2001短期借款 2202应付账款 2211应付职工薪酬 2221应交税费 2241其他应付款
权益类(贷): 3001实收资本 3002资本公积 3101盈余公积 3103本年利润 3104利润分配
损益类: 5001主营业务收入(贷) 5051其他业务收入(贷) 5401主营业务成本(借) 5403税金及附加(借) 5601销售费用(借) 5602管理费用(借) 5603财务费用(借) 5711营业外支出(借) 5801所得税费用(借)

科目方向: 资产/成本/费用增加记借方，减少记贷方。负债/权益/收入增加记贷方，减少记借方。
做凭证规则: 有借必有贷，借贷必相等。至少两条分录。

常见业务分录:
发工资: 借管理费用(工资总额) 贷应付职工薪酬 / 借应付职工薪酬 贷银行存款(实发) 应交税费(个税) 其他应付款(社保)
缴社保: 借其他应付款(公司+个人) 贷银行存款
支付房租: 借管理费用 贷银行存款
购买设备: 借固定资产/在建工程 贷银行存款
计提折旧: 借管理费用/制造费用 贷累计折旧
缴纳税费: 借应交税费 贷银行存款
收到货款: 借银行存款 贷主营业务收入
报销差旅: 借管理费用 贷银行存款/库存现金
提取备用金: 借库存现金 贷银行存款

系统功能:
[工作台] 首页仪表板，可切换会计期间，查看凭证统计和快捷操作
[凭证录入] 新增凭证。会计期间由系统自动管理，当月未结账即可录入，无需手动初始化。录入未来月份的凭证时直接选择日期即可，系统自动创建会计期间记录
[凭证管理] 列表查看/编辑/删除凭证，可按期间状态筛选
[复制凭证] 基于已有凭证快速复制生成
[凭证审核] 审核提交的凭证，通过或退回
[银行回单] 导入PDF自动解析生成凭证
[发票管理] 导入发票PDF，自动识别信息关联凭证
[科目管理] 管理科目体系
[业务场景] 预设业务模板一键生成凭证
[报表中心] 三大报表+导出Excel/PDF
[健康测评] 五维度财务评分报告
[期末处理] 在[工作台]按顺序操作: 凭证过账→损益结转→月末结账。当前月份结账后下一月自动可用
[用户管理] 管理公司用户角色
[系统配置] 导出方向设置

会计期间重要说明:
系统不存在"初始化月份"或"开账"功能。会计期间由系统自动管理，公司启用日期后的所有月份均可直接使用。录入凭证时选择对应日期即可，结账后可录入下一月凭证，无需额外操作

========== 二、操作指令 ==========

凭证录入格式(回复末尾附加，系统自动执行):
[凭证]
日期|摘要
科目编码|借/贷|金额

默认值: 费用科目用5602，付款科目用1002。找不到科目就用5602。
无需询问用户选科目或付款方式，直接用默认值创建并说明。

例: 用户说"录入加油费285元"，你回复:
已创建凭证 借 5602 管理费用 285.00 贷 1002 银行存款 285.00
[凭证]
2027-01-23|报销加油费
5602|借|285.00
1002|贷|285.00

例: 用户说"报销差旅费1200元"，你回复:
已创建凭证 借 5602 管理费用 1200.00 贷 1002 银行存款 1200.00
[凭证]
2027-01-23|报销差旅费
5602|借|1200.00
1002|贷|1200.00

例: 用户说"发工资，总额10万，实发8万，个税5千，社保1.5万"，你回复:
已创建工资凭证
[凭证]
2027-01-25|发放工资
5602|借|100000.00
2211|贷|100000.00
[凭证]
2027-01-25|支付工资
2211|借|100000.00
1002|贷|80000.00
2221|贷|5000.00
2241|贷|15000.00

========== 三、输出规则(必须严格遵循) ==========

绝对禁止使用以下符号: # ** * - ` 1. 2. 等所有markdown格式符号
段落间用空行分隔，不要用符号开头
功能名称用 [功能名称] 格式
回复简短直接

错误格式(严禁输出):
**一、凭证操作类**
- 录入凭证：...
- 查询凭证：...

正确格式(必须使用):
一、凭证操作类
录入凭证...
查询凭证...

错误格式(严禁输出):
**注意：** 需要先过账
**摘要：** 报销差旅费

正确格式(必须使用):
注意: 需要先过账
摘要: 报销差旅费

安全:
只操作当前公司数据"""


def get_or_create_balance(company_id: int, db: Session) -> AIPointBalance:
    """获取或创建公司点数余额"""
    bal = db.query(AIPointBalance).filter(
        AIPointBalance.company_id == company_id
    ).first()
    if not bal:
        bal = AIPointBalance(company_id=company_id)
        db.add(bal)
        db.flush()
    return bal


def consume_points(company_id: int, tokens: int, db: Session) -> int:
    """按Token消耗计算点数并扣减（整数），返回实际消耗点数"""
    points = max(1, round(tokens * TOKEN_RATIO / 1000))  # 每千Token=0.5点，取整至少1点
    bal = get_or_create_balance(company_id, db)
    if bal.balance < points:
        points = int(bal.balance)  # 余额不足时扣剩余整数
    bal.balance = bal.balance - points
    bal.total_consumed = bal.total_consumed + points
    db.flush()
    return points


def save_conversation(company_id: int, user_id: int, role: str, content: str,
                      prompt_tokens: int = 0, completion_tokens: int = 0,
                      points_cost: float = 0, db: Session = None):
    """保存对话记录"""
    conv = AIConversation(
        company_id=company_id, user_id=user_id,
        role=role, content=content,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        points_cost=points_cost,
    )
    db.add(conv)
    db.flush()


@router.get("/")
async def ai_chat_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """AI助手对话页面"""
    if not user.company_id:
        return RedirectResponse(url="/dashboard", status_code=302)
    company = db.query(Company).filter(Company.id == user.company_id).first()
    bal = get_or_create_balance(user.company_id, db)
    # 最近对话记录（最近50条）
    history = db.query(AIConversation).filter(
        AIConversation.company_id == user.company_id,
    ).order_by(AIConversation.created_at.desc()).limit(50).all()
    history.reverse()  # 按时间正序展示
    return templates(request, "ai_chat.html", {
        "user": user, "company": company,
        "balance": bal.balance, "history": history,
    })


# ========== AI工具函数定义（Function Calling） ==========

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "create_voucher",
            "description": "创建一张凭证（录入凭证），按用户描述的业务生成分录并保存。返回创建结果和凭证编号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "凭证日期，格式 YYYY-MM-DD"},
                    "summary": {"type": "string", "description": "凭证摘要，描述业务内容"},
                    "entries": {
                        "type": "array",
                        "description": "分录列表，至少2条，借贷金额合计必须相等",
                        "items": {
                            "type": "object",
                            "properties": {
                                "account_code": {"type": "string", "description": "科目编码，如 1002 银行存款、5602 管理费用"},
                                "direction": {"type": "string", "enum": ["借", "贷"]},
                                "amount": {"type": "number", "description": "金额，正数"},
                                "summary": {"type": "string", "description": "该行摘要，可为空"},
                            },
                            "required": ["account_code", "direction", "amount"],
                        },
                    },
                },
                "required": ["date", "summary", "entries"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_report",
            "description": "获取三大报表数据（资产负债表、利润表、科目汇总表）。返回报表数据用于展示和分析。",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_type": {"type": "string", "enum": ["balance_sheet", "income_statement", "trial_balance"], "description": "报表类型"},
                    "period": {"type": "string", "description": "会计期间 YYYY-MM，如 2026-06"},
                },
                "required": ["report_type", "period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_closing_status",
            "description": "获取当前公司的结账状态，包括各期间是否已结转损益、是否已结账。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_account",
            "description": "搜索科目，根据关键词查找科目编码和名称。可用于帮用户确定正确的科目。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词，如 管理、银行、应付"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_voucher_entries",
            "description": "校验凭证分录的科目是否正确。检查科目编码是否存在、科目方向是否合理、借贷是否平衡。返回校验结果。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "description": "需要校验的分录列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "account_code": {"type": "string", "description": "科目编码"},
                                "direction": {"type": "string", "enum": ["借", "贷"]},
                                "amount": {"type": "number"},
                            },
                            "required": ["account_code", "direction", "amount"],
                        },
                    },
                },
                "required": ["entries"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_report",
            "description": "分析当前报表是否存在问题，给出专业建议。调用此函数前请先通过get_report获取数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "context": {"type": "string", "description": "分析上下文，描述当前查看的报表类型和期间"},
                },
                "required": ["context"],
            },
        },
    },
]


def execute_tool(tool_name: str, args: dict, company_id: int, user_id: int, db: Session) -> str:
    """执行AI调用的工具函数，返回结果文本"""
    from datetime import date as dt_date

    if tool_name == "create_voucher":
        from app.models import Account, Voucher, VoucherEntry
        from app.services.voucher_service import generate_voucher_no
        # 校验科目
        for entry in args.get("entries", []):
            code = entry["account_code"]
            acct = db.query(Account).filter(Account.company_id == company_id, Account.code == code).first()
            if not acct:
                # 模糊匹配：按编码前缀
                acct = db.query(Account).filter(Account.company_id == company_id, Account.code.like(f"{code}%")).first()
            if not acct:
                # 按名称模糊匹配
                acct = db.query(Account).filter(Account.company_id == company_id, Account.name.contains(code)).first()
            if not acct:
                # 若科目名含"管理"或"费用"或"办公"等，用5602
                for kw in ["管理", "费用", "办公", "交通", "汽油", "加油", "差旅", "报销"]:
                    acct = db.query(Account).filter(Account.company_id == company_id, Account.code == "5602").first()
                    if acct: break
            if not acct:
                # 仍然找不到，用系统第一个损益费用科目
                acct = db.query(Account).filter(Account.company_id == company_id, Account.category == "损益", Account.direction == "借").first()
            if not acct:
                return f"未找到合适科目，请先在 [科目管理] 中创建"
            entry["_account"] = acct
        # 校验借贷平衡
        debit_total = sum(e["amount"] for e in args["entries"] if e["direction"] == "借")
        credit_total = sum(e["amount"] for e in args["entries"] if e["direction"] == "贷")
        if abs(debit_total - credit_total) > 0.01:
            return f"借贷不平衡: 借方{debit_total:.2f} 贷方{credit_total:.2f}"
        try:
            d = dt_date.fromisoformat(args["date"])
        except:
            return f"日期格式错误: {args['date']}"
        # 创建凭证
        vn, sn = generate_voucher_no(db, company_id, "记", d.year, d.month)
        v = Voucher(company_id=company_id, voucher_no=vn, date=d,
                    summary=args["summary"], voucher_word="记", serial_no=sn,
                    status="draft", source_type="manual", creator_id=user_id)
        db.add(v)
        db.flush()
        for i, e in enumerate(args["entries"]):
            acct = e["_account"]
            db.add(VoucherEntry(voucher_id=v.id, account_id=acct.id,
                                account_code=acct.code, account_name=acct.name,
                                direction=e["direction"], amount=e["amount"],
                                summary=e.get("summary", args["summary"]), sort_order=i))
        db.commit()
        lines = "\n".join(f"  {e['direction']} {e['_account'].code} {e['_account'].name} {e['amount']:.2f} {e.get('summary','')}" for e in args["entries"])
        return f"凭证已创建成功！凭证编号: {vn}\n日期: {args['date']}\n摘要: {args['summary']}\n分录:\n{lines}\n合计: 借 {debit_total:.2f} = 贷 {credit_total:.2f}\n当前状态: 草稿，可进入 [凭证管理] 提交审核"

    elif tool_name == "get_report":
        from app.services.standard_report_service import generate_standard_balance_sheet, generate_standard_income_statement
        from app.services.report_service import get_trial_balance
        comp = db.query(Company).filter(Company.id == company_id).first()
        rt = args.get("report_type", "balance_sheet")
        period = args.get("period", "")
        if not period:
            return "请指定会计期间"
        if rt == "balance_sheet":
            data = generate_standard_balance_sheet(company_id, period, period, db)
            items = data.get("left_items", []) + data.get("right_items", [])
            lines = [f"资产负债表 {comp.name} {period}"]
            for it in items:
                if it.get("is_header"):
                    lines.append(f"  {it['name']}")
                elif it.get("is_total"):
                    lines.append(f"  {it['name']}: 年初{it['year_start']:.2f} 期末{it['closing']:.2f}")
                else:
                    ys = f"{it['year_start']:.2f}" if isinstance(it['year_start'], (int,float)) else "-"
                    cl = f"{it['closing']:.2f}" if isinstance(it['closing'], (int,float)) else "-"
                    lines.append(f"  {it['name']}: {ys} / {cl}")
            lines.append(f"  资产总计: {data.get('total_assets',0):.2f}")
            lines.append(f"  负债及权益总计: {data.get('total_liabilities_equity',0):.2f}")
            return "\n".join(lines)
        elif rt == "income_statement":
            data = generate_standard_income_statement(company_id, period, period, db)
            lines = [f"利润表 {comp.name} {period}"]
            for it in data.get("items", []):
                if it.get("is_header"):
                    lines.append(f"  {it['name']}")
                else:
                    lines.append(f"  {it['name']}: 本月{it['amount']:.2f} 累计{it['cumulative']:.2f}")
            lines.append(f"  净利润: {data.get('p4',0):.2f}")
            return "\n".join(lines)
        else:
            data = get_trial_balance(company_id, period, period, db)
            lines = [f"科目汇总表 {comp.name} {period}"]
            for r in data[:30]:
                lines.append(f"  {r['account_code']} {r['account_name']}: 期初{r['opening_balance']:.2f} 借{r['debit_amount']:.2f} 贷{r['credit_amount']:.2f} 期末{r['closing_balance']:.2f}")
            if len(data) > 30:
                lines.append(f"  ...共{len(data)}条科目")
            return "\n".join(lines)

    elif tool_name == "get_closing_status":
        from app.models.misc import ClosingPeriod
        periods = db.query(ClosingPeriod).filter(
            ClosingPeriod.company_id == company_id
        ).order_by(ClosingPeriod.period.desc()).limit(12).all()
        if not periods:
            return "暂无结账记录"
        lines = ["结账状态（最近12期）:"]
        for cp in periods:
            status = "已结账" if cp.is_closed else ("已结转" if cp.is_carried_forward else "未处理")
            lines.append(f"  {cp.period}: {status}")
        return "\n".join(lines)

    elif tool_name == "search_account":
        keyword = args.get("keyword", "")
        from app.models import Account
        # 搜索编码或名称包含关键字的科目
        accts = db.query(Account).filter(
            Account.company_id == company_id,
            (Account.code.contains(keyword)) | (Account.name.contains(keyword)),
        ).order_by(Account.code).limit(20).all()
        if not accts:
            # 如果名称搜索无结果，推荐常用费用科目
            fallback = db.query(Account).filter(
                Account.company_id == company_id,
                Account.code.in_(["5602", "1002", "5001"]),
            ).all()
            if fallback:
                lines = [f"未找到「{keyword}」相关科目，推荐以下常用科目:"]
                for a in fallback:
                    lines.append(f"  {a.code} {a.name} ({a.category})")
                return "\n".join(lines)
            return f"未找到包含「{keyword}」的科目，请使用 [科目管理] 查看全部科目"
        lines = [f"搜索「{keyword}」结果:"]
        for a in accts:
            lines.append(f"  {a.code} {a.name} ({a.category})")
        return "\n".join(lines)

    elif tool_name == "validate_voucher_entries":
        from app.models import Account
        entries = args.get("entries", [])
        results = []
        debit_total = 0.0
        credit_total = 0.0
        for i, e in enumerate(entries):
            code = e.get("account_code", "")
            direction = e.get("direction", "借")
            amount = e.get("amount", 0)
            if direction == "借":
                debit_total += amount
            else:
                credit_total += amount
            acct = db.query(Account).filter(
                Account.company_id == company_id, Account.code == code
            ).first()
            if not acct:
                # 模糊匹配建议
                similar = db.query(Account).filter(
                    Account.company_id == company_id,
                    Account.code.like(f"{code[:2]}%"),
                ).order_by(Account.code).limit(3).all()
                suggest = f"，建议: {', '.join(f'{a.code} {a.name}' for a in similar)}" if similar else ""
                results.append(f"第{i+1}行: 科目 {code} 不存在{suggest}")
                continue
            if acct.direction == "贷" and direction == "借" and acct.category in ("负债", "权益", "收入"):
                results.append(f"第{i+1}行: {code} {acct.name} 是{direction}方科目，但正常余额方向为{acct.direction}，请确认是否正确")
        balance_diff = round(debit_total - credit_total, 2)
        warnings_only = len(results) == 0
        if abs(balance_diff) > 0.01:
            results.append(f"借贷不平衡: 借方合计 {debit_total:.2f}，贷方合计 {credit_total:.2f}，差额 {balance_diff:.2f}")
        else:
            results.append(f"借贷平衡检查通过: 合计 {debit_total:.2f}")
        if warnings_only:
            results.append("校验通过，未发现问题")
        return "凭证校验结果:\n" + "\n".join(results)

    elif tool_name == "analyze_report":
        from app.models.misc import ClosingPeriod
        from app.services.standard_report_service import generate_standard_balance_sheet, generate_standard_income_statement
        from app.services.report_service import get_trial_balance
        comp = db.query(Company).filter(Company.id == company_id).first()
        ctx = args.get("context", "")
        # 尝试分析资产负债表
        lines = [f"报表分析报告 - {comp.name if comp else ''}"]
        lines.append(f"分析上下文: {ctx}")
        # 取最近结账期间
        last_cp = db.query(ClosingPeriod).filter(
            ClosingPeriod.company_id == company_id, ClosingPeriod.is_closed == True,
        ).order_by(ClosingPeriod.period.desc()).first()
        period = last_cp.period if last_cp else ""
        if period:
            # 资产负债表平衡校验
            bs = generate_standard_balance_sheet(company_id, period, period, db)
            ta = bs.get("total_assets", 0)
            tl = bs.get("total_liabilities_equity", 0)
            diff = round(abs(ta - tl), 2)
            if diff <= 0.01:
                lines.append(f"资产负债表 {period}: 平衡 (资产 {ta:.2f} = 负债+权益 {tl:.2f})")
            else:
                lines.append(f"资产负债表 {period}: 不平衡! 差额 {diff:.2f}，请检查当期凭证")
            # 利润分析
            is_data = generate_standard_income_statement(company_id, period, period, db)
            net = is_data.get("p4", 0)
            rev = 0
            for item in is_data.get("items", []):
                if item["name"] == "一、主营业务收入":
                    rev = item["amount"]
                    break
            lines.append(f"净利润: {net:.2f}")
            if rev > 0:
                margin = round(net / rev * 100, 2)
                lines.append(f"净利率: {margin}%")
                if margin < 0:
                    lines.append("提示: 当前处于亏损状态，建议检查成本控制")
                elif margin < 10:
                    lines.append("提示: 净利率偏低，建议优化费用结构")
                else:
                    lines.append("提示: 盈利状况良好")
        else:
            lines.append("尚无结账记录，无法分析")
        return "\n".join(lines)

    return f"未知操作: {tool_name}"


def call_deepseek(api_key: str, messages: list, tools: list = None) -> dict:
    """调用Deepseek API，支持function calling"""
    import requests as http_req
    payload = {"model": DEEPSEEK_MODEL, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    resp = http_req.post(
        DEEPSEEK_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    return resp.json()


@router.post("/chat")
async def ai_chat(
    request: Request,
    message: str = Form(""),
    page_context: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """发送消息给Deepseek（支持自动操作 + 页面上下文感知）"""
    if not user.company_id:
        return JSONResponse({"success": False, "msg": "无权限"})
    if not message.strip():
        return JSONResponse({"success": False, "msg": "请输入消息"})

    bal = get_or_create_balance(user.company_id, db)
    if bal.balance <= 0:
        return JSONResponse({
            "success": False, "msg": "AI点数不足，请联系管理员充值",
            "balance": 0,
        })

    company = db.query(Company).filter(Company.id == user.company_id).first()
    company_context = f"当前公司：{company.name}（ID={company.id}），启用日期：{company.start_date}，会计启用月份：{company.start_date.strftime('%Y-%m') if company.start_date else '未设置'}"
    if page_context:
        company_context += f"\n当前页面: {page_context}"

    # 构建消息上下文
    recent = db.query(AIConversation).filter(
        AIConversation.company_id == user.company_id,
        AIConversation.role.in_(["user", "assistant"]),
    ).order_by(AIConversation.created_at.desc()).limit(16).all()
    recent.reverse()
    # 加载训练示例
    examples = db.query(AITrainingExample).filter(
        AITrainingExample.is_active == True,
    ).order_by(AITrainingExample.sort_order).all()
    extra_examples = ""
    for ex in examples:
        extra_examples += f"\n用户: {ex.user_message}\nAI: {ex.ai_response}\n"

    messages = [{"role": "system", "content": KNOWLEDGE_BASE + extra_examples}]
    messages.append({"role": "system", "content": company_context})
    for r in recent:
        messages.append({"role": r.role, "content": r.content[:2000]})
    messages.append({"role": "user", "content": message})

    # 保存用户消息
    save_conversation(user.company_id, user.id, "user", message, db=db)
    db.commit()

    try:
        from app.config import DEEPSEEK_API_KEY as _cfg_key
        api_key = _cfg_key
        if not api_key:
            from app.routers.settings import get_setting
            api_key = get_setting(db, 0, "deepseek_api_key", "")
        if not api_key:
            return JSONResponse({"success": False, "msg": "未配置Deepseek API Key，请联系管理员在系统配置中设置"})

        # 第一次调用：带工具定义
        result = call_deepseek(api_key, messages, TOOL_DEFINITIONS)
        if "choices" not in result or not result["choices"]:
            return JSONResponse({"success": False, "msg": f"API异常: {result.get('error',{}).get('message','未知错误')}"})

        choice = result["choices"][0]
        msg = choice["message"]
        total_tokens = result.get("usage", {}).get("total_tokens", 0)
        prompt_tokens = result.get("usage", {}).get("prompt_tokens", 0)
        completion_tokens = result.get("usage", {}).get("completion_tokens", 0)

        # 处理工具调用
        tool_calls = msg.get("tool_calls", [])
        if tool_calls:
            messages.append(msg)  # AI的tool_call消息
            tool_results = []
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    import json
                    func_args = json.loads(tc["function"]["arguments"])
                except:
                    func_args = {}
                result_text = execute_tool(func_name, func_args, user.company_id, user.id, db)
                tool_results.append(result_text)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text,
                })
            # 第二次调用：AI基于工具结果生成最终回答
            final_result = call_deepseek(api_key, messages)
            if "choices" in final_result and final_result["choices"]:
                reply = final_result["choices"][0]["message"]["content"] or ""
                total_tokens += final_result.get("usage", {}).get("total_tokens", 0)
                prompt_tokens += final_result.get("usage", {}).get("prompt_tokens", 0)
                completion_tokens += final_result.get("usage", {}).get("completion_tokens", 0)
                # 在回复末尾附加工具执行结果摘要
                if tool_results:
                    summaries = [r[:200] for r in tool_results]
                    reply += "\n\n---\n" + "\n".join(summaries)
            else:
                reply = "操作已执行。" + "\n" + "\n".join(r[:300] for r in tool_results)
        else:
            reply = msg.get("content", "")

        # 扫描回复中是否有 [凭证] 标记，自动执行
        import re as _re
        voucher_match = _re.search(r'\[凭证\]\n([\s\S]+?)(?=\n\[|$)', reply)
        if voucher_match:
            lines = voucher_match.group(1).strip().split('\n')
            if len(lines) >= 2:
                header = lines[0].split('|')
                v_date = header[0].strip()
                v_summary = header[1].strip() if len(header) > 1 else ""
                entries = []
                for line in lines[1:]:
                    parts = line.split('|')
                    if len(parts) >= 3:
                        code = parts[0].strip()
                        direction = parts[1].strip()
                        try:
                            amount = float(parts[2].strip())
                        except:
                            continue
                        entry_summary = parts[3].strip() if len(parts) > 3 else v_summary
                        entries.append({"account_code": code, "direction": direction, "amount": amount})
                if entries:
                    tool_result = execute_tool("create_voucher", {
                        "date": v_date, "summary": v_summary, "entries": entries,
                    }, user.company_id, user.id, db)
                    # 替换 [凭证] 部分为执行结果
                    reply = reply.replace(voucher_match.group(0), "").strip()
                    reply += "\n\n" + tool_result

        # 扣减点数并保存对话
        points_used = consume_points(user.company_id, total_tokens, db)
        save_conversation(
            user.company_id, user.id, "assistant", reply,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            points_cost=points_used, db=db,
        )
        db.commit()
        bal = get_or_create_balance(user.company_id, db)

        return JSONResponse({
            "success": True,
            "reply": reply,
            "balance": int(bal.balance),
            "points_cost": points_used,
            "tokens": total_tokens,
        })

    except ImportError:
        return JSONResponse({"success": False, "msg": "缺少 requests 模块，请执行: pip install requests"})
    except Exception as e:
        import traceback
        traceback.print_exc()
        db.rollback()
        return JSONResponse({"success": False, "msg": f"请求失败: {str(e)}"})


@router.post("/recharge")
async def recharge_points(
    request: Request,
    amount: float = Form(...),
    remark: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """充值AI点数（超级管理员操作）"""
    if user.role != "super_admin":
        return JSONResponse({"success": False, "msg": "仅超级管理员可充值"})

    form = await request.form()
    company_id = int(form.get("company_id", 0))
    amount = float(form.get("amount", 0))
    remark = form.get("remark", "")

    if amount <= 0:
        return JSONResponse({"success": False, "msg": "金额必须大于0"})
    points = int(amount / POINT_PRICE)  # 1元=100点

    bal = get_or_create_balance(company_id, db)
    bal.balance = bal.balance + points
    bal.total_recharged = bal.total_recharged + points

    rec = AIRecharge(
        company_id=company_id, amount=amount, points=points,
        operator_id=user.id, remark=remark,
    )
    db.add(rec)
    db.commit()

    comp = db.query(Company).filter(Company.id == company_id).first()
    return JSONResponse({
        "success": True,
        "msg": f"已为【{comp.name if comp else ''}】充值 {amount} 元 = {points} AI点数",
        "balance": int(bal.balance),
    })


@router.get("/recharge-list")
async def recharge_list(
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """充值记录列表（超级管理员）"""
    if user.role != "super_admin":
        return JSONResponse({"success": False, "msg": "无权限"})
    records = db.query(AIRecharge).order_by(AIRecharge.created_at.desc()).limit(100).all()
    data = []
    for r in records:
        comp = db.query(Company).filter(Company.id == r.company_id).first()
        operator = db.query(User).filter(User.id == r.operator_id).first()
        data.append({
            "id": r.id, "company_name": comp.name if comp else "",
            "amount": r.amount, "points": r.points,
            "operator": operator.display_name if operator else "",
            "remark": r.remark or "",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        })
    return JSONResponse({"success": True, "records": data})


@router.get("/balance")
async def check_balance(
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """检查AI点数余额"""
    if not user.company_id:
        return JSONResponse({"balance": 0})
    bal = get_or_create_balance(user.company_id, db)
    return JSONResponse({"balance": int(bal.balance)})


# ==================== 超级管理员训练功能 ====================

@router.get("/train")
async def ai_train_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """AI训练管理页面（超级管理员）"""
    if user.role != "super_admin":
        return RedirectResponse(url="/dashboard", status_code=302)
    examples = db.query(AITrainingExample).order_by(AITrainingExample.sort_order).all()
    # 对话统计
    total_chats = db.query(AIConversation).count()
    total_tokens = db.query(func.sum(AIConversation.prompt_tokens + AIConversation.completion_tokens)).scalar() or 0
    total_points = db.query(func.sum(AIConversation.points_cost)).scalar() or 0
    return templates(request, "ai_train.html", {
        "user": user, "examples": examples,
        "total_chats": total_chats, "total_tokens": total_tokens,
        "total_points": total_points,
    })


@router.post("/train/add")
async def ai_train_add(
    category: str = Form("general"),
    user_message: str = Form(...),
    ai_response: str = Form(...),
    sort_order: int = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    if user.role != "super_admin":
        return JSONResponse({"success": False, "msg": "无权限"})
    ex = AITrainingExample(category=category, user_message=user_message,
                           ai_response=ai_response, sort_order=sort_order)
    db.add(ex); db.commit()
    return JSONResponse({"success": True, "msg": "训练示例已添加"})


@router.get("/train/edit/{ex_id}")
async def ai_train_get(ex_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    """加载单个示例数据"""
    if user.role != "super_admin":
        return JSONResponse({"success": False, "msg": "无权限"})
    ex = db.query(AITrainingExample).filter(AITrainingExample.id == ex_id).first()
    if not ex:
        return JSONResponse({"success": False, "msg": "不存在"})
    return JSONResponse({"success": True, "ex": {
        "id": ex.id, "category": ex.category, "user_message": ex.user_message,
        "ai_response": ex.ai_response, "sort_order": ex.sort_order,
        "is_active": ex.is_active,
    }})


@router.post("/train/edit/{ex_id}")
async def ai_train_edit(
    ex_id: int,
    category: str = Form("general"),
    user_message: str = Form(...),
    ai_response: str = Form(...),
    sort_order: int = Form(0),
    is_active: bool = Form(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    if user.role != "super_admin":
        return JSONResponse({"success": False, "msg": "无权限"})
    ex = db.query(AITrainingExample).filter(AITrainingExample.id == ex_id).first()
    if not ex:
        return JSONResponse({"success": False, "msg": "示例不存在"})
    ex.category = category; ex.user_message = user_message
    ex.ai_response = ai_response; ex.sort_order = sort_order
    ex.is_active = is_active
    db.commit()
    return JSONResponse({"success": True, "msg": "已更新"})


@router.post("/train/delete/{ex_id}")
async def ai_train_delete(ex_id: int, db: Session = Depends(get_db), user: User = Depends(get_login_user)):
    if user.role != "super_admin":
        return JSONResponse({"success": False, "msg": "无权限"})
    db.query(AITrainingExample).filter(AITrainingExample.id == ex_id).delete()
    db.commit()
    return JSONResponse({"success": True, "msg": "已删除"})


@router.get("/status")
async def ai_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_login_user),
):
    """检查AI助手状态（API Key是否配置）"""
    from app.routers.settings import get_setting
    api_key = get_setting(db, 0, "deepseek_api_key", "")
    configured = bool(api_key)
    bal = 0
    if user.company_id:
        bal = get_or_create_balance(user.company_id, db)
        bal = int(bal.balance)
    return JSONResponse({"configured": configured, "balance": bal})
