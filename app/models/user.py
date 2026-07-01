"""数据库模型 - User"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, comment="所属公司ID（超级管理员为NULL）")
    username = Column(String(100), unique=True, nullable=False, comment="用户名")
    display_name = Column(String(100), comment="显示名称")
    password_hash = Column(String(255), nullable=False, comment="密码哈希(bcrypt)")
    role = Column(String(30), nullable=False, comment="角色: super_admin/company_admin/inputer/reviewer/viewer")
    is_active = Column(Boolean, default=True)
    wechat_id = Column(String(100), unique=True, nullable=True, comment="微信号")
    wechat_bound_at = Column(DateTime, nullable=True, comment="微信绑定时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    company = relationship("Company", backref="users")
