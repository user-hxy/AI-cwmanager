"""发票解析服务 - 支持XML/OFD/PDF/JPG/PNG"""
import re
import json
import zipfile
import io
import xml.etree.ElementTree as ET
from typing import Optional, List
from PIL import Image
from app.models.misc import InvoiceTemplate


def parse_xml_invoice(file_bytes: bytes) -> dict:
    """解析XML格式的数电发票"""
    result = {
        "invoice_type": "",
        "invoice_no": "",
        "issue_date": "",
        "buyer_name": "",
        "buyer_tax_id": "",
        "seller_name": "",
        "seller_tax_id": "",
        "total_amount": 0.0,
        "total_tax": 0.0,
        "total_price": 0.0,
        "detail_items": [],
        "confidence": "高",
    }
    try:
        root = ET.fromstring(file_bytes)
        # 尝试多种命名空间
        ns = {"ns": "http://www.chinatax.gov.cn/dataspec/"}

        def find_text(path):
            for tag_prefix in ["ns:", ""]:
                full_path = f".//{tag_prefix}{path}"
                elem = root.find(full_path, ns) if tag_prefix else root.find(full_path)
                if elem is not None and elem.text:
                    return elem.text.strip()
            return ""

        result["invoice_no"] = find_text("InvoiceNo") or find_text("FPQQLSH") or find_text("发票号码")
        result["issue_date"] = find_text("IssueDate") or find_text("KPRQ")
        result["buyer_name"] = find_text("BuyerName") or find_text("GMFMC")
        result["buyer_tax_id"] = find_text("BuyerTaxId") or find_text("GMSBH")
        result["seller_name"] = find_text("SellerName") or find_text("XSFMC")
        result["seller_tax_id"] = find_text("SellerTaxId") or find_text("XSSBH")

        # 金额/税额/价税合计
        amt = find_text("TotalAmount") or find_text("JSHJ")
        tax = find_text("TotalTax") or find_text("SPSE")
        price = find_text("TotalPrice") or find_text("JSHJ")

        if amt:
            result["total_amount"] = float(amt)
        if tax:
            result["total_tax"] = float(tax)
        if price:
            result["total_price"] = float(price)

        # 项目明细
        items = root.findall(".//Item") or root.findall(".//DetailItem") or root.findall(".//SPHX")
        for item in items:
            item_name = item.findtext("ItemName") or item.findtext("XMMC") or ""
            item_amount = item.findtext("ItemAmount") or item.findtext("JE") or "0"
            item_tax = item.findtext("ItemTax") or item.findtext("SL") or "0"
            result["detail_items"].append({
                "name": item_name.strip(),
                "amount": float(item_amount),
                "tax_rate": item_tax,
            })

    except Exception:
        result["confidence"] = "低"

    return result


def parse_ofd_invoice(file_bytes: bytes) -> dict:
    """解析OFD格式发票（OFD是ZIP压缩包）"""
    result = {
        "invoice_type": "OFD",
        "invoice_no": "",
        "issue_date": "",
        "buyer_name": "",
        "buyer_tax_id": "",
        "seller_name": "",
        "seller_tax_id": "",
        "total_amount": 0.0,
        "total_tax": 0.0,
        "total_price": 0.0,
        "detail_items": [],
        "confidence": "高",
    }
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            # 查找XML文件
            xml_files = [f for f in zf.namelist() if f.endswith(".xml")]
            for xml_file in xml_files:
                xml_bytes = zf.read(xml_file)
                try:
                    parsed = parse_xml_invoice(xml_bytes)
                    if parsed.get("invoice_no"):
                        return parsed
                except Exception:
                    continue
        result["confidence"] = "低"
    except zipfile.BadZipFile:
        result["confidence"] = "低"
    return result


def parse_image_invoice(file_bytes: bytes) -> dict:
    """图片型发票占位解析 - 返回模拟结果（实际项目中集成PaddleOCR）"""
    # 实际会调用PaddleOCR进行OCR识别
    # 这里提供基础占位，返回低置信度提示人工处理
    return {
        "invoice_type": "图片发票",
        "invoice_no": "",
        "issue_date": "",
        "buyer_name": "",
        "buyer_tax_id": "",
        "seller_name": "",
        "seller_tax_id": "",
        "total_amount": 0.0,
        "total_tax": 0.0,
        "total_price": 0.0,
        "detail_items": [],
        "confidence": "低",
        "message": "图片型发票请使用OCR引擎(如PaddleOCR)进行识别，当前版本需要人工录入",
    }


def parse_invoice_file(filename: str, file_bytes: bytes) -> dict:
    """发票解析入口，根据文件扩展名自动选择解析方式"""
    ext = filename.lower().split(".")[-1] if "." in filename else ""

    if ext == "xml":
        return parse_xml_invoice(file_bytes)
    elif ext == "ofd":
        return parse_ofd_invoice(file_bytes)
    elif ext == "pdf":
        # PDF需要尝试pdfplumber提取文本
        # 这里返回模拟结果，实际项目集成pdfplumber
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                text = ""
                for page in pdf.pages:
                    text += page.extract_text() or ""
            if text.strip():
                result = {
                    "invoice_type": "PDF发票",
                    "invoice_no": "",
                    "issue_date": "",
                    "buyer_name": "",
                    "buyer_tax_id": "",
                    "seller_name": "",
                    "seller_tax_id": "",
                    "total_amount": 0.0,
                    "total_tax": 0.0,
                    "total_price": 0.0,
                    "detail_items": [],
                    "confidence": "中",
                }
                # 尝试正则提取关键字段
                m = re.search(r"发票号码[：:]\s*(\d{8,20})", text)
                if m:
                    result["invoice_no"] = m.group(1)
                m = re.search(r"开票日期[：:]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})", text)
                if m:
                    result["issue_date"] = m.group(1).replace("年", "-").replace("月", "-").replace("日", "")
                m = re.search(r"价税合计[（(]小写[）)]*[：:]\s*([\d,]+\.?\d*)", text)
                if m:
                    result["total_price"] = float(m.group(1).replace(",", ""))
                if result["invoice_no"] and result["total_price"]:
                    result["confidence"] = "高"
                return result
        except ImportError:
            pass
        return {
            "invoice_type": "PDF发票",
            "invoice_no": "",
            "issue_date": "",
            "confidence": "低",
            "message": "PDF解析需要安装pdfplumber库",
        }
    elif ext in ("jpg", "jpeg", "png", "bmp", "tiff", "tif"):
        return parse_image_invoice(file_bytes)
    else:
        # 尝试作为文本解析
        try:
            text = file_bytes.decode("utf-8")
            if "发票" in text or "Invoice" in text:
                return parse_xml_invoice(file_bytes)
        except Exception:
            pass
        return {
            "invoice_type": "未知",
            "invoice_no": "",
            "confidence": "低",
            "message": f"不支持的文件格式: {ext}",
        }
