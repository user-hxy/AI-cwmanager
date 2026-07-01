"""数据库模型 - AccountBalance（科目余额表）"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, func
from app.database import Base


class AccountBalance(Base):
    __tablename__ = "account_balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    period = Column(String(7), nullable=False, comment="会计期间 yyyy-mm")
    opening_balance = Column(Float, default=0, comment="期初余额")
    debit_amount = Column(Float, default=0, comment="本期借方发生")
    credit_amount = Column(Float, default=0, comment="本期贷方发生")
    closing_balance = Column(Float, default=0, comment="期末余额")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
