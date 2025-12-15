from __future__ import annotations
import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List
import zipfile
SUPPORTED_TEXT_SUFFIXES = {".md", ".txt", ".markdown"}
DOCX_SUFFIXES = {".docx"}
PDF_SUFFIXES = {".pdf"}
def load_text_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8").strip()
    if suffix in DOCX_SUFFIXES:
        return _extract_docx_text(path)
    if suffix in PDF_SUFFIXES:
        return _extract_pdf_text(path)
    raise ValueError(f"Unsupported document type for text extraction: {suffix}")
def _extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
    root = ET.fromstring(document_xml)
    paragraphs: List[str] = []
    for paragraph in root.iter():
        if not paragraph.tag.endswith("}p"):
            continue
        buffer: List[str] = []
        for child in paragraph.iter():
            if child.tag.endswith("}t") and child.text:
                buffer.append(child.text)
            elif child.tag.endswith("}tab"):
                buffer.append("\t")
            elif child.tag.endswith("}br"):
                buffer.append("\n")
        text = "".join(buffer).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs).strip()
def _extract_pdf_text(path: Path) -> str:
    spec = importlib.util.find_spec("pypdf")
    if spec is None:
        raise ImportError(
            "Reading PDF examples requires the optional 'pypdf' dependency. "
            "Install with `pip install pypdf` and retry."
        )
    from pypdf import PdfReader  # type: ignore
    reader = PdfReader(str(path))
    text_blocks: List[str] = []
    for page in reader.pages:
        extracted = page.extract_text() or ""
        cleaned = extracted.strip()
        if cleaned:
            text_blocks.append(cleaned)
    return "\n\n".join(text_blocks).strip()