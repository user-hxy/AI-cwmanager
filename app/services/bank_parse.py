"""银行回单解析服务 - 支持PDF文本提取与精确正则解析"""
import re
import io
from typing import Optional, List
from datetime import date
from app.models.misc import BankTemplate, KeyWordMapping


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """使用pdfplumber提取PDF文本"""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            texts = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                texts.append(text)
            return "\n".join(texts)
    except Exception:
        return ""


def clean_text(text: str) -> str:
    """去除OCR噪声(abc字母穿插)，保留有效中文内容"""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        s = line.strip()
        # 跳过纯噪声行（只有 a b c 和空格）
        if not s or re.match(r'^[\sabc]*$', s, re.IGNORECASE):
            continue
        # 移除中文字符之间的任意字母组合（ab, bc, abc, a, b, c等）
        s = re.sub(r'(?<=[\u4e00-\u9fff])\s*(?:ab?c?|bc?|[abc])\s*(?=[\u4e00-\u9fff])', '', s, flags=re.IGNORECASE)
        s = re.sub(r'(?<=[\u4e00-\u9fff])[abc](?=\s)', '', s, flags=re.IGNORECASE)
        s = re.sub(r'(?<=\s)[abc](?=[\u4e00-\u9fff])', '', s, flags=re.IGNORECASE)
        s = re.sub(r'(?<=[\d])[abc](?=[\u4e00-\u9fff])', '', s, flags=re.IGNORECASE)
        s = re.sub(r'(?<=[\u4e00-\u9fff])[abc](?=[\d])', '', s, flags=re.IGNORECASE)
        s = re.sub(r'(?<=[\d])[abc](?=[\d])', '', s, flags=re.IGNORECASE)
        # 移除中文字符和符号之间的字母
        s = re.sub(r'(?<=[\u4e00-\u9fff])[abc](?=[：:，,])', '', s, flags=re.IGNORECASE)
        s = re.sub(r'(?<=[：:])\s*ab?\s*', '', s, flags=re.IGNORECASE)
        # 清理冒号后的噪声
        s = re.sub(r'[：:]\s*ab\s*', '：', s)
        s = re.sub(r'ab\s*[：:]', '', s)
        # 清理行首/行尾的孤立字母
        s = re.sub(r'^[abc]\s+', '', s, flags=re.IGNORECASE)
        s = re.sub(r'\s+[abc]$', '', s, flags=re.IGNORECASE)
        # 合并多余空白
        s = re.sub(r'\s+', ' ', s).strip()
        # 修复符号间距
        s = re.sub(r'([：:])\s+', r'\1', s)
        s = re.sub(r'\s+([，,。.])', r'\1', s)
        if s:
            cleaned.append(s)
    return '\n'.join(cleaned)


def split_into_receipts(text: str) -> List[str]:
    """将多回单文本按"姜堰农村商业银行回单"拆分为单个回单"""
    parts = re.split(r'姜堰农村商业银行回单', text)
    receipts = []
    for p in parts:
        p = p.strip()
        # 只保留有效回单（含有网银往账或电子缴税关键字，且长度合理）
        if ("网银往账凭证" in p or "电子缴税凭证" in p) and len(p) > 50:
            receipts.append(p)
    return receipts


def _normalize_text(text: str) -> str:
    """归一化文本：去除中文之间的空格和字母噪声"""
    # 去除中文字符之间的所有空格
    t = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', text)
    # 去除中文字符之间的字母组合
    t = re.sub(r'(?<=[\u4e00-\u9fff])\s*(?:ab?c?|bc?|[abc])\s*(?=[\u4e00-\u9fff])', '', t, flags=re.IGNORECASE)
    return t


