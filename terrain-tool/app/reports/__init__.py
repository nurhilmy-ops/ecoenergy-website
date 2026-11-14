"""Report renderers.

Public API: ``build_reports(result, out_dir, settings) -> {"pdf": Path, "docx": Path}``.
Both formats are rendered from one renderer-neutral block list (``content.build_content``),
so the PDF and the Word file always say exactly the same thing.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from ..config import Settings
from .content import build_content
from .docx import render_docx
from .pdf import render_pdf

__all__ = ["build_reports", "PDF_NAME", "DOCX_NAME"]

log = logging.getLogger(__name__)

PDF_NAME = "report.pdf"
DOCX_NAME = "report.docx"


def _write_atomically(target: Path, render: Callable[[Path], Path]) -> Path:
    """Render to a temporary file next to `target`, then rename it into place, so a
    download never sees a half-written report."""
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        render(tmp)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def build_reports(result: dict, out_dir: Path, settings: Settings) -> dict[str, Path]:
    """Render report.pdf and report.docx into out_dir from result (+ the PNGs it references,
    which live in out_dir). Returns {"pdf": Path, "docx": Path}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    content = build_content(result, out_dir, settings)
    pdf = _write_atomically(out_dir / PDF_NAME, lambda p: render_pdf(content, p))
    docx = _write_atomically(out_dir / DOCX_NAME, lambda p: render_docx(content, p))
    log.info("reports %s: %d blocks rendered to PDF and DOCX",
             content.info.short_id, len(content.blocks))
    return {"pdf": pdf, "docx": docx}
