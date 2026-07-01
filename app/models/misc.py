"""数据库模型 - 银行回单、发票、结账、审计日志等辅助表"""
from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, Text, ForeignKey, func
from app.database import Base


class BankReceipt(Base):
    """银行回单"""
    __tablename__ = "bank_receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    bank_account = Column(String(100), comment="银行账号")
    bank_name = Column(String(100), comment="银行名称")
    receipt_type = Column(String(50), comment="回单类型")
    payer_name = Column(String(200), comment="付款人")
    payee_name = Column(String(200), comment="收款人")
    amount = Column(Float, default=0, comment="金额")
    transaction_date = Column(Date, comment="交易日期")
    remark = Column(Text, comment="附言/摘要")
    fee = Column(Float, default=0, comment="手续费")
    raw_text = Column(Text, comment="原始解析文本")
    parse_confidence = Column(String(10), default="高", comment="解析置信度: 高/中/低")
    voucher_id = Column(Integer, ForeignKey("vouchers.id"), nullable=True, comment="关联凭证ID")
    status = Column(String(20), default="unprocessed", comment="状态: unprocessed/processed")
    created_at = Column(DateTime, server_default=func.now())


class Invoice(Base):
    """发票"""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    invoice_type = Column(String(50), comment="发票类型")
    invoice_no = Column(String(30), comment="发票号码")
    invoice_code = Column(String(30), comment="发票代码")
    issue_date = Column(Date, comment="开票日期")
    buyer_name = Column(String(200), comment="购买方名称")
    buyer_tax_id = Column(String(50), comment="购买方税号")
    seller_name = Column(String(200), comment="销售方名称")
    seller_tax_id = Column(String(50), comment="销售方税号")
    total_amount = Column(Float, default=0, comment="金额(不含税)")
    total_tax = Column(Float, default=0, comment="税额")
    total_price = Column(Float, default=0, comment="价税合计")
    detail_items = Column(Text, comment="项目明细(JSON)")
    is_deductible = Column(Boolean, default=False, comment="是否可抵扣")
    verify_status = Column(String(20), default="unverified", comment="验真状态")
    voucher_id = Column(Integer, ForeignKey("vouchers.id"), nullable=True, comment="关联凭证ID")
    status = Column(String(20), default="unprocessed")
    file_path = Column(String(500), comment="文件路径")
    created_at = Column(DateTime, server_default=func.now())


class InvoiceTemplate(Base):
    """发票解析模板"""
    __tablename__ = "invoice_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    invoice_type = Column(String(50), comment="发票类型")
    name = Column(String(100), comment="模板名称")
    parse_rules = Column(Text, comment="解析规则(JSON)")
    mapping_rules = Column(Text, comment="科目映射规则(JSON)")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class BankTemplate(Base):
    """银行回单解析模板"""
    __tablename__ = "bank_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    bank_name = Column(String(100), comment="银行名称")
    name = Column(String(100), comment="模板名称")
    regex_rules = Column(Text, comment="正则提取规则(JSON)")
    mapping_rules = Column(Text, comment="科目映射规则(JSON)")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class Counterparty(Base):
    """往来单位"""
    __tablename__ = "counterparties"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    type = Column(String(20), comment="类型: customer/supplier/employee")
    name = Column(String(200), nullable=False, comment="名称")
    code = Column(String(50), comment="编码")
    contact = Column(String(100), comment="联系人")
    phone = Column(String(50), comment="电话")
    department = Column(String(100), comment="部门(员工)")
    id_card = Column(String(30), comment="身份证号(员工)")
    address = Column(String(300), comment="地址")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class BankAccount(Base):
    """银行账户"""
    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    account_name = Column(String(200), comment="户名")
    account_no = Column(String(50), comment="账号")
    bank_name = Column(String(100), comment="开户行")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class ClosingPeriod(Base):
    """月末结账记录"""
    __tablename__ = "closing_periods"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    period = Column(String(7), nullable=False, comment="会计期间 yyyy-mm")
    is_closed = Column(Boolean, default=False, comment="是否已结账")
    is_carried_forward = Column(Boolean, default=False, comment="是否已结转损益")
    closed_by = Column(Integer, ForeignKey("users.id"), nullable=True, comment="结账人")
    closed_at = Column(DateTime, comment="结账时间")
    carry_forward_voucher_id = Column(Integer, nullable=True, comment="结转凭证ID")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Attachment(Base):
    """附件"""
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    source_type = Column(String(30), comment="来源: voucher/bank_receipt/invoice")
    source_id = Column(Integer, comment="来源ID")
    file_name = Column(String(255), comment="文件名")
    file_path = Column(String(500), comment="文件路径")
    file_size = Column(Integer, comment="文件大小(字节)")
    upload_time = Column(DateTime, server_default=func.now())


class SceneRule(Base):
    """常用业务场景规则"""
    __tablename__ = "scene_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    name = Column(String(100), nullable=False, comment="场景名称")
    keywords = Column(String(500), comment="匹配关键词（逗号分隔）")
    debit_account_code = Column(String(20), nullable=False, comment="借方科目编码")
    debit_account_name = Column(String(100), comment="借方科目名称")
    credit_account_code = Column(String(20), nullable=False, comment="贷方科目编码")
    credit_account_name = Column(String(100), comment="贷方科目名称")
    category = Column(String(50), comment="分组: 收入类/费用类/工资福利/研发资产/税务银行/借款往来/权益其他")
    icon = Column(String(10), default="📄", comment="图标")
    sort_order = Column(Integer, default=0, comment="排序")
    is_active = Column(Boolean, default=True, comment="是否启用")
    is_builtin = Column(Boolean, default=False, comment="是否为内置默认规则")
    is_frequent = Column(Boolean, default=False, comment="是否常用场景")
    created_at = Column(DateTime, server_default=func.now())


