"""数据库模型 - Company"""
from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, func
from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, comment="公司名称")
    code = Column(String(50), unique=True, nullable=False, comment="公司编码")
    tax_id = Column(String(50), comment="统一社会信用代码")
    start_date = Column(Date, comment="启用日期")
    industry = Column(String(100), comment="所属行业")
    contact_person = Column(String(100), comment="联系人")
    contact_phone = Column(String(50), comment="联系电话")
    status = Column(String(20), default="active", comment="状态: active/disabled")
    is_initialized = Column(Boolean, default=False, comment="是否已完成期初设置")
    expiry_type = Column(String(20), default="permanent", comment="使用时效类型: permanent/fixed")
    expiry_date = Column(Date, nullable=True, comment="使用截止日期(expiry_type=fixed时有效)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    @property
    def is_expired(self) -> bool:
        """判断公司是否已过期"""
        from datetime import date
        if self.expiry_type == "permanent":
            return False
        if self.expiry_type == "fixed" and self.expiry_date:
            return date.today() > self.expiry_date
        return False

    @property
    def expiry_display(self) -> str:
        """获取使用时效显示文本"""
        if self.expiry_type == "permanent":
            return "永久"
        if self.expiry_type == "fixed" and self.expiry_date:
            return f"至 {self.expiry_date.isoformat()}"
        return "永久"
