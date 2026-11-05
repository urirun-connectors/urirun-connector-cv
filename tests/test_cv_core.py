"""Offline tests for the cv connector: bindings shape, field merging, text-first parsing,
LLM extraction plumbing (mocked, never hits the network), and batch aggregation."""
import os

import pytest

import urirun_connector_cv.core as c


def test_bindings_valid():
    b = c.urirun_bindings()
    uris = set(b["bindings"])
    assert "cv://host/document/query/parse" in uris
    assert "cv://host/folder/query/batch" in uris
    assert "cv://host/doctor/query/report" in uris
    for spec in b["bindings"].values():
        assert spec["python"]["module"].endswith("core")
        assert spec["uri"].startswith("cv://")


def test_doctor_report():
    r = c.doctor()
    assert r["ok"] is True
    assert r["connector"] == "cv"
    assert r["status"] == "ready"


def test_parse_requires_path_or_text():
    r = c.parse()
    assert r["ok"] is False
    assert "provide path or text" in r["error"]
    assert r["fields"] == c._empty_fields()


def test_parse_rejects_too_short_text():
    r = c.parse(text="hi")
    assert r["ok"] is False
    assert "no usable text" in r["error"]


def test_parse_without_llm_returns_raw_text_only():
    body = "Jan Kowalski\nul. Testowa 1, Warszawa\nStanowisko: Programista Python"
    r = c.parse(text=body, use_llm=False)
    assert r["ok"] is True
    assert r["method"] == "given-text"
    assert r["fields"]["raw_text"] == body
    assert r["fields"]["full_name"] is None
    assert r["fields"]["skills"] == []


def test_parse_with_mocked_llm_merges_fields(monkeypatch):
    canned = {
        "full_name": "Jan Kowalski", "address": "Warszawa", "email": None, "phone": "",
        "position": "Programista", "skills": ["Python", "SQL"],
        "experience": [{"employer": "Acme", "role": "Dev", "start": "2020", "end": "present", "description": ""}],
        "education": [], "languages": ["polski", "angielski"], "summary": "Doświadczony programista.",
        "unexpected_key": "ignored",
    }
    monkeypatch.setattr(c, "_llm_extract", lambda text, model: canned)
    r = c.parse(text="Jan Kowalski, programista Python z 5-letnim doświadczeniem w Acme.")
    assert r["ok"] is True
    assert r["method"].endswith("+llm")
    f = r["fields"]
    assert f["full_name"] == "Jan Kowalski"
    assert f["position"] == "Programista"
    assert f["skills"] == ["Python", "SQL"]
    assert f["experience"][0]["employer"] == "Acme"
    assert f["languages"] == ["polski", "angielski"]
    # scalar fields the LLM returned as null/empty stay unset, not overwritten with junk
    assert f["email"] is None and f["phone"] is None
    assert "unexpected_key" not in f
    assert f["raw_text"].startswith("Jan Kowalski")


def test_parse_llm_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(c, "_llm_extract", lambda text, model: None)
    r = c.parse(text="Jan Kowalski, programista Python z wieloletnim doświadczeniem.")
    assert r["ok"] is False
    assert r["method"].endswith("+llm-failed")
    assert r["fields"]["skills"] == []


def test_merge_fields_ignores_non_list_for_list_field():
    fields = c._merge_fields({"skills": "not-a-list", "full_name": "X"})
    assert fields["skills"] == []
    assert fields["full_name"] == "X"


def test_merge_fields_handles_none():
    assert c._merge_fields(None) == c._empty_fields()


def test_docx_text_missing_python_docx_or_bad_file_returns_empty(tmp_path):
    bogus = tmp_path / "not-really.docx"
    bogus.write_text("not a real docx")
    assert c._docx_text(str(bogus)) == ""


def test_extract_text_docx_extension_without_valid_docx(tmp_path):
    bogus = tmp_path / "cv.docx"
    bogus.write_text("not a real docx")
    result = c._extract_text(str(bogus))
    assert result["ok"] is False
    assert result["backend"] == "python-docx"


def test_batch_not_a_directory():
    r = c.batch(root="/no/such/directory")
    assert r["ok"] is False
    assert "not a directory" in r["error"]


def test_batch_aggregates_rows(tmp_path, monkeypatch):
    (tmp_path / "a.pdf").write_text("placeholder")
    (tmp_path / "b.docx").write_text("placeholder")
    (tmp_path / "ignore.txt").write_text("placeholder")
    monkeypatch.setattr(c, "parse", lambda path, use_llm, model: {
        "ok": True, "method": "stub", "fields": c._empty_fields(),
    })
    r = c.batch(root=str(tmp_path), extensions="pdf,docx")
    assert r["ok"] is True
    assert r["files"] == 2
    assert r["parsed"] == 2
    assert {row["file"] for row in r["rows"]} == {"a.pdf", "b.docx"}


def test_extract_with_oqllm_docker(monkeypatch):
    """Verify CV LLM extraction connectivity through local OQLLM Docker instance."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11437/health", timeout=1.0) as resp:
            if resp.status != 200:
                pytest.skip("OQLLM Docker not healthy")
    except Exception:
        pytest.skip("OQLLM Docker not reachable on 11437")

    monkeypatch.setenv("CV_LLM_API_BASE", "http://127.0.0.1:11437/v1")
    monkeypatch.setenv("CV_LLM_API_KEY", "oqllm_live_loopback_root")

    res = c._llm_extract("Jan Kowalski, Python dev", "oqlos/system-one-router")
    assert isinstance(res, dict)
    assert "input_format" in res


class _Resp:
    def __init__(self, content):
        msg = type("M", (), {"content": content})()
        self.choices = [type("C", (), {"message": msg})()]

    def __getitem__(self, key):  # dict-style access used by some connectors
        return {"choices": [{"message": {"content": self.choices[0].message.content}}]}[key]


def _capture(monkeypatch):
    import litellm
    seen = {}
    def fake(**kw):
        seen.update(kw)
        return _Resp('{"ok": true}')
    monkeypatch.setattr(litellm, "completion", fake)
    for var in ("URIRUN_LLM_API_BASE", "URIRUN_LLM_API_KEY", "OQLLM_API_KEY", "OPENAI_API_BASE", "CV_LLM_API_BASE", "CV_LLM_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-must-not-leak")
    return seen


def test_default_call_does_not_forward_foreign_credentials(monkeypatch):
    seen = _capture(monkeypatch)
    c._llm_extract("Jan Kowalski", "openrouter/qwen/qwen3.7-plus")
    assert "api_key" not in seen and "api_base" not in seen
    assert seen["model"].startswith("openrouter/")


def test_explicit_gateway_gets_only_gateway_key(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setenv("CV_LLM_API_BASE", "http://127.0.0.1:11437/v1")
    monkeypatch.setenv("OQLLM_API_KEY", "oqllm-key")
    c._llm_extract("Jan Kowalski", "openrouter/qwen/qwen3.7-plus")
    assert seen["api_base"] == "http://127.0.0.1:11437/v1"
    assert seen["api_key"] == "oqllm-key"
