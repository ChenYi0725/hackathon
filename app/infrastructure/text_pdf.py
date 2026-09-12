"""Explicit text-only reader for regression fixtures and reference documents."""
import io
from pypdf import PdfReader

def read_pdf(data: bytes):
    if not data.startswith(b'%PDF-'):
        raise ValueError('檔案不是有效的 PDF。')
    reader=PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError('請先解除 PDF 密碼保護。')
    if not 1<=len(reader.pages)<=200:
        raise ValueError('PDF 須為 1–200 頁。')
    pages=[]
    for i,page in enumerate(reader.pages):
        if len(page.get_contents().get_data() if page.get_contents() else b'') > 15_000_000:
            raise ValueError('單頁內容過大，請拆分或最佳化 PDF。')
        text=page.extract_text(extraction_mode='layout') or ''
        pages.append(dict(page=i+1,text=text[:100000]))
    return pages
