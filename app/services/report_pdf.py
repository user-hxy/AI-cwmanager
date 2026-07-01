"""报表PDF生成服务"""
import warnings
warnings.filterwarnings("ignore", message=".*MERG.*subset.*")
from io import BytesIO
from datetime import date
from sqlalchemy.orm import Session
from fpdf import FPDF
import os

_CHINESE_FONTS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fonts", "simsun.ttc"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fonts", "msyh.ttc"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "fonts", "NotoSansSC-Regular.otf"),
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/simsun.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


def _find_font():
    for fp in _CHINESE_FONTS:
        if os.path.exists(fp):
            return fp
    return None


class ReportPDF(FPDF):
    def __init__(self, orientation="P"):
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self.orientation = orientation
        self.page_w = 297 if orientation == "L" else 210
        self.page_h = 210 if orientation == "L" else 297
        self.margin_lr = 10
        fp = _find_font()
        if fp:
            self.add_font("cn", "", fp, uni=True)
            self.add_font("cn", "B", fp, uni=True)
            self.has_cn = True
        else:
            self.has_cn = False

    def _t(self, text):
        if self.has_cn:
            return str(text)
        return str(text).encode("latin-1", errors="replace").decode("latin-1")

    def header(self):
        pass

    def footer(self):
        self.set_y(-12)
        self.set_font("cn", "", 7)
        self.cell(0, 8, self._t(f"- {self.page_no()} -"), align="C")


