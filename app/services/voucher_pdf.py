"""凭证PDF生成服务"""
from io import BytesIO
from datetime import date
from sqlalchemy.orm import Session
from fpdf import FPDF
from app.models import Voucher, VoucherEntry, Account, Company, User

# 检查可用的中文字体
import os

_CHINESE_FONTS = [
    "C:/Windows/Fonts/simsun.ttc",    # 宋体
    "C:/Windows/Fonts/simsun.ttf",
    "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/simhei.ttf",     # 黑体
    "/System/Library/Fonts/PingFang.ttc",  # macOS
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",  # Linux
]


def _find_chinese_font():
    for fp in _CHINESE_FONTS:
        if os.path.exists(fp):
            return fp
    return None


class VoucherPDF(FPDF):
    def __init__(self, orientation="L"):
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self.font_path = _find_chinese_font()
        if self.font_path:
            self.add_font("custom", "", self.font_path, uni=True)
            self.add_font("custom", "B", self.font_path, uni=True)
            self.has_cn = True
        else:
            self.has_cn = False

    def _t(self, text):
        """处理文本，避免编码问题"""
        if self.has_cn:
            return text
        try:
            return text.encode("latin-1", errors="replace").decode("latin-1")
        except:
            return ""

    def _fmt_amt(self, amount):
        """金额格式：1,234.56"""
        return f"{amount:,.2f}"

    def draw_voucher(self, voucher: Voucher, entries: list,
                     company_name: str, creator_name: str, x: float, y: float,
                     reviewer_name="", poster_name="", height=76, page_label=""):
        """在指定位置绘制一个凭证（参照2026.3-2026.5.pdf格式）"""
        w = 135  # 凭证宽度
        h = height
        margin_l = 1

        # 公司名称
        self.set_xy(x, y + 0.5)
        self.set_font("custom", "B", 9)
        self.cell(w, 5, self._t(company_name), align="C")

        # 标题行
        self.set_xy(x, y + 5)
        self.set_font("custom", "B", 9)
        self.cell(w, 5, self._t("记 账 凭 证"), align="C")

        # 日期（左侧）+ 凭证号（右侧）
        d = voucher.date
        date_str = f"{d.year}年{d.month}月{d.day}日"
        vno = voucher.voucher_no or ""
        # 直接使用系统凭证号格式
        if page_label:
            vno_display = f"{vno}（{page_label}）"
        else:
            vno_display = vno

        self.set_font("custom", "", 7)
        self.set_xy(x + margin_l, y + 10)
        self.cell(55, 4, self._t(date_str))
        self.cell(70, 4, self._t(vno_display), align="R")

        # 四列表头：摘要 | 会计科目 | 借方金额 | 贷方金额
        col_w = [5, 45, 30, 28, 27]  # 序号、摘要、会计科目、借方金额、贷方金额
        header_y = y + 14.5
        self.set_draw_color(80, 80, 80)
        self.set_line_width(0.3)
        self.set_font("custom", "B", 6.5)
        headers = ["", "摘要", "会计科目", "借方金额", "贷方金额"]
        th = 5
        cx = x
        for i, h_text in enumerate(headers):
            self.set_xy(cx, header_y)
            self.cell(col_w[i], th, self._t(h_text), border=1, align="C")
            cx += col_w[i]

        # 分录行
        row_h = 5.5
        self.set_font("custom", "", 6.5)
        total_debit = 0
        total_credit = 0
        render_rows = len(entries) if entries else 1
        for row_i in range(render_rows):
            ry = header_y + th + row_i * row_h
            e = entries[row_i] if row_i < len(entries) else None
            if e:
                vals = [
                    str(row_i + 1),
                    e.summary or voucher.summary or "",
                    f"{e.account_code or ''} {e.account_name or ''}",
                    f"{self._fmt_amt(e.amount)}" if e.direction == "借" else "",
                    f"{self._fmt_amt(e.amount)}" if e.direction == "贷" else "",
                ]
                if e.direction == "借":
                    total_debit += e.amount
                else:
                    total_credit += e.amount
            else:
                vals = ["", "", "", "", ""]

            cx = x
            for ci in range(5):
                self.set_xy(cx, ry)
                align = "C" if ci in (0, 3, 4) else "L"
                self.cell(col_w[ci], row_h, self._t(str(vals[ci])), border=1, align=align)
                cx += col_w[ci]

        # 附单据 + 合计行
        sum_y = header_y + th + render_rows * row_h
        att_cnt = getattr(voucher, 'attachment_count', 0) or 0
        self.set_font("custom", "", 6)
        self.set_xy(x, sum_y)
        self.cell(col_w[0] + col_w[1], row_h, self._t(f"附单据 {att_cnt} 张"), border=0, align="L")
        cx = x + col_w[0] + col_w[1]
        self.set_font("custom", "B", 6.5)
        for ci in range(2, 5):
            self.set_xy(cx, sum_y)
            if ci == 2:
                self.cell(col_w[ci], row_h, self._t("合  计"), border=1, align="C")
            elif ci == 3:
                self.cell(col_w[ci], row_h, self._t(f"{self._fmt_amt(total_debit)}"), border=1, align="C")
            elif ci == 4:
                self.cell(col_w[ci], row_h, self._t(f"{self._fmt_amt(total_credit)}"), border=1, align="C")
            cx += col_w[ci]

        # 底部人员信息
        foot_y = sum_y + row_h + 1
        self.set_font("custom", "", 5.5)
        self.set_xy(x + margin_l, foot_y)
        self.cell(18, 3, self._t("会计主管："))
        self.cell(22, 3, self._t("复核：" + (reviewer_name or "")))
        self.cell(22, 3, self._t("记账：" + (creator_name or "")))
        self.cell(18, 3, self._t("出纳："))
        self.cell(18, 3, self._t("经办："))
        self.cell(28, 3, self._t("制单：" + (creator_name or "")))


