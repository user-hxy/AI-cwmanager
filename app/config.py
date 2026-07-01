"""系统配置模块"""
import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

# 加载 .env 文件（如果存在）
try:
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in open(env_path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
except Exception:
    pass

# 数据库
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/finance.db")

# JWT
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-to-a-secure-random-key-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8小时

# Deepseek AI 配置（优先读环境变量，未设置则在系统配置页面填入）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# 上传目录
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# 公司默认科目（小企业会计准则一级科目）
DEFAULT_ACCOUNTS = [
    ("1001", "库存现金", "资产", True, False),
    ("1002", "银行存款", "资产", True, False),
    ("1012", "其他货币资金", "资产", True, False),
    ("1101", "短期投资", "资产", True, False),
    ("1121", "应收票据", "资产", True, False),
    ("1122", "应收账款", "资产", True, False),
    ("1123", "预付账款", "资产", True, False),
    ("1131", "应收股利", "资产", True, False),
    ("1132", "应收利息", "资产", True, False),
    ("1221", "其他应收款", "资产", True, False),
    ("1231", "坏账准备", "资产", True, True),
    ("1401", "材料采购", "资产", True, False),
    ("1402", "在途物资", "资产", True, False),
    ("1403", "原材料", "资产", True, False),
    ("1404", "材料成本差异", "资产", True, True),
    ("1405", "库存商品", "资产", True, False),
    ("1407", "商品进销差价", "资产", True, True),
    ("1408", "委托加工物资", "资产", True, False),
    ("1411", "周转材料", "资产", True, False),
    ("1421", "消耗性生物资产", "资产", True, False),
    ("1501", "长期债券投资", "资产", True, False),
    ("1511", "长期股权投资", "资产", True, False),
    ("1601", "固定资产", "资产", True, False),
    ("1602", "累计折旧", "资产", True, True),
    ("1603", "固定资产减值准备", "资产", True, True),
    ("1604", "在建工程", "资产", True, False),
    ("1605", "工程物资", "资产", True, False),
    ("1606", "固定资产清理", "资产", True, False),
    ("1621", "生产性生物资产", "资产", True, False),
    ("1622", "生产性生物资产累计折旧", "资产", True, True),
    ("1701", "无形资产", "资产", True, False),
    ("1702", "累计摊销", "资产", True, True),
    ("1703", "无形资产减值准备", "资产", True, True),
    ("1801", "长期待摊费用", "资产", True, False),
    ("1901", "待处理财产损溢", "资产", True, False),
    ("2001", "短期借款", "负债", True, False),
    ("2201", "应付票据", "负债", True, False),
    ("2202", "应付账款", "负债", True, False),
    ("2203", "预收账款", "负债", True, False),
    ("2211", "应付职工薪酬", "负债", True, False),
    ("2221", "应交税费", "负债", True, False),
    ("2231", "应付利息", "负债", True, False),
    ("2232", "应付利润", "负债", True, False),
    ("2241", "其他应付款", "负债", True, False),
    ("2401", "递延收益", "负债", True, False),
    ("2501", "长期借款", "负债", True, False),
    ("2701", "长期应付款", "负债", True, False),
    ("3001", "实收资本", "权益", True, False),
    ("3002", "资本公积", "权益", True, False),
    ("3101", "盈余公积", "权益", True, False),
    ("3103", "本年利润", "权益", True, False),
    ("3104", "利润分配", "权益", True, False),
    ("4001", "生产成本", "成本", True, False),
    ("4101", "制造费用", "成本", True, False),
    ("4301", "研发支出", "成本", True, False),
    ("4401", "工程施工", "成本", True, False),
    ("4403", "机械作业", "成本", True, False),
    ("5001", "主营业务收入", "损益", True, False),
    ("5051", "其他业务收入", "损益", True, False),
    ("5111", "投资收益", "损益", True, False),
    ("5301", "营业外收入", "损益", True, False),
    ("5401", "主营业务成本", "损益", True, False),
    ("5402", "其他业务成本", "损益", True, False),
    ("5403", "税金及附加", "损益", True, False),
    ("5601", "销售费用", "损益", True, False),
    ("5602", "管理费用", "损益", True, False),
    ("5603", "财务费用", "损益", True, False),
    ("5711", "营业外支出", "损益", True, False),
    ("5801", "所得税费用", "损益", True, False),
    ("5901", "以前年度损益调整", "损益", True, False),
]

# 收入类科目代码集合（用于损益结转）
INCOME_ACCOUNT_CODES = {"5001", "5051", "5111", "5301"}

# 费用类科目代码集合
EXPENSE_ACCOUNT_CODES = {"5401", "5402", "5403", "5601", "5602", "5603", "5711", "5801", "4301"}

# 角色定义
ROLES = {
    "super_admin": "超级管理员",
    "company_admin": "公司管理员",
    "inputer": "凭证录入员",
    "reviewer": "凭证审核员",
    "viewer": "报表查看者",
}