def export_balance_sheet_pdf(data: dict, orientation="P") -> BytesIO:
    """资产负债表PDF（使用标准格式 left_items/right_items）"""
    pdf = ReportPDF(orientation=orientation)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    table_w = 241  # 总表格宽度 mm
    page_w = pdf.page_w
    margin_l = (page_w - table_w) / 2  # 水平居中起始X
    if margin_l < 8:
        margin_l = 8

    col_w = [52, 10, 28, 28, 5, 52, 10, 28, 28]

    # 标题
    pdf.set_font("cn", "B", 16)
    pdf.cell(0, 10, pdf._t("资产负债表"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("cn", "", 9)
    period_txt = data.get("period_display", data.get("period", ""))
    pdf.cell(0, 6, pdf._t(f"编制单位：{data.get('company', '')}　　　{period_txt}　　　单位：元"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # 从新格式取数据
    left_items = data.get("left_items", [])
    right_items = data.get("right_items", [])

    # 表头
    pdf.set_font("cn", "B", 7.5)
    headers = ["资产", "行次", "期末余额", "期初余额", "", "负债和所有者权益", "行次", "期末余额", "期初余额"]
    cx = margin_l
    y_start = pdf.get_y()
    for i, h in enumerate(headers):
        pdf.set_xy(cx, y_start)
        pdf.cell(col_w[i], 6, pdf._t(h), border=1, align="C")
        cx += col_w[i]
    pdf.set_y(y_start + 6)

    # 数据行（左右同时渲染）
    max_rows = max(len(left_items), len(right_items))
    pdf.set_font("cn", "", 6.5)

    def _get_cell(li, key, default=""):
        if li:
            v = li.get(key, default)
            return v if v != "" else default
        return default

    for i in range(max_rows):
        y = pdf.get_y()
        if y > 260:
            pdf.add_page()
            y = pdf.get_y()

        li = left_items[i] if i < len(left_items) else None
        ri = right_items[i] if i < len(right_items) else None

        l_name = li["name"] if li else ""
        l_line = str(li.get("line_no", "")) if li and not li.get("is_header") else ""
        l_closing = f"{li['closing']:.2f}" if li and isinstance(li.get("closing"), (int, float)) else ""
        l_ys = f"{li['year_start']:.2f}" if li and isinstance(li.get("year_start"), (int, float)) else ""
        r_name = ri["name"] if ri else ""
        r_line = str(ri.get("line_no", "")) if ri and not ri.get("is_header") else ""
        r_closing = f"{ri['closing']:.2f}" if ri and isinstance(ri.get("closing"), (int, float)) else ""
        r_ys = f"{ri['year_start']:.2f}" if ri and isinstance(ri.get("year_start"), (int, float)) else ""

        # 左列
        cx = margin_l
        for vi, v in enumerate([l_name, l_line, l_closing, l_ys]):
            pdf.set_xy(cx, y)
            pdf.cell(col_w[vi], 5, pdf._t(str(v)), border=1, align="C")
            cx += col_w[vi]

        cx += col_w[4]  # 跳过间隔

        # 右列
        for vi, v in enumerate([r_name, r_line, r_closing, r_ys]):
            pdf.set_xy(cx, y)
            pdf.cell(col_w[vi + 5], 5, pdf._t(str(v)), border=1, align="C")
            cx += col_w[vi + 5]

        pdf.set_y(y + 5)

    # 合计行
    y = pdf.get_y()
    pdf.set_font("cn", "B", 7.5)
    cx = margin_l
    vals_l = ["资产总计", "", f"{data.get('total_assets', 0):.2f}", f"{data.get('total_assets_year_start', 0):.2f}"]
    for vi, v in enumerate(vals_l):
        pdf.set_xy(cx, y)
        pdf.cell(col_w[vi], 5, pdf._t(str(v)), border=1, align="C")
        cx += col_w[vi]
    cx += col_w[4]
    vals_r = ["负债和所有者权益总计", "", f"{data.get('total_liabilities_equity', 0):.2f}", f"{data.get('total_le_year_start', 0):.2f}"]
    for vi, v in enumerate(vals_r):
        pdf.set_xy(cx, y)
        pdf.cell(col_w[vi + 5], 5, pdf._t(str(v)), border=1, align="C")
        cx += col_w[vi + 5]

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


def export_income_statement_pdf(data: dict, orientation="P") -> BytesIO:
    """利润表PDF（使用标准格式 items，含本月数和本年累计数）"""
    pdf = ReportPDF(orientation=orientation)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # 标题居中
    pdf.set_font("cn", "B", 14)
    pdf.cell(0, 8, pdf._t(data.get("title", "利润表")), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("cn", "", 8)
    pdf.cell(0, 5, pdf._t(f"{data.get('company', '')} · {data.get('period', '')}"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    items = data.get("items", [])
    col_w = [76, 10, 24, 24]
    table_w = sum(col_w)
    page_w = pdf.page_w
    ml = (page_w - table_w) / 2
    if ml < 8: ml = 8

    # 表头
    pdf.set_font("cn", "B", 7.5)
    cx = ml
    for i, h in enumerate(["项目", "行次", "本月数", "本年累计数"]):
        pdf.set_xy(cx, pdf.get_y())
        pdf.cell(col_w[i], 6, pdf._t(h), border=1, align="C")
        cx += col_w[i]
    pdf.ln(6)

    # 数据行
    pdf.set_font("cn", "", 7)
    for item in items:
        y = pdf.get_y()
        if y > 260:
            pdf.add_page()
            y = pdf.get_y()
        is_bold = item.get("is_total", False) or (item.get("name", "").startswith(("一、","二、","三、","四、","五、")))
        if is_bold:
            pdf.set_font("cn", "B", 7)
        name = item.get("name", "")
        line_no = str(item.get("line_no", ""))
        amt = item.get("amount", 0)
        cum = item.get("cumulative", 0)

        cx = ml
        for vi, v in enumerate([name, line_no, f"{amt:.2f}" if amt else "", f"{cum:.2f}" if cum else ""]):
            pdf.set_xy(cx, y)
            pdf.cell(col_w[vi], 5, pdf._t(str(v)), border=1, align="C")
            cx += col_w[vi]
        pdf.set_y(y + 5)

        if is_bold:
            pdf.set_font("cn", "", 7)

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf


def export_trial_balance_pdf(data: list, company: str, period: str, orientation="L", period_display="") -> BytesIO:
    """科目汇总表PDF"""
    pdf = ReportPDF(orientation=orientation)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("cn", "B", 16)
    pdf.cell(0, 10, pdf._t("科目汇总表"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("cn", "", 9)
    period_txt = period_display if period_display else period
    pdf.cell(0, 6, pdf._t(f"编制单位：{company}　　　{period_txt}　　　单位：元"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    col_w = [16, 28, 10, 28, 28, 28, 28]
    table_w = sum(col_w)
    ml = (pdf.page_w - table_w) / 2
    if ml < 8: ml = 8

    pdf.set_font("cn", "B", 7)
    headers = ["科目编码", "科目名称", "类别", "期初余额", "本期借方", "本期贷方", "期末余额"]
    pdf.set_x(ml)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 6, pdf._t(h), border=1, align="C")
    pdf.ln(6)

    pdf.set_font("cn", "", 6.5)
    for item in data:
        y = pdf.get_y()
        if y > 260:
            pdf.add_page()
            y = pdf.get_y()
        vals = [
            item.get("account_code", ""),
            item.get("account_name", ""),
            item.get("category", ""),
            f"{item.get('opening_balance', 0):.2f}",
            f"{item.get('debit_amount', 0):.2f}",
            f"{item.get('credit_amount', 0):.2f}",
            f"{item.get('closing_balance', 0):.2f}",
        ]
        pdf.set_x(ml)
        for i, v in enumerate(vals):
            pdf.cell(col_w[i], 5, pdf._t(str(v)), border=1, align="C")
        pdf.ln(5)

    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf
