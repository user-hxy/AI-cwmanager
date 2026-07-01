"""数据库模型 - Voucher & VoucherEntry（凭证及分录）"""
from sqlalchemy import Column, Integer, String, Date, DateTime, Float, Text, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class Voucher(Base):
    __tablename__ = "vouchers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, comment="所属公司")
    voucher_no = Column(String(50), comment="凭证号")
    date = Column(Date, nullable=False, comment="凭证日期")
    voucher_word = Column(String(10), default="记", comment="凭证字")
    serial_no = Column(Integer, default=0, comment="当月流水号")
    summary = Column(String(500), comment="摘要")
    status = Column(String(20), default="draft", comment="状态: draft/pending/approved/posted")
    source_type = Column(String(30), comment="来源: manual/bank_receipt/invoice/carry_forward/copy")
    source_id = Column(Integer, comment="来源单据ID")
    source_ref_id = Column(Integer, nullable=True, comment="复制来源凭证ID(用于追溯)")
    creator_id = Column(Integer, ForeignKey("users.id"), comment="制单人")
    reviewer_id = Column(Integer, ForeignKey("users.id"), comment="审核人")
    poster_id = Column(Integer, ForeignKey("users.id"), comment="过账人")
    attachment_count = Column(Integer, default=0, comment="附件张数")
    reject_reason = Column(Text, comment="驳回原因")
    reviewed_at = Column(DateTime)
    posted_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    company = relationship("Company")
    creator = relationship("User", foreign_keys=[creator_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])
    poster = relationship("User", foreign_keys=[poster_id])
    entries = relationship("VoucherEntry", back_populates="voucher", cascade="all, delete-orphan")


class VoucherEntry(Base):
    __tablename__ = "voucher_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    voucher_id = Column(Integer, ForeignKey("vouchers.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, comment="科目ID")
    account_code = Column(String(20), comment="科目编码（冗余）")
    account_name = Column(String(100), comment="科目名称（冗余）")
    direction = Column(String(4), nullable=False, comment="方向: 借/贷")
    amount = Column(Float, default=0, comment="金额")
    summary = Column(String(200), comment="分录摘要")
    auxiliary_info = Column(Text, comment="辅助核算信息(JSON)")
    sort_order = Column(Integer, default=0, comment="排序")

    voucher = relationship("Voucher", back_populates="entries")
