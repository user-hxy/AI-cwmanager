"""凭证业务逻辑服务"""
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from app.models import Voucher, VoucherEntry, Account, AccountBalance, Company
from app.models.misc import ClosingPeriod, AuditLog
from app.config import INCOME_ACCOUNT_CODES, EXPENSE_ACCOUNT_CODES


def generate_voucher_no(db: Session, company_id: int, voucher_word: str, year: int, month: int) -> tuple:
    """生成凭证号：支-YYYYMM-XXXX"""
    prefix = f"{voucher_word}-{year}{month:02d}-"
    last_voucher = (
        db.query(Voucher)
        .filter(
            Voucher.company_id == company_id,
            Voucher.voucher_word == voucher_word,
            sqlfunc.extract("year", Voucher.date) == year,
            sqlfunc.extract("month", Voucher.date) == month,
        )
        .order_by(Voucher.serial_no.desc())
        .first()
    )
    seq = (last_voucher.serial_no + 1) if last_voucher else 1
    return f"{prefix}{seq:04d}", seq


def batch_generate_numbers(db: Session, company_id: int, year: int, month: int) -> dict:
    """批量统一生成凭证号：按付→收→转顺序，同字内按日期排序，所有状态凭证均参与"""
    all_vouchers = (
        db.query(Voucher)
        .filter(
            Voucher.company_id == company_id,
            sqlfunc.extract("year", Voucher.date) == year,
            sqlfunc.extract("month", Voucher.date) == month,
        )
        .order_by(
            Voucher.source_type != "carry_forward",  # 结转凭证排最前
            Voucher.date,
            Voucher.id,
        )
        .all()
    )

    # 按凭证字分组
    grouped = {}
    for v in all_vouchers:
        word = v.voucher_word or "转"
        if word not in grouped:
            grouped[word] = []
        grouped[word].append(v)

    stats = {}
    for word in ["付", "收", "转"]:
        vouchers = grouped.get(word, [])
        if not vouchers:
            continue
        seq = 1
        prefix = f"{word}-{year}{month:02d}-"
        for v in vouchers:
            new_no = f"{prefix}{seq:04d}"
            v.voucher_no = new_no
            v.serial_no = seq
            seq += 1
        stats[word] = seq - 1

    return stats


def check_balance(voucher_id: int, db: Session) -> bool:
    """检查凭证借贷是否平衡"""
    entries = db.query(VoucherEntry).filter(VoucherEntry.voucher_id == voucher_id).all()
    debit_sum = sum(e.amount for e in entries if e.direction == "借")
    credit_sum = sum(e.amount for e in entries if e.direction == "贷")
    return abs(debit_sum - credit_sum) < 0.01


def post_voucher(voucher_id: int, user_id: int, db: Session) -> tuple:
    """过账：更新科目余额表"""
    voucher = db.query(Voucher).filter(Voucher.id == voucher_id).first()
    if not voucher:
        return False, "凭证不存在"
    if voucher.status != "approved":
        return False, "只有已审核凭证才能过账"
    if not check_balance(voucher_id, db):
        return False, "凭证借贷不平衡，无法过账"

    period = voucher.date.strftime("%Y-%m")
    entries = db.query(VoucherEntry).filter(VoucherEntry.voucher_id == voucher_id).all()

    for entry in entries:
        balance = db.query(AccountBalance).filter(
            AccountBalance.company_id == voucher.company_id,
            AccountBalance.account_id == entry.account_id,
            AccountBalance.period == period,
        ).first()
        if not balance:
            acct = db.query(Account).filter(Account.id == entry.account_id).first()
            prev = db.query(AccountBalance).filter(
                AccountBalance.company_id == voucher.company_id,
                AccountBalance.account_id == entry.account_id,
                AccountBalance.period < period,
            ).order_by(AccountBalance.period.desc()).first()
            opening = prev.closing_balance if prev else 0
            balance = AccountBalance(
                company_id=voucher.company_id,
                account_id=entry.account_id,
                period=period,
                opening_balance=opening,
                debit_amount=0,
                credit_amount=0,
                closing_balance=opening,
            )
            db.add(balance)
            db.flush()

        if entry.direction == "借":
            balance.debit_amount = (balance.debit_amount or 0) + entry.amount
        else:
            balance.credit_amount = (balance.credit_amount or 0) + entry.amount
        # 按科目方向正确计算期末余额
        acct = db.query(Account).filter(Account.id == entry.account_id).first()
        if acct and acct.direction == "贷":
            balance.closing_balance = balance.opening_balance + balance.credit_amount - balance.debit_amount
        else:
            balance.closing_balance = balance.opening_balance + balance.debit_amount - balance.credit_amount

    voucher.status = "posted"
    voucher.poster_id = user_id
    voucher.posted_at = datetime.now()
    db.commit()
    return True, "过账成功"


def unpost_voucher(voucher_id: int, db: Session) -> tuple:
    """反过账（超级管理员权限）"""
    voucher = db.query(Voucher).filter(Voucher.id == voucher_id).first()
    if not voucher:
        return False, "凭证不存在"
    if voucher.status != "posted":
        return False, "只有已过账凭证才能反过账"
    if voucher.source_type == "carry_forward":
        return False, "结转凭证不允许直接反过账，请使用反结转功能"

    period = voucher.date.strftime("%Y-%m")
    entries = db.query(VoucherEntry).filter(VoucherEntry.voucher_id == voucher_id).all()
    for entry in entries:
        balance = (
            db.query(AccountBalance)
            .filter(
                AccountBalance.company_id == voucher.company_id,
                AccountBalance.account_id == entry.account_id,
                AccountBalance.period == period,
            )
            .first()
        )
        if balance:
            if entry.direction == "借":
                balance.debit_amount -= entry.amount
            else:
                balance.credit_amount -= entry.amount
            # 按科目方向正确计算期末余额
            acct = db.query(Account).filter(Account.id == entry.account_id).first()
            if acct and acct.direction == "贷":
                balance.closing_balance = balance.opening_balance + balance.credit_amount - balance.debit_amount
            else:
                balance.closing_balance = balance.opening_balance + balance.debit_amount - balance.credit_amount

    voucher.status = "approved"
    voucher.poster_id = None
    voucher.posted_at = None
    db.commit()
    return True, "反过账成功"
