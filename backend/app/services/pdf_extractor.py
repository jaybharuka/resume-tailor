import pymupdf
import pymupdf4llm

MIN_EXTRACTED_TEXT_LENGTH = 20


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract markdown-ish text from PDF bytes using pymupdf4llm."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return pymupdf4llm.to_markdown(doc)


def has_extractable_text(text: str) -> bool:
    return len(text.strip()) >= MIN_EXTRACTED_TEXT_LENGTH
