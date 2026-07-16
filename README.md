# urirun-connector-cv

**CV / resume field extraction** — connector ekosystemu [ifURI / urirun](https://github.com/if-uri/urirun).
Schemat URI: `cv://`

Extract structured fields from CVs/resumes over cv:// URIs — full name, address, email, phone, position, skills, experience, education, languages. Text via `python-docx` (DOCX) or `doc://` OCR (PDF/image, layering pdftotext/PaddleOCR/tesseract), fields via an LLM pass (OpenRouter).

## Opis

cv:// turns résumé parsing into a first-class URI. `cv://host/document/query/parse` returns structured fields `{full_name, address, email, phone, position, skills, experience, education, languages, summary, raw_text}` from one PDF/DOCX/image/text file. DOCX is read directly via `python-docx`; everything else is delegated to `doc://` ([urirun-connector-ocr](https://github.com/urirun-connectors/urirun-connector-ocr)), which already chooses the right backend (pdftotext for text-layer PDFs, PaddleOCR/tesseract for scans and images) and degrades gracefully when a backend is missing.

Unlike [invoice://](https://github.com/urirun-connectors/urirun-connector-invoice), a CV has no stable label grammar to regex against, so field extraction is **LLM-first** (OpenRouter via litellm) rather than regex-first with an LLM fallback. Set `use_llm=false` to get back only the extracted raw text — useful for inspecting OCR quality before spending an LLM call.

`cv://host/folder/query/batch` parses every CV under a folder into rows, for a one-off backlog import. Read-only over the CV files.

## Wymagania

- **system:** poppler-utils (`pdftotext`/`pdftoppm`) and/or `tesseract`, via `doc://` — for PDF/image CVs
- **python:** `urirun`, `urirun-connector-ocr`
- **optional:** `python-docx` for DOCX CVs; `litellm` + `OPENROUTER_API_KEY` for field extraction (`use_llm=true`, the default)

## Instalacja (dev)

```bash
pip install -e .
pytest -q
```

## Użycie

```bash
# extract only raw text (no LLM call) — check OCR quality first
urirun-cv parse --path /cv-inbox/jan-kowalski.pdf --use_llm=false

# full structured extraction
OPENROUTER_API_KEY=sk-... urirun-cv parse --path /cv-inbox/jan-kowalski.pdf

# batch a backlog folder
urirun-cv batch --root /cv-inbox
```

## Powiązane

- Rdzeń: [if-uri/urirun](https://github.com/if-uri/urirun)
- OCR: [urirun-connector-ocr](https://github.com/urirun-connectors/urirun-connector-ocr)
- Podobny wzorzec ekstrakcji: [urirun-connector-invoice](https://github.com/urirun-connectors/urirun-connector-invoice)
- Hub connectorów: [connect.ifuri.com](https://connect.ifuri.com)

---
Kategoria: HR · Słowa kluczowe: cv, resume, hr, recruitment, ocr, extraction · Wydawca: if-uri
