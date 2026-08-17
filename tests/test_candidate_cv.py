"""A candidate's CV: attach it, read it, and above all do not lose it.

The dangerous part of this feature is not the upload. It is that the Recruitment screens PATCH the
whole candidate object they are holding — advancing a stage, saving an evaluation — and that object
came from a LIST read, which blanks cvFile so an applicant's PDF does not ride along with every
board render. Without server-side reconciliation the first evaluation saved after attaching a CV
deletes it, the record still says a CV was attached, and nobody finds out until someone clicks Open.

That is the same failure the contracts reconciliation was written for. These tests are here so it
cannot come back.
"""
import base64

import pytest

import db


PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 fake cv bytes").decode()


@pytest.fixture
def cand(api, tokens):
    st, b = api("POST", "/api/coll/candidates", tokens["mgr"],
                {"name": "Nguyen Van Bao", "role": "Electrical Engineer",
                 "stage": "Applied", "source": "TopCV"})
    assert st == 200, b
    row = b.get("item") or b
    cid = row.get("id")
    assert cid
    yield cid
    try:
        conn = db.get_conn()
        conn.execute("DELETE FROM collections WHERE coll='candidates' AND id=?", (cid,))
        conn.commit(); conn.close()
    except Exception:
        pass


def _attach(api, tokens, cid, who="mgr", **over):
    body = {"candidateId": cid, "file": PDF, "fileName": "bao-cv.pdf"}
    body.update(over)
    return api("POST", "/api/hr/cv", tokens[who], body)


# ── the round trip that used to destroy it ───────────────────────────────────────────────────────

def test_a_normal_save_does_not_delete_the_cv(api, tokens, cand):
    """THE regression. Attach a CV, then do exactly what the evaluation dialog does: PATCH the whole
    record as the browser is holding it — i.e. with cvFile blanked by the list read."""
    st, _ = _attach(api, tokens, cand)
    assert st == 200

    st, b = api("GET", "/api/coll/candidates", tokens["mgr"])
    assert st == 200
    row = next(x for x in (b.get("items") or b.get("candidates") or []) if x["id"] == cand)
    assert row.get("hasCv") is True
    assert not row.get("cvFile"), "the list read shipped the CV bytes to the whole board"

    row["evals"] = {"Applied": {"score": 4.0, "rec": "Hire"}}
    st, _ = api("PATCH", "/api/coll/candidates/" + cand, tokens["mgr"], row)
    assert st == 200

    stored = db.get_collection_item("candidates", cand) or {}
    assert stored.get("cvFile") == PDF, "saving an evaluation deleted the CV"
    assert stored.get("cvName") == "bao-cv.pdf"
    assert (stored.get("evals") or {}).get("Applied", {}).get("score") == 4.0


def test_advancing_a_stage_does_not_delete_the_cv(api, tokens, cand):
    st, _ = _attach(api, tokens, cand)
    assert st == 200
    st, b = api("GET", "/api/coll/candidates", tokens["mgr"])
    row = next(x for x in (b.get("items") or b.get("candidates") or []) if x["id"] == cand)
    row["stage"] = "Screening"
    st, _ = api("PATCH", "/api/coll/candidates/" + cand, tokens["mgr"], row)
    assert st == 200
    stored = db.get_collection_item("candidates", cand) or {}
    assert stored.get("cvFile") == PDF
    assert stored.get("stage") == "Screening"


def test_replacing_the_cv_still_works(api, tokens, cand):
    """Reconciliation must not become a lock: a real replacement has to get through."""
    assert _attach(api, tokens, cand)[0] == 200
    other = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 the corrected cv").decode()
    st, _ = _attach(api, tokens, cand, file=other, fileName="bao-cv-v2.pdf")
    assert st == 200
    stored = db.get_collection_item("candidates", cand) or {}
    assert stored.get("cvFile") == other
    assert stored.get("cvName") == "bao-cv-v2.pdf"


# ── who may touch it ─────────────────────────────────────────────────────────────────────────────

def test_staff_cannot_attach_or_read_a_cv(api, tokens, cand):
    """A CV is an outsider's personal data held for one purpose. Ordinary staff have no part in it."""
    st, _ = _attach(api, tokens, cand, who="staff")
    assert st == 403
    assert _attach(api, tokens, cand)[0] == 200
    st, _ = api("GET", "/api/hr/cv/" + cand, tokens["staff"])
    assert st == 403


def test_the_bytes_come_back_for_someone_entitled(api, tokens, cand):
    assert _attach(api, tokens, cand)[0] == 200
    st, b = api("GET", "/api/hr/cv/" + cand, tokens["mgr"])
    assert st == 200, b
    assert b["file"] == PDF
    assert b["fileName"] == "bao-cv.pdf"


def test_reading_a_cv_is_recorded(api, tokens, cand):
    """The review step only means something if a named person did it, so the read is logged
    server-side where it cannot be skipped."""
    assert _attach(api, tokens, cand)[0] == 200
    assert api("GET", "/api/hr/cv/" + cand, tokens["mgr"])[0] == 200
    rows = db.list_collection("audit") or []
    assert any(r.get("action") == "CV opened" and cand in str(r.get("target") or "") for r in rows), \
        "opening a candidate's CV left no trace"


# ── what may be stored ───────────────────────────────────────────────────────────────────────────

def test_a_cv_must_be_a_document_not_a_script(api, tokens, cand):
    st, b = _attach(api, tokens, cand, file="data:text/html;base64," +
                    base64.b64encode(b"<script>alert(1)</script>").decode(), fileName="cv.html")
    assert st == 400
    assert "PDF" in b.get("error", "")


def test_a_missing_or_unreadable_file_is_refused(api, tokens, cand):
    assert _attach(api, tokens, cand, file="")[0] == 400
    assert _attach(api, tokens, cand, file="https://example.com/cv.pdf")[0] == 400


def test_an_oversized_cv_is_refused(api, tokens, cand):
    big = "data:application/pdf;base64," + base64.b64encode(b"x" * (9 * 1024 * 1024)).decode()
    assert _attach(api, tokens, cand, file=big)[0] == 400


def test_attaching_to_a_candidate_that_is_gone(api, tokens):
    st, b = api("POST", "/api/hr/cv", tokens["mgr"],
                {"candidateId": "no-such-candidate", "file": PDF, "fileName": "x.pdf"})
    assert st == 404


def test_the_file_name_cannot_carry_a_path_or_newline(api, tokens, cand):
    """It is rendered on the card and offered as a download name."""
    st, _ = _attach(api, tokens, cand, fileName="../../etc/passwd\nSet-Cookie: x=1")
    assert st == 200
    stored = db.get_collection_item("candidates", cand) or {}
    nm = stored.get("cvName") or ""
    assert "/" not in nm and "\\" not in nm and "\n" not in nm and "\r" not in nm
