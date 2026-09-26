"""ADR-141 Stage 13.3 — /api/axioms + /api/axioms/{id}/verify.

Two donor routes (donor main.py:2042/2072) over the 13.3 substrate:
donor ``tektos/axioms.py`` (262 LOC, self-contained: yaml + dataclasses)
verbatim → ``kernel/axioms.py`` (generic context-compression knowledge
store → kernel-level per the governing layering rule). Tektos axiom
DATA (19 .axiom files) shipped with the plugin (``plugins/tektos/axioms/``)
and is passed to the substrate as a directory — never imported (ADR-007).
``registry.tektos_axioms`` (AxiomSystem) replaces the donor's module-level
``load_axioms()`` singleton.

Wire locks (donor-verbatim):
- ``GET /api/axioms`` → bare 10-field list (id/category/status/date/
  content/notes/prerequisites/blocking/tags/metadata); ``?category=``
  filters; any failure → ``[]`` at 200 (donor log+degrade).
- ``POST /api/axioms/{id}/verify`` → ``{"ok": true, "id", "status":
  "verified"}`` (persisted to disk via _save); unknown id → 404
  ``{"detail": "Axiom '<id>' not found"}``; subsystem absent → 404 same
  shape (donor's 404 branch is the only honest degrade — the donor had
  no "uninitialized" state: its singleton always existed, possibly empty).

Tests use a tmp COPY of the plugin axiom data (verify() rewrites the
.axiom files on disk), with KOSMOS_TEKTOS_AXIOMS_DIR pointed at it.
"""
import os
import shutil
import tempfile

import pytest

# env BEFORE kernel.app import (module-level, no re-import trickery).
os.environ["KOSMOS_MEMORY_BACKEND"] = "in_memory"
os.environ["KOSMOS_GNOSIS_SEED"] = "0"
os.environ.pop("TEKTOS_SELF_IMPROVEMENT_ENABLED", None)

_TMPAX = tempfile.mkdtemp(prefix="s133ax")
shutil.copytree(
    os.path.expanduser("~/dev/kosmos-lms/plugins/tektos/axioms"), _TMPAX, dirs_exist_ok=True
)
os.environ["KOSMOS_TEKTOS_AXIOMS_DIR"] = _TMPAX

import kernel.app as ka  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def env():
    with TestClient(ka.app) as client:
        yield {"client": client}
    shutil.rmtree(_TMPAX, ignore_errors=True)


def test_axioms_list_all(env):
    r = env["client"].get("/api/axioms")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    assert len(items) >= 20  # donor ships 19 files / 29 active axioms
    # 10-field donor wire shape, locked field-for-field.
    keys = set(items[0].keys())
    assert keys == {
        "id", "category", "status", "date", "content", "notes",
        "prerequisites", "blocking", "tags", "metadata",
    }
    by_id = {a["id"]: a for a in items}
    assert "constraint.loop_safety" in by_id
    assert by_id["constraint.loop_safety"]["status"] == "verified"


def test_axioms_list_category_filter(env):
    r = env["client"].get("/api/axioms", params={"category": "constraint"})
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    assert all(a["category"] == "constraint" for a in items)
    # unknown category → [] (donor list_by_category semantics)
    r2 = env["client"].get("/api/axioms", params={"category": "no_such_category"})
    assert r2.status_code == 200
    assert r2.json() == []


def test_axiom_verify_persists(env):
    # pick a pending/in_progress axiom so the flip is observable
    all_ = env["client"].get("/api/axioms").json()
    flip = next((a for a in all_ if a["status"] in ("pending", "in_progress")), None)
    if flip is None:
        # all verified (donor data state) — use one and re-verify
        flip = next(a for a in all_ if a["status"] == "verified")
    before = flip["status"]

    r = env["client"].post(f"/api/axioms/{flip['id']}/verify")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": flip["id"], "status": "verified"}
    # persisted to the (tmp) data dir: fresh list shows verified
    after = {a["id"]: a["status"] for a in env["client"].get("/api/axioms").json()}
    assert after[flip["id"]] == "verified"
    assert before in ("pending", "in_progress", "verified")


def test_axiom_verify_unknown_404(env):
    r = env["client"].post("/api/axioms/no.such.axiom/verify")
    assert r.status_code == 404
    assert r.json() == {"detail": "Axiom 'no.such.axiom' not found"}


def test_axioms_subsystem_absent_degrade(env):
    # registry slot None (subsystem failed boot) → donor's empty-system
    # shapes: list [] at 200, verify 404 (the donor had no "uninitialized"
    # state — its singleton always existed, possibly empty).
    old = ka.registry.tektos_axioms
    ka.registry.tektos_axioms = None
    try:
        assert env["client"].get("/api/axioms").json() == []
        r = env["client"].post("/api/axioms/anything/verify")
        assert r.status_code == 404
        assert r.json() == {"detail": "Axiom 'anything' not found"}
    finally:
        ka.registry.tektos_axioms = old
