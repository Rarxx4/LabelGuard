"""OCR for raster artwork (and PDFs whose text was converted to outlines).

RapidOCR runs PaddleOCR models on ONNX Runtime: pip-installable, no system
binaries. It gives line-level text with boxes and confidences, which is an
independent "second reader" for the AI's transcription.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from PIL import Image


@lru_cache(maxsize=1)
def _engine():
    try:  # rapidocr >= 3 (works on all current Python versions)
        import logging
        from rapidocr import RapidOCR
        engine = RapidOCR()
        logging.getLogger("RapidOCR").setLevel(logging.WARNING)  # silence model-loading info lines
        return "v3", engine
    except ImportError:  # older package name, Python <= 3.12
        from rapidocr_onnxruntime import RapidOCR
        return "v1", RapidOCR()


def _run(arr) -> list[tuple]:
    """(box, text, score) per detected line, whichever RapidOCR version is installed."""
    version, engine = _engine()
    if version == "v3":
        out = engine(arr)
        if out.boxes is None:
            return []
        return list(zip(out.boxes, out.txts, out.scores))
    result, _ = engine(arr)
    return result or []


def ocr_image(img: Image.Image) -> list[dict]:
    """Returns [{text, bbox (normalised x0,y0,x1,y1), confidence, height_px}]."""
    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]
    lines = []
    for box, text, score in _run(arr):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        if not text.strip():
            continue
        lines.append({
            "text": text.strip(),
            "bbox": (min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h),
            "confidence": float(score),
            "height_px": max(ys) - min(ys),
        })
    return lines
