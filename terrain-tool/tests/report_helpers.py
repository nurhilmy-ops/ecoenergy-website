"""Helpers for the report renderer tests: sample result, placeholder figures, text extraction."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from matplotlib.figure import Figure

from app.config import Settings

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_result.json"

# Contract file names, with sizes (inches) close to what app.terrain.figures produces,
# including one tall figure so the "fit to height" path is exercised.
FIGURE_SIZES = {
    "1_site_layout.png": (7.5, 6.0),
    "2_elevation.png": (7.5, 6.2),
    "3_slope_classes.png": (8.0, 5.6),
    "4_profiles.png": (7.5, 9.5),
}


def load_sample() -> dict:
    return copy.deepcopy(json.loads(FIXTURE.read_text(encoding="utf-8")))


def write_placeholder_figures(out_dir: Path, names=None) -> list[Path]:
    """Draw small labelled PNGs with the matplotlib OO API (no pyplot, thread safe)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names or FIGURE_SIZES:
        fig = Figure(figsize=FIGURE_SIZES.get(name, (7.5, 6.0)), dpi=80)
        ax = fig.add_subplot()
        ax.plot([0, 1, 2, 3], [0, 2, 1, 3], color="#0F2742")
        ax.set_title(f"placeholder {name}")
        path = out_dir / name
        fig.savefig(path)
        paths.append(path)
    return paths


def report_settings(tmp_path: Path, **overrides) -> Settings:
    """Settings without reading the environment or a .env file."""
    return Settings(data_dir=tmp_path, **overrides)


def squash(text: str) -> str:
    """Collapse all whitespace so wrapped lines compare equal to the source text."""
    return re.sub(r"\s+", " ", text).strip()


def pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    return squash(" ".join(page.extract_text() or "" for page in PdfReader(str(path)).pages))


def docx_text(doc) -> str:
    """All body text of a python-docx Document: paragraphs and table cells, in order."""
    from docx.oxml.ns import qn
    parts = ["".join(t.text or "" for t in p.iter(qn("w:t")))
             for p in doc.element.body.iter(qn("w:p"))]
    return squash(" ".join(parts))
