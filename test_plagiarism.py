"""Tests for the OPTIONAL Serper-based preliminary originality (web-match) scan.
Network is always mocked — these never make a real request."""

from unittest import mock

import editor


def test_no_key_noops():
    res = editor.plagiarism_scan(["Some long body sentence here for testing only."], "")
    assert res["available"] is False
    assert "No Serper API key" in res["note"]


def test_candidate_filtering_skips_short_keywords_and_refs():
    paras = [
        "Short line.",                                   # too few words -> skip
        "Keywords: ai, robotics, learning systems",      # keywords line -> skip
        "Smith J, Jones B, Lee C, Patel D, et al. 2019.",  # reference -> skip
        "This is a sufficiently long ordinary body sentence that should be scanned now.",
    ]
    cands = editor._candidate_sentences(paras)
    assert cands == [
        "This is a sufficiently long ordinary body sentence that should be scanned now."
    ]


def test_max_checks_bounds_query_budget():
    paras = [
        "This is body sentence number {} that is long enough to be checked here.".format(i)
        for i in range(100)
    ]
    cands = editor._candidate_sentences(paras, max_checks=10)
    assert len(cands) == 10


def test_scan_flags_verbatim_match_and_scores():
    paras = [
        "This is a sufficiently long ordinary body sentence that should be scanned now.",
        "Another distinct and sufficiently long sentence that will not match anything.",
    ]

    def fake_post(url, headers=None, json=None, timeout=None):
        # The first sentence "matches" (organic hit); the second does not.
        q = json["q"]
        if "should be scanned" in q:
            return _Resp(200, {"organic": [
                {"title": "Some Source", "link": "https://example.com/a"},
            ]})
        return _Resp(200, {"organic": []})

    with mock.patch.object(editor.requests, "post", side_effect=fake_post):
        res = editor.plagiarism_scan(paras, "key", max_workers=2)

    assert res["available"] is True
    assert res["checked"] == 2
    assert len(res["flagged"]) == 1
    assert res["flagged"][0]["sources"][0]["link"] == "https://example.com/a"
    assert res["score"] == 50  # 1 of 2 matched -> 50% originality
    assert "Turnitin" in res["disclaimer"]


def test_scan_network_error_is_not_flagged():
    paras = ["This is a sufficiently long ordinary body sentence that should be scanned."]
    err = editor.requests.exceptions.ConnectionError("down")
    with mock.patch.object(editor.requests, "post", side_effect=err):
        res = editor.plagiarism_scan(paras, "key")
    assert res["available"] is True and res["flagged"] == [] and res["score"] == 100


def test_build_report_empty_when_unavailable():
    assert editor.build_plagiarism_report(None) == ""
    assert editor.build_plagiarism_report({"available": False}) == ""


def test_build_report_has_summary_sources_and_disclaimer():
    plag = {
        "available": True, "checked": 5, "score": 80,
        "disclaimer": editor.PLAGIARISM_DISCLAIMER,
        "flagged": [{"sentence": "Copied line.",
                     "sources": [{"title": "Src", "link": "https://x.com"}]}],
    }
    md = editor.build_plagiarism_report(plag)
    assert "Preliminary Originality Report" in md
    assert "80%" in md and "Sentences checked:** 5" in md
    assert "Turnitin" in md                       # disclaimer present
    assert "[Src](https://x.com)" in md           # full source link rendered


def test_build_report_no_matches_message():
    plag = {"available": True, "checked": 7, "score": 100,
            "disclaimer": editor.PLAGIARISM_DISCLAIMER, "flagged": []}
    md = editor.build_plagiarism_report(plag)
    assert "No verbatim web matches" in md


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload
