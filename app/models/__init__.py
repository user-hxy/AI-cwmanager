"""模型注册入口"""
from app.models.company import Company
from app.models.user import User
from app.models.account import Account
from app.models.voucher import Voucher, VoucherEntry
from app.models.balance import AccountBalance
from app.models.misc import (
    BankReceipt, Invoice, InvoiceTemplate, BankTemplate,
    Counterparty, BankAccount, ClosingPeriod, Attachment,
    KeyWordMapping, AuditLog, ReportCache, FinancialAssessment,
)
