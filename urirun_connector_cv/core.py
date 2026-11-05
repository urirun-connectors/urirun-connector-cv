# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
#
# cv:// connector — structured field extraction from CVs/resumes, turning a PDF/DOCX/
# image into {full_name, address, email, phone, position, skills, experience, education,
# languages, summary} over a URI instead of eyeballing a résumé. Text extraction for
# PDFs/images is delegated to doc:// (urirun-connector-ocr, which already layers
# pdftotext / PaddleOCR / tesseract), DOCX is read directly via python-docx. Unlike
# invoice:// a CV has no stable label grammar to regex against, so field extraction is
# LLM-first (OpenRouter via litellm) rather than regex-first-LLM-fallback.

from __future__ import annotations

import os
import re
from typing import Any

import urirun

from . import _urirun_compat

CONNECTOR_ID = "cv"
CV = _urirun_compat.connector(CONNECTOR_ID, scheme="cv", target="host", meta={"label": "CV / resume field extraction"})

_FIELDS = ("full_name", "address", "email", "phone", "position", "skills",
           "experience", "education", "languages", "summary")
_LIST_FIELDS = {"skills", "experience", "education", "languages"}
_MIN_TEXT_CHARS = 20


def _empty_fields() -> dict[str, Any]:
    return {k: ([] if k in _LIST_FIELDS else None) for k in _FIELDS}


def _docx_text(path: str) -> str:
    try:
        import docx  # type: ignore
    except Exception:  # noqa: BLE001 - optional dependency
        return ""
    try:
        document = docx.Document(path)
    except Exception:  # noqa: BLE001 - not a valid docx
        return ""
    parts = [p.text for p in document.paragraphs if p.text]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells if cell.text)
    return "\n".join(parts)


