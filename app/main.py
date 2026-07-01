"""FastAPI 主应用"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from app.database import init_db
from app.routers import (
    auth, dashboard,
    bank_receipts, invoices,          # 原始凭证
    scenes,                           # 业务场景
    vouchers, closing,                # 凭证与期末处理
    accounts,                         # 科目管理
    reports, assessment,              # 报表与分析
    users, companies,                 # 用户与公司管理
    setup, settings as settings_router,  # 系统设置
    bank_templates,                   # 辅助功能
    ai_assistant,                     # AI智能助手
)

app = FastAPI(title="企业多公司财务管理系统", version="1.0.0")

# 静态文件
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# 注册路由（按业务流程排序）
app.include_router(auth.router)
app.include_router(dashboard.router)          # 工作台
app.include_router(bank_receipts.router)      # 原始凭证→银行回单
app.include_router(invoices.router)           # 原始凭证→发票
app.include_router(scenes.router)             # 业务场景
app.include_router(vouchers.router)           # 凭证管理
app.include_router(closing.router)            # 期末处理
app.include_router(accounts.router)           # 科目管理
app.include_router(reports.router)            # 报表中心
app.include_router(assessment.router)         # 健康测评
app.include_router(users.router)              # 用户管理
app.include_router(companies.router)          # 公司管理
app.include_router(setup.router)              # 期初设置
app.include_router(settings_router.router)    # 系统设置（最后）
app.include_router(bank_templates.router)     # 辅助功能
app.include_router(ai_assistant.router)       # AI智能助手


def _auto_install_modules():
    """检查并自动安装缺少的Python模块"""
    import importlib.util, subprocess, sys

    required = {
        "fpdf": "fpdf2",
        "openpyxl": "openpyxl",
        "pdfplumber": "pdfplumber",
        "qrcode": "qrcode",
        "PIL": "Pillow",
        "requests": "requests",
    }
    for mod_name, pip_name in required.items():
        if importlib.util.find_spec(mod_name) is None:
            print(f"[安装] 检测到缺少模块 '{pip_name}'，正在自动安装...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pip_name, "-q"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                print(f"[安装] '{pip_name}' 安装完成")
            except Exception as e:
                print(f"[安装] '{pip_name}' 自动安装失败: {e}")


@app.on_event("startup")
async def startup():
    """应用启动时初始化数据库"""
    _auto_install_modules()
    init_db()

    # 迁移：为已有数据库添加 expiry_type / expiry_date 字段
    import sqlalchemy as sa
    from app.database import engine as _engine

    # 迁移：为已有users表添加wechat_id字段
    try:
        inspector = sa.inspect(_engine)
        columns = [c["name"] for c in inspector.get_columns("users")]
        if "wechat_id" not in columns:
            with _engine.connect() as conn:
                conn.execute(sa.text("ALTER TABLE users ADD COLUMN wechat_id VARCHAR(100)"))
                conn.execute(sa.text("ALTER TABLE users ADD COLUMN wechat_bound_at DATETIME"))
                conn.commit()
                print("[迁移] 已添加 users.wechat_id / users.wechat_bound_at 字段")
    except Exception as e:
        print(f"[迁移] users.wechat_id 迁移跳过: {e}")

    try:
        inspector = sa.inspect(_engine)
        columns = [c["name"] for c in inspector.get_columns("companies")]
        if "expiry_type" not in columns:
            with _engine.connect() as conn:
                conn.execute(sa.text("ALTER TABLE companies ADD COLUMN expiry_type VARCHAR(20) DEFAULT 'permanent'"))
                conn.execute(sa.text("ALTER TABLE companies ADD COLUMN expiry_date DATE"))
                conn.commit()
                print("[迁移] 已添加 companies.expiry_type / expiry_date 字段")
    except Exception as e:
        print(f"[迁移] companies 字段迁移跳过: {e}")

    try:
        inspector = sa.inspect(_engine)
        columns = [c["name"] for c in inspector.get_columns("companies")]
        if "contact_person" not in columns:
            with _engine.connect() as conn:
                conn.execute(sa.text("ALTER TABLE companies ADD COLUMN contact_person VARCHAR(100)"))
                conn.execute(sa.text("ALTER TABLE companies ADD COLUMN contact_phone VARCHAR(50)"))
                conn.commit()
                print("[迁移] 已添加 companies.contact_person / contact_phone 字段")
    except Exception as e:
        print(f"[迁移] companies 联系人字段迁移跳过: {e}")

    # 迁移：system_settings 表去掉外键约束（支持全局配置 company_id=0）
    try:
        inspector = sa.inspect(_engine)
        fks = inspector.get_foreign_keys("system_settings")
        if fks:
            with _engine.connect() as conn:
                conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
                conn.execute(sa.text("CREATE TABLE system_settings_new (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL DEFAULT 0, setting_key VARCHAR(100) NOT NULL, setting_value VARCHAR(500) DEFAULT '', created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"))
                conn.execute(sa.text("INSERT INTO system_settings_new SELECT id, company_id, setting_key, setting_value, created_at, updated_at FROM system_settings"))
                conn.execute(sa.text("DROP TABLE system_settings"))
                conn.execute(sa.text("ALTER TABLE system_settings_new RENAME TO system_settings"))
                conn.execute(sa.text("PRAGMA foreign_keys=ON"))
                conn.commit()
                print("[迁移] system_settings 表已重建，外键约束已移除")
    except Exception as e:
        print(f"[迁移] system_settings 迁移跳过: {e}")

    # 迁移：创建并升级各辅助表
    extra_tables = [
        ("ReportCache", "report_cache", "pdf_path", "VARCHAR(500)"),
        ("SceneRule", "scene_rules", None, None),
        ("FinancialAssessment", "financial_assessments", None, None),
        ("AIPointBalance", "ai_point_balances", None, None),
        ("AIRecharge", "ai_recharges", None, None),
        ("AIConversation", "ai_conversations", None, None),
        ("AITrainingExample", "ai_training_examples", None, None),
    ]
    for cls_name, table_name, col_name, col_type in extra_tables:
        try:
            mod = __import__("app.models.misc", fromlist=[cls_name])
            ModelClass = getattr(mod, cls_name)
            existed = ModelClass.__table__.exists(_engine)
            ModelClass.__table__.create(_engine, checkfirst=True)
            if not existed:
                print(f"[迁移] 已创建 {table_name} 表")
            if col_name:
                inspector = sa.inspect(_engine)
                columns = [c["name"] for c in inspector.get_columns(table_name)]
                if col_name not in columns:
                    with _engine.connect() as conn:
                        conn.execute(sa.text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
                        print(f"[迁移] 已添加 {table_name}.{col_name} 字段")
        except Exception as e:
            print(f"[迁移] {table_name} 处理跳过: {e}")

    # 种子数据：首次创建 ai_training_examples 表时注入默认训练示例
    try:
        from app.models.misc import AITrainingExample as _ATE
        if _ATE.__table__.exists(_engine):
            sess = SessionLocal()
            cnt = sess.query(_ATE).count()
            if cnt == 0:
                _seeds = [
                    ("general", "你是谁", "我是AI财务管理系统的内置AI财务助手", 0),
                    ("general", "怎么新增凭证", "进入 [凭证录入] 页面填写日期科目金额，借贷平衡保存", 1),
                    ("voucher", "录入一张加油费凭证285元", "已创建凭证\n[凭证]\n2027-01-23|报销加油费\n5602|借|285.00\n1002|贷|285.00", 10),
                    ("voucher", "报销差旅费1200元", "已创建凭证\n[凭证]\n2027-01-23|报销差旅费\n5602|借|1200.00\n1002|贷|1200.00", 11),
                    ("voucher", "发工资总额10万实发8万个税5千社保1.5万", "已创建两张凭证\n[凭证]\n2027-01-25|计提工资\n5602|借|100000.00\n2211|贷|100000.00\n[凭证]\n2027-01-25|发放工资\n2211|借|100000.00\n1002|贷|80000.00\n2221|贷|5000.00\n2241|贷|15000.00", 12),
                    ("voucher", "支付房租8000元", "已创建凭证\n[凭证]\n2027-01-23|支付房租\n5602|借|8000.00\n1002|贷|8000.00", 13),
                    ("voucher", "收到货款50000元", "已创建凭证\n[凭证]\n2027-01-23|收到货款\n1002|借|50000.00\n5001|贷|50000.00", 14),
                    ("voucher", "缴纳税费12000元", "已创建凭证\n[凭证]\n2027-01-23|缴纳税费\n2221|借|12000.00\n1002|贷|12000.00", 15),
                    ("voucher", "购买办公电脑6000元", "已创建凭证\n[凭证]\n2027-01-23|购买电脑\n1601|借|6000.00\n1002|贷|6000.00", 16),
                    ("accounting", "管理费用包括哪些", "办公费/差旅费/房租/工资/社保/折旧等。科目5602", 20),
                    ("accounting", "固定资产标准", "使用寿命超1年的有形资产。科目1601，计提折旧用1602", 21),
                    ("accounting", "资产负债表和利润表关系", "净利润通过年末结转进入利润分配，影响所有者权益", 22),
                    ("general", "系统没有月份初始化功能", "系统无需手动初始化月份。结账后下一月自动可用，直接选日期录入即可", 4),
                    ("general", "2027年1月怎么开账", "系统无需手动开账，当前月结账后下一月自动可用，直接录入凭证即可", 5),
                    ("general", "月末要做什么", "在 [工作台] 按顺序: 凭证过账→损益结转→月末结账", 30),
                    ("general", "如何导入银行回单", "进入 [银行回单] 选择PDF导入，系统自动解析", 31),
                ]
                for cat, um, ar, so in _seeds:
                    sess.add(_ATE(category=cat, user_message=um, ai_response=ar, sort_order=so, is_active=True))
                sess.commit()
                print(f"[种子] 已注入 {len(_seeds)} 条默认训练示例")
            sess.close()
    except Exception as e:
        print(f"[种子] ai_training_examples 种子处理跳过: {e}")

    # 检查是否需要创建默认超级管理员
    from app.database import SessionLocal
    from app.models import User
    from app.services.auth_service import hash_password

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                company_id=None,
                username="admin",
                display_name="超级管理员",
                password_hash=hash_password("admin123"),
                role="super_admin",
            )
            db.add(admin)
            db.commit()
            print("已创建默认超级管理员: admin / admin123")
    finally:
        db.close()


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")
