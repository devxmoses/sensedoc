"""Find text and where it sits on the page.

Digital PDFs already know where every word is (PyMuPDF). Photos and scans don't, so we run OCR:
RapidOCR uses small ONNX models (the same kind as PaddleOCR), runs on the CPU and installs with pip,
no system packages or GPU needed.
"""

import io
import logging
import threading
from dataclasses import dataclass

import numpy as np
from PIL import Image as PILImage

_engine = None
_lock = threading.RLock()  # one OCR engine, used by one background thread at a time


@dataclass
class Line:
    text: str
    page: int  # 1-based
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions of the page size (0-1)
    confidence: float  # 1.0 for digital text; the OCR score for photos and scans
    from_ocr: bool = False


def engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr import RapidOCR  # imported lazily: loading the models takes a moment

            _engine = RapidOCR()
            logging.getLogger("RapidOCR").setLevel(logging.WARNING)  # it logs every model load at INFO
        return _engine


def ocr_image(data: bytes, page: int) -> list[Line]:
    image = PILImage.open(io.BytesIO(data)).convert("RGB")
    width, height = image.size
    with _lock:
        result = engine()(np.array(image))
    if result.boxes is None:
        return []
    lines = []
    for box, text, score in zip(result.boxes, result.txts, result.scores):
        xs, ys = box[:, 0], box[:, 1]  # four corners of a possibly tilted box
        bbox = (float(xs.min() / width), float(ys.min() / height), float(xs.max() / width), float(ys.max() / height))
        lines.append(Line(text, page, bbox, round(float(score), 3), from_ocr=True))
    return lines


def pdf_page_lines(page, number: int) -> list[Line]:
    """Line positions of a digital PDF page, straight from the file."""
    width, height = page.rect.width, page.rect.height
    grouped: dict[tuple[int, int], list] = {}
    for x0, y0, x1, y1, word, block, line, _ in page.get_text("words"):
        grouped.setdefault((block, line), []).append((x0, y0, x1, y1, word))
    lines = []
    for words in grouped.values():
        bbox = (
            min(w[0] for w in words) / width,
            min(w[1] for w in words) / height,
            max(w[2] for w in words) / width,
            max(w[3] for w in words) / height,
        )
        lines.append(Line(" ".join(w[4] for w in words), number, bbox, 1.0))
    return lines