def _clean_name(name: str) -> str:
    """清理名称尾部噪声"""
    name = re.sub(r'\s*[abc]+\s*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'(收款人|流水号|账号|行号|行名).*', '', name).strip()
    name = re.sub(r'\s+', '', name)
    return name


def _resolve_payer_name(text: str) -> str:
    """从文本中提取付款人户名（多维度匹配）"""
    t = _normalize_text(text)
    # 先尝试"付款人户名:"或"付款人全称:"
    m = re.search(r'付\s*款\s*人\s*(?:户\s*名|全\s*称)\s*[：:]\s*([^\s,，0-9]{2,40})', t)
    if m:
        return _clean_name(m.group(1))
    # 降级: "纳税人全称:"后跟税号前的内容
    m = re.search(r'纳税人(?:全称|识别号)[：:]*\s*([\u4e00-\u9fffA-Za-z]{2,40})', t)
    if m:
        return _clean_name(m.group(1))
    return ""


def _resolve_remark(text: str) -> str:
    """从文本中提取用途/备注信息"""
    t = _normalize_text(text)
    # 修复"备注："前后的噪声
    t = re.sub(r'备\s*注\s*[abc]?\s*[：:]', '备注：', t, flags=re.IGNORECASE)
    t = re.sub(r'用\s*途\s*[：:]', '用途：', t)

    remark = ""
    m = re.search(r'用途[：:]\s*([^\n]*)', t)
    if m:
        r = m.group(1).strip()
        r = re.sub(r'^[abc\s]+', '', r)
        r = re.sub(r'[abc\s]+$', '', r)
        r = re.sub(r'备注[：:].*', '', r)
        r = re.sub(r'打印次数.*', '', r)
        remark = r.strip()

    m = re.search(r'备注[：:]\s*([^\n]*?)(?:\s*打印次数|$)', t)
    if m:
        r2 = m.group(1).strip()
        r2 = re.sub(r'^[abc\s]+', '', r2)
        r2 = re.sub(r'[abc\s]+$', '', r2)
        r2 = r2.strip()
        if r2 and r2 not in remark:
            remark = remark + " " + r2 if remark else r2

    # 清理残余噪声
    remark = re.sub(r'[abc\s]+', ' ', remark).strip()
    # 清理车牌号中的噪声
    remark = re.sub(r'([\u4e00-\u9fff][A-Z])\s*[a-z0-9]\s*([a-z0-9])\s*(\d)', r'\1\2\3', remark)
    return remark


def parse_jiangyan_online_banking(text: str) -> dict:
    """解析姜堰农商行-网银往账凭证"""
    result = {
        "payer_name": "", "payee_name": "", "amount": 0.0,
        "transaction_date": "", "remark": "", "fee": 0.0,
        "sub_type": "online_banking", "confidence": "中",
    }

    # 交易日期: 20260104 → 2026-01-04
    m = re.search(r'交易日期[：:]\s*(\d{4})(\d{2})(\d{2})', text)
    if m:
        result["transaction_date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # 付款人（多维度）
    result["payer_name"] = _resolve_payer_name(text)

    # 收款人户名:xxx
    m = re.search(r'收\s*款\s*人\s*户\s*名[：:]\s*([^\s,，0-9]{2,40})', text)
    if m:
        result["payee_name"] = _clean_name(m.group(1))

    # 交易金额(小写): ￥105.61
    m = re.search(r'交易金额[（(]小写[）)]*[：:]*\s*￥?\s*([\d,]+\.\d{2})', text)
    if m:
        result["amount"] = float(m.group(1).replace(",", ""))

    # 用途和备注
    result["remark"] = _resolve_remark(text)

    # 置信度
    if result["amount"] > 0 and result["payer_name"]:
        result["confidence"] = "高"
    elif result["amount"] > 0:
        result["confidence"] = "中"
    else:
        result["confidence"] = "低"

    return result


def parse_jiangyan_tax_payment(text: str) -> dict:
    """解析姜堰农商行-电子缴税凭证"""
    result = {
        "payer_name": "", "payee_name": "税务局",
        "amount": 0.0, "transaction_date": "", "remark": "",
        "fee": 0.0, "sub_type": "tax_payment", "confidence": "高",
    }

    # 交易日期: 20260104
    m = re.search(r'交易日期[：:]\s*(\d{4})(\d{2})(\d{2})', text)
    if m:
        result["transaction_date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # 纳税人全称:xxx
    m = re.search(r'纳税人全称[和纳税人识别号]*[：:]\s*([^\s]+)', text)
    if m:
        result["payer_name"] = m.group(1).strip()

    # 合计金额(小写):￥20.09
    m = re.search(r'合计金额[（(]小写[）)]*[：:]*\s*￥?\s*([\d,]+\.\d{2})', text)
    if m:
        result["amount"] = float(m.group(1).replace(",", ""))

    # 税种名称（在"交税（费）种名称"后面的行）
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if '种名称' in line or '税' in line:
            # 寻找金额
            am = re.search(r'([\d,]+\.\d{2})', line)
            if am:
                result["amount"] = float(am.group(1).replace(",", ""))
            # 寻找税种名
            nm = re.search(r'([\u4e00-\u9fff]{2,8}税)', line)
            if nm:
                result["remark"] = f"缴税-{nm.group(1)}"
                break

    if not result["remark"]:
        result["remark"] = "缴税"

    if result["amount"] <= 0:
        result["confidence"] = "低"

    return result


def parse_jiangyan_receipt(text: str) -> dict:
    """解析姜堰农商行回单 - 自动识别类型"""
    text_clean = clean_text(text)

    if "电子缴税凭证" in text_clean:
        return parse_jiangyan_tax_payment(text_clean)
    elif "网银往账凭证" in text_clean:
        return parse_jiangyan_online_banking(text_clean)
    else:
        result = parse_jiangyan_online_banking(text_clean)
        result["sub_type"] = "unknown"
        result["confidence"] = "低"
        return result


def parse_zheshang_receipt(text: str) -> dict:
    """解析浙商银行回单"""
    text_clean = clean_text(text)
    result = {
        "payer_name": "", "payee_name": "", "amount": 0.0,
        "transaction_date": "", "remark": "", "fee": 0.0,
        "confidence": "高",
    }
    m = re.search(r'付款人[户名]*[：:]\s*([^\s]+)', text_clean)
    if m:
        result["payer_name"] = m.group(1).strip()
    m = re.search(r'收款人[户名]*[：:]\s*([^\s]+)', text_clean)
    if m:
        result["payee_name"] = m.group(1).strip()
    m = re.search(r'金额[（(]小写[）)]*[：:]*\s*([\d,]+\.?\d*)', text_clean)
    if m:
        result["amount"] = float(m.group(1).replace(",", ""))
    elif re.search(r'交易金额[：:]*\s*([\d,]+\.?\d*)', text_clean):
        m = re.search(r'交易金额[：:]*\s*([\d,]+\.?\d*)', text_clean)
        result["amount"] = float(m.group(1).replace(",", ""))
    m = re.search(r'交易日期[：:]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})', text_clean)
    if m:
        result["transaction_date"] = m.group(1).replace("/", "-")
    m = re.search(r'附言[：:]\s*(.+)', text_clean)
    if m:
        result["remark"] = m.group(1).strip()
    m = re.search(r'手续费[：:]\s*([\d,]+\.?\d*)', text_clean)
    if m:
        result["fee"] = float(m.group(1).replace(",", ""))

    if not result["amount"]:
        result["confidence"] = "低"
    elif not result["payer_name"] or not result["payee_name"]:
        result["confidence"] = "中"
    return result


def match_keyword_to_account(keyword: str, mappings: list) -> Optional[dict]:
    """根据关键词匹配科目"""
    for m in mappings:
        if m.keyword in keyword:
            return {"account_code": m.account_code, "account_name": m.account_name, "direction": m.direction}
    return None


def auto_detect_bank(text: str) -> str:
    """自动检测银行名称"""
    if "姜堰" in text or "农商行" in text or "农村商业银行" in text:
        return "jiangyan"
    elif "浙商" in text:
        return "zheshang"
    return "unknown"


def parse_receipt_text(text: str, template: BankTemplate = None) -> dict:
    """通用回单解析入口（单条文本）"""
    bank_name = template.bank_name if template else ""
    detected = auto_detect_bank(text)
    if detected == "jiangyan" or "姜堰" in bank_name or "农商" in bank_name:
        return parse_jiangyan_receipt(text)
    elif "浙商" in text or "浙商" in bank_name:
        return parse_zheshang_receipt(text)
    else:
        return parse_zheshang_receipt(text)


def parse_receipt_pdf(file_bytes: bytes) -> List[dict]:
    """解析PDF回单文件，返回多个回单结果列表"""
    raw_text = extract_text_from_pdf(file_bytes)
    if not raw_text.strip():
        return [{"payer_name": "", "payee_name": "", "amount": 0.0,
                 "transaction_date": "", "remark": "", "fee": 0.0,
                 "confidence": "低", "error": "无法提取PDF文本"}]

    bank_type = auto_detect_bank(raw_text)
    if bank_type == "jiangyan":
        # 清理全文噪声用于分割
        clean_full = clean_text(raw_text)
        receipts_text = split_into_receipts(clean_full)
        results = []
        for rt in receipts_text:
            if "网银往账凭证" in rt or "电子缴税凭证" in rt:
                parsed = parse_jiangyan_receipt(rt)
                if parsed["amount"] > 0:
                    results.append(parsed)
        if not results:
            results.append(parse_jiangyan_receipt(raw_text))
        return results
    else:
        return [parse_receipt_text(raw_text)]
