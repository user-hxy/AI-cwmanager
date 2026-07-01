"""期末结转与反结转服务"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Voucher, VoucherEntry, Account, AccountBalance, Company
from app.models.misc import ClosingPeriod, AuditLog
from app.config import INCOME_ACCOUNT_CODES, EXPENSE_ACCOUNT_CODES
from app.services.voucher_service import generate_voucher_no, post_voucher


def can_carry_forward(company_id: int, period: str, db: Session) -> tuple:
    """检查是否满足结转前置条件"""
    cp = db.query(ClosingPeriod).filter(
        ClosingPeriod.company_id == company_id, ClosingPeriod.period == period
    ).first()
    if cp and cp.is_carried_forward:
        return False, "本期已结转损益"

    # 检查是否有未过账的非结转凭证（列出详情）
    unposted_list = db.query(Voucher).filter(
        Voucher.company_id == company_id,
        sqlfunc_extract_year_month(Voucher.date) == period,
        Voucher.status.in_(["draft", "pending", "approved"]),
        Voucher.source_type != "carry_forward",
    ).all()
    if unposted_list:
        details = "；".join([f"{v.voucher_no}({v.summary or '无摘要'})" for v in unposted_list[:5]])
        if len(unposted_list) > 5:
            details += f" 等{len(unposted_list)}张"
        return False, f"存在 {len(unposted_list)} 张未过账凭证：{details}，请先过账后再结转"

    # 检查是否有已过账的非结转凭证
    has_posted = db.query(Voucher).filter(
        Voucher.company_id == company_id,
        sqlfunc_extract_year_month(Voucher.date) == period,
        Voucher.status == "posted",
    ).first()
    if not has_posted:
        return False, "本期无已过账凭证，无需结转"

    return True, "可以结转"


def sqlfunc_extract_year_month(query):
    """跨数据库的日期提取占位"""
    from sqlalchemy import func
    return func.strftime("%Y-%m", Voucher.date)


def carry_forward(company_id: int, user_id: int, period: str, db: Session) -> tuple:
    """执行损益结转"""
    ok, msg = can_carry_forward(company_id, period, db)
    if not ok:
        return False, msg

    cp = db.query(ClosingPeriod).filter(
        ClosingPeriod.company_id == company_id, ClosingPeriod.period == period
    ).first()

    # 获取本年利润科目
    profit_acct = db.query(Account).filter(
        Account.company_id == company_id, Account.code == "3103"
    ).first()
    if not profit_acct:
        return False, "未找到本年利润科目(3103)，请先设置科目"

    # 获取所有损益类科目的余额
    balances = db.query(AccountBalance).join(
        Account, AccountBalance.account_id == Account.id
    ).filter(
        AccountBalance.company_id == company_id,
        AccountBalance.period == period,
        Account.code.in_(INCOME_ACCOUNT_CODES | EXPENSE_ACCOUNT_CODES),
    ).all()

    income_entries = []      # 收入类（贷方余额→借记冲零→转入本年利润贷方）
    expense_entries = []     # 费用类正常借方余额→贷记冲零→转入本年利润借方
    expense_reverse = []     # 费用类贷方余额（如利息收入冲减财务费用）→借记冲零→转入本年利润贷方

    for bal in balances:
        acct = db.query(Account).filter(Account.id == bal.account_id).first()
        if not acct:
            continue
        cb = bal.closing_balance or 0.0
        if abs(cb) < 0.001:
            continue
        if acct.code in INCOME_ACCOUNT_CODES:
            income_entries.append((acct, abs(cb)))
        elif acct.code in EXPENSE_ACCOUNT_CODES:
            if cb > 0:
                # 正常借方余额：贷记冲零
                expense_entries.append((acct, cb))
            else:
                # 贷方余额（如利息收入冲减费用）：借记冲零，视同收入结转
                expense_reverse.append((acct, abs(cb)))

    if not income_entries and not expense_entries:
        return False, "本期无损益类科目余额，无需结转"

    # 创建结转凭证（使用处理期间的最后一天）
    year, month = int(period[:4]), int(period[5:7])
    from datetime import date
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    voucher_date = date(year, month, last_day)
    voucher_no, seq = generate_voucher_no(db, company_id, "转", year, month)

    voucher = Voucher(
        company_id=company_id,
        voucher_no=voucher_no,
        date=voucher_date,
        voucher_word="转",
        serial_no=seq,
        summary=f"{period} 损益结转",
        status="pending",
        source_type="carry_forward",
        creator_id=user_id,
    )
    db.add(voucher)
    db.flush()

    sort_order = 0
    total_income = sum(v for _, v in income_entries) + sum(v for _, v in expense_reverse)
    total_expense = sum(v for _, v in expense_entries)

    # 收入类：借：收入科目 贷：本年利润
    for acct, amt in income_entries:
        sort_order += 1
        db.add(VoucherEntry(
            voucher_id=voucher.id, account_id=acct.id,
            account_code=acct.code, account_name=acct.name,
            direction="借", amount=amt,
            summary=f"结转{acct.name}", sort_order=sort_order,
        ))
    # 费用类贷方余额（反向结转）：借：费用科目 贷：本年利润（视同收入）
    for acct, amt in expense_reverse:
        sort_order += 1
        db.add(VoucherEntry(
            voucher_id=voucher.id, account_id=acct.id,
            account_code=acct.code, account_name=acct.name,
            direction="借", amount=amt,
            summary=f"结转{acct.name}(负值冲回)", sort_order=sort_order,
        ))
    sort_order += 1
    db.add(VoucherEntry(
        voucher_id=voucher.id, account_id=profit_acct.id,
        account_code=profit_acct.code, account_name=profit_acct.name,
        direction="贷", amount=total_income,
        summary="结转收入至本年利润", sort_order=sort_order,
    ))

    # 费用类：借：本年利润 贷：费用科目
    sort_order += 1
    db.add(VoucherEntry(
        voucher_id=voucher.id, account_id=profit_acct.id,
        account_code=profit_acct.code, account_name=profit_acct.name,
        direction="借", amount=total_expense,
        summary="结转费用至本年利润", sort_order=sort_order,
    ))
    for acct, amt in expense_entries:
        sort_order += 1
        db.add(VoucherEntry(
            voucher_id=voucher.id, account_id=acct.id,
            account_code=acct.code, account_name=acct.name,
            direction="贷", amount=amt,
            summary=f"结转{acct.name}", sort_order=sort_order,
        ))

    db.commit()

    # 更新结转状态
    if not cp:
        cp = ClosingPeriod(company_id=company_id, period=period, is_carried_forward=True, carry_forward_voucher_id=voucher.id)
        db.add(cp)
    else:
        cp.is_carried_forward = True
        cp.carry_forward_voucher_id = voucher.id
    db.commit()

    return True, f"结转成功，已生成结转凭证 {voucher_no}"


def reverse_carry_forward(company_id: int, user_id: int, reason: str, period: str, db: Session) -> tuple:
    """反结转：物理删除结转凭证及相关分录，恢复余额"""
    cp = db.query(ClosingPeriod).filter(
        ClosingPeriod.company_id == company_id, ClosingPeriod.period == period
    ).first()
    if not cp or not cp.is_carried_forward:
        return False, "本期未结转，无需反结转"
    if cp.is_closed:
        return False, "本期已月末结账，请先反结账后再反结转"

    # 获取结转凭证
    voucher = db.query(Voucher).filter(Voucher.id == cp.carry_forward_voucher_id).first()
    if voucher and voucher.status == "posted":
        # 反过账：恢复余额
        entries = db.query(VoucherEntry).filter(VoucherEntry.voucher_id == voucher.id).all()
        for entry in entries:
            balance = db.query(AccountBalance).filter(
                AccountBalance.company_id == company_id,
                AccountBalance.account_id == entry.account_id,
                AccountBalance.period == period,
            ).first()
            if balance:
                if entry.direction == "借":
                    balance.debit_amount -= entry.amount
                else:
                    balance.credit_amount -= entry.amount
                acct = db.query(Account).filter(Account.id == entry.account_id).first()
                if acct and acct.direction == "贷":
                    balance.closing_balance = balance.opening_balance + balance.credit_amount - balance.debit_amount
                else:
                    balance.closing_balance = balance.opening_balance + balance.debit_amount - balance.credit_amount

    # 物理删除结转凭证及分录
    if voucher:
        db.query(VoucherEntry).filter(VoucherEntry.voucher_id == voucher.id).delete()
        db.delete(voucher)

    cp.is_carried_forward = False
    cp.carry_forward_voucher_id = None
    db.commit()

    # 记录审计日志
    db.add(AuditLog(
        company_id=company_id, user_id=user_id,
        username="", action="reverse_carry_forward",
        target_type="closing", detail=f"反结转: {reason}",
    ))
    db.commit()
    return True, "反结转成功"