def _extract_text(path: str) -> dict[str, Any]:
    """Extract raw text from a CV file. DOCX goes through python-docx; everything else
    (PDF, image, plain text) is delegated to doc:// (urirun-connector-ocr), which already
    chooses the right backend (pdftotext for text-layer PDFs, PaddleOCR/tesseract for
    scans/images) and degrades gracefully when a backend is missing."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        text = _docx_text(path)
        return {"ok": bool(text.strip()), "text": text, "backend": "python-docx"} if text.strip() else \
               {"ok": False, "text": "", "backend": "python-docx", "error": "empty or unreadable docx (is python-docx installed?)"}
    try:
        from urirun_connector_ocr.core import document_text
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "text": "", "backend": "none", "error": f"needs urirun-connector-ocr: {exc}"}
    result = document_text(path=path)
    return {"ok": bool(result.get("ok")), "text": str(result.get("text") or ""),
            "backend": result.get("backend", "ocr"), "error": result.get("error")}


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.S)


def _llm_extract(text: str, model: str) -> dict[str, Any] | None:
    """LLM pass (OpenRouter via litellm) that turns free-form CV text into the structured
    field set. This is the primary extraction path (not a fallback): CVs have no reliable
    label grammar to regex against the way invoices do."""
    try:
        import json as _json
        import litellm  # type: ignore
        prompt = (
            "Extract this CV/resume as compact JSON with exactly these keys: "
            "full_name (str), address (str), email (str), phone (str), position (str, "
            "most recent/target job title), skills (array of str), "
            "experience (array of {employer, role, start, end, description}), "
            "education (array of {institution, degree, start, end}), "
            "languages (array of str), summary (str, 1-2 sentences). "
            "Use null for a missing scalar and [] for a missing list. Dates as YYYY-MM "
            "or YYYY when only a year is known, \"present\" for ongoing. "
            "Return ONLY the JSON object, no prose, no markdown fences.\n\nCV text:\n\n"
            + text[:12000]
        )
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 1500,
        }
        api_base = os.environ.get("CV_LLM_API_BASE") or os.environ.get("URIRUN_LLM_API_BASE") or os.environ.get("OPENAI_API_BASE")
        if api_base:
            kwargs["api_base"] = api_base
            if not (model.startswith("openai/") or model.startswith("openrouter/")):
                kwargs["model"] = f"openai/{model}"
        api_key = os.environ.get("CV_LLM_API_KEY") or os.environ.get("OQLLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if api_key:
            kwargs["api_key"] = api_key

        resp = litellm.completion(**kwargs)
        out = resp["choices"][0]["message"]["content"]
        match = _JSON_OBJECT_RE.search(out)
        return _json.loads(match.group(0)) if match else None
    except Exception:  # noqa: BLE001
        return None


def _merge_fields(llm_fields: dict[str, Any] | None) -> dict[str, Any]:
    fields = _empty_fields()
    if not llm_fields:
        return fields
    for key in _FIELDS:
        value = llm_fields.get(key)
        if key in _LIST_FIELDS:
            if isinstance(value, list):
                fields[key] = value
        elif value not in (None, ""):
            fields[key] = value
    return fields


@CV.handler("document/query/parse", isolated=True,
           meta={"label": "Extract structured fields from one CV/resume", "cliAlias": "parse"})
def parse(path: str = "", text: str = "", use_llm: bool = True,
         model: str = "openrouter/qwen/qwen3.7-plus") -> dict[str, Any]:
    """Structured fields of a CV at `path` (PDF/DOCX/image/text) or raw `text`:
    full_name, address, email, phone, position, skills, experience, education, languages,
    summary. Text extraction: DOCX via python-docx, everything else via doc:// (OCR).
    Field extraction is LLM-first (use_llm=false returns only the extracted raw text with
    empty fields, e.g. to inspect OCR quality before spending an LLM call)."""
    path = os.path.expanduser(path) if path else ""
    extraction = {"ok": True, "text": text, "backend": "given-text"} if text else \
        (_extract_text(path) if path else {"ok": False, "text": "", "backend": "none", "error": "provide path or text"})
    body = extraction.get("text") or ""
    if len(body.strip()) < _MIN_TEXT_CHARS:
        return {"ok": False, "connector": CONNECTOR_ID, "kind": "cv", "live": False, "path": path,
                "method": extraction.get("backend", "none"),
                "error": extraction.get("error") or "no usable text extracted from CV",
                "fields": _empty_fields()}

    method = extraction.get("backend", "text")
    llm_fields = None
    if use_llm:
        llm_fields = _llm_extract(body, model)
        method = f"{method}+llm" if llm_fields else f"{method}+llm-failed"
    fields = _merge_fields(llm_fields)
    fields["raw_text"] = body[:20000]
    ok = bool(llm_fields) if use_llm else True
    return {"ok": ok, "connector": CONNECTOR_ID, "kind": "cv", "live": False, "path": path,
            "method": method, "fields": fields}


def _batch_walk(root: str, exts: set[str], recursive: bool):
    walker = os.walk(root) if recursive else [(root, [], os.listdir(root))]
    for dirpath, _dirs, files in walker:
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() in exts:
                yield os.path.join(dirpath, name)


@CV.handler("folder/query/batch", isolated=True,
           meta={"label": "Parse every CV in a folder", "cliAlias": "batch"})
def batch(root: str = "", extensions: str = "pdf,docx,png,jpg,jpeg", recursive: bool = False,
         use_llm: bool = True, max_files: int = 200,
         model: str = "openrouter/qwen/qwen3.7-plus") -> dict[str, Any]:
    """Parse every CV under `root` (matching `extensions`) into structured rows. Read-only
    over the CV files. Intended for a one-off backlog import, not a live inbox poll."""
    root = os.path.expanduser(root)
    if not os.path.isdir(root):
        return {"ok": False, "error": f"not a directory: {root}", "connector": CONNECTOR_ID}
    exts = {("." + e.strip().lstrip(".")).lower() for e in extensions.split(",") if e.strip()}
    rows = []
    for file_path in _batch_walk(root, exts, recursive):
        result = parse(path=file_path, use_llm=use_llm, model=model)
        rows.append({"file": os.path.basename(file_path), "ok": result.get("ok"),
                    "method": result.get("method"), "fields": result.get("fields")})
        if len(rows) >= max_files:
            break
    return {"ok": True, "connector": CONNECTOR_ID, "kind": "cv-batch", "live": False, "root": root,
            "files": len(rows), "parsed": sum(1 for r in rows if r["ok"]), "rows": rows}


@CV.handler("cv://host/doctor/query/report", isolated=True, meta={"label": "Connector readiness report"})
def doctor() -> dict[str, Any]:
    """Return a safe, read-only connector readiness report for CI smoke tests."""
    return {
        "ok": True,
        "connector": CONNECTOR_ID,
        "version": _connector_version(),
        "status": "ready",
    }


def _connector_version() -> str:
    try:
        from importlib.metadata import version

        return version("urirun-connector-cv")
    except Exception:
        return "0.1.0"


def main(argv: list[str] | None = None) -> int:
    return CV.cli(argv, manifest_prose=_urirun_compat.load_manifest(__package__))


urirun_bindings = CV.bindings