def generate_voucher_pdf(company_id: int, period: str, db: Session,
                         orientation="L", per_page=2) -> BytesIO:
    """生成凭证PDF"""
    company = db.query(Company).filter(Company.id == company_id).first()
    company_name = company.name if company else ""

    # 查询凭证
    all_vouchers = db.query(Voucher).filter(
        Voucher.company_id == company_id,
        Voucher.date >= date(int(period[:4]), int(period[5:7]), 1),
        Voucher.date <= date(int(period[:4]), int(period[5:7]), 28),
    ).order_by(
        Voucher.source_type != "carry_forward",
        Voucher.date,
        Voucher.id,
    ).all()

    vouchers = [v for v in all_vouchers if v.date.strftime("%Y-%m") == period]

    pdf = VoucherPDF(orientation=orientation)
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    page_w = 297 if orientation == "L" else 210
    page_h = 210 if orientation == "L" else 297
    VOUCHER_WIDTH = 135

    for idx, v in enumerate(vouchers):
        page_idx = idx // per_page
        pos_on_page = idx % per_page

        # 每页第一个凭证时计算布局
        if pos_on_page == 0:
            if page_idx > 0:
                pdf.add_page()
            page_h_avail = page_h - 8
            slot_h = page_h_avail / per_page
        # 凭证高度自适应填满插槽（留3mm间隙）
        vh = slot_h - 3
        if vh > 95:
            vh = 95

        # 垂直居中：每个凭证在其分配的垂直区域内居中
        y_pos = 4 + pos_on_page * slot_h + (slot_h - vh) / 2
        # 水平居中（基于凭证实际宽度135mm）
        x_pos = (page_w - VOUCHER_WIDTH) / 2

        entries = db.query(VoucherEntry).filter(
            VoucherEntry.voucher_id == v.id
        ).order_by(VoucherEntry.sort_order).all()

        creator = db.query(User).filter(User.id == v.creator_id).first()
        creator_name = creator.display_name if creator else ""
        reviewer = db.query(User).filter(User.id == v.reviewer_id).first()
        reviewer_name = reviewer.display_name if reviewer else ""
        poster = db.query(User).filter(User.id == v.poster_id).first()
        poster_name = poster.display_name if poster else ""

        pdf.draw_voucher(v, entries, company_name, creator_name, x_pos, y_pos,
                         reviewer_name=reviewer_name, poster_name=poster_name,
                         height=vh, page_label="1/1")

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf
