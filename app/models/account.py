"""数据库模型 - Account（科目表）"""
from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, comment="所属公司")
    code = Column(String(20), nullable=False, comment="科目编码")
    name = Column(String(100), nullable=False, comment="科目名称")
    parent_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, comment="父科目ID")
    category = Column(String(20), nullable=False, comment="类别: 资产/负债/权益/成本/损益")
    direction = Column(String(4), default="借", comment="方向: 借/贷")
    is_detail = Column(Boolean, default=False, comment="是否最末级明细科目")
    is_system = Column(Boolean, default=False, comment="是否系统预设")
    level = Column(Integer, default=1, comment="级次")
    created_at = Column(DateTime, server_default=func.now())

    parent = relationship("Account", remote_side=[id], backref="children")
