from __future__ import annotations

import json
from pathlib import Path

import pytest

import urirun_connector_cv.core as core

_uc = pytest.importorskip("urirun_contract")
Contract = _uc.Contract
conform = _uc.conform

PKG = Path(__file__).resolve().parents[1] / "urirun_connector_cv"
CONTRACTS = PKG / "contracts.json"


def _load() -> dict:
    doc = json.loads(CONTRACTS.read_text(encoding="utf-8"))
    return {
        route: Contract(
            version=c["version"],
            effect=c["effect"],
            reversible=c["reversible"],
            inverse_route=c.get("inverseRoute", ""),
            inp=c["inp"],
            out=c["out"],
            errors=tuple(c["errors"]),
            examples=tuple(c["examples"]),
        )
        for route, c in doc["contracts"].items()
    }


def test_contract_conforms() -> None:
    conform(_load())


def test_every_binding_route_has_a_contract() -> None:
    declared = set(json.loads(CONTRACTS.read_text(encoding="utf-8"))["contracts"])
    assert set(core.urirun_bindings()["bindings"]) == declared


def test_public_handlers_are_exported_not_helpers() -> None:
    bindings = core.urirun_bindings()["bindings"]
    assert bindings["cv://host/document/query/parse"]["python"]["export"] == "parse"
    assert bindings["cv://host/folder/query/batch"]["python"]["export"] == "batch"