class KeyWordMapping(Base):
    """关键词科目映射（兼容旧版，新系统使用SceneRule）"""
    __tablename__ = "keyword_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    keyword = Column(String(100), nullable=False, comment="关键词")
    account_code = Column(String(20), nullable=False, comment="目标科目编码")
    account_name = Column(String(100), comment="目标科目名称")
    direction = Column(String(4), comment="凭证方向")
    source_type = Column(String(20), default="bank", comment="来源: bank/invoice")
    created_at = Column(DateTime, server_default=func.now())


class SystemSetting(Base):
    """系统设置（company_id=0 表示全局配置）"""
    __tablename__ = "system_settings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, nullable=False, default=0, comment="企业ID, 0=全局")
    setting_key = Column(String(100), nullable=False, comment="设置键")
    setting_value = Column(String(500), default="", comment="设置值")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    """审计日志"""
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    username = Column(String(100), comment="用户名")
    action = Column(String(50), nullable=False, comment="操作标识")
    target_type = Column(String(30), comment="目标类型")
    target_id = Column(Integer, comment="目标ID")
    detail = Column(Text, comment="详细描述")
    ip_address = Column(String(50), comment="操作IP")
    created_at = Column(DateTime, server_default=func.now())


class ReportCache(Base):
    """统计报表缓存"""
    __tablename__ = "report_cache"
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    report_type = Column(String(30), nullable=False, comment="报表类型: trial_balance/balance_sheet/income_statement")
    period_type = Column(String(20), default="month", comment="期间类型: month/quarter/half_year/year")
    start_period = Column(String(10), nullable=False, comment="起始期间 YYYY-MM")
    end_period = Column(String(10), nullable=False, comment="截止期间 YYYY-MM")
    title = Column(String(200), comment="报表标题")
    data = Column(Text, comment="报表数据(JSON)")
    pdf_path = Column(String(500), comment="PDF文件路径")
    created_at = Column(DateTime, server_default=func.now())


class PeriodSummary(Base):
    """月度财务快照 — 结账时自动生成，用于快速聚合季/半年/年报"""
    __tablename__ = "period_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    period = Column(String(7), nullable=False, comment="会计期间 yyyy-mm")

    # 资产负债表关键指标
    total_assets = Column(Float, default=0, comment="资产总计")
    total_liabilities = Column(Float, default=0, comment="负债合计")
    total_equity = Column(Float, default=0, comment="所有者权益合计")

    # 利润表关键指标
    revenue = Column(Float, default=0, comment="营业收入")
    total_cost = Column(Float, default=0, comment="营业成本")
    sell_expense = Column(Float, default=0, comment="营业费用")
    mgmt_expense = Column(Float, default=0, comment="管理费用")
    finance_expense = Column(Float, default=0, comment="财务费用")
    net_profit = Column(Float, default=0, comment="净利润")

    # 账户级余额快照 (JSON) — 用于精确重建三大报表
    account_snapshot = Column(Text, comment="科目余额快照 JSON: {account_id: {code,name,category,direction,opening,debit,credit,closing}}")

    created_at = Column(DateTime, server_default=func.now())

    @property
    def year(self) -> str:
        return self.period[:4]

    @property
    def month(self) -> int:
        return int(self.period[5:7])


class FinancialAssessment(Base):
    """企业财务健康度测评记录"""
    __tablename__ = "financial_assessments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    model_id = Column(String(50), nullable=False, comment="测评模型ID")
    period = Column(String(7), nullable=False, comment="会计期间 yyyy-mm")
    score = Column(Float, default=0, comment="评分")
    level = Column(String(20), comment="评级: 优秀/良好/一般/关注/风险")
    result_data = Column(Text, comment="测评结果详细数据(JSON)")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class AIPointBalance(Base):
    """AI点数余额"""
    __tablename__ = "ai_point_balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    balance = Column(Float, default=0, comment="剩余AI点数")
    total_recharged = Column(Float, default=0, comment="累计充值点数")
    total_consumed = Column(Float, default=0, comment="累计消耗点数")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AIRecharge(Base):
    """AI点数充值记录"""
    __tablename__ = "ai_recharges"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    amount = Column(Float, nullable=False, comment="充值金额(元)")
    points = Column(Float, nullable=False, comment="获得AI点数")
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True, comment="操作人")
    remark = Column(String(200), comment="备注")
    created_at = Column(DateTime, server_default=func.now())


class AITrainingExample(Base):
    """AI训练示例 — 超级管理员可添加自定义示例对"""
    __tablename__ = "ai_training_examples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String(50), default="general", comment="分类: general/voucher/report/accounting")
    user_message = Column(Text, nullable=False, comment="用户问题")
    ai_response = Column(Text, nullable=False, comment="期望的AI回复")
    sort_order = Column(Integer, default=0, comment="排序")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class AIConversation(Base):
    """AI对话记录"""
    __tablename__ = "ai_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), nullable=False, comment="角色: user/assistant/system")
    content = Column(Text, nullable=False, comment="消息内容")
    prompt_tokens = Column(Integer, default=0, comment="提示Token数")
    completion_tokens = Column(Integer, default=0, comment="回复Token数")
    points_cost = Column(Float, default=0, comment="消耗AI点数")
    created_at = Column(DateTime, server_default=func.now())
