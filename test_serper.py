"""Tests for the OPTIONAL Serper.dev (Google Scholar) DOI fallback. Network is
always mocked — these never make a real request."""

from unittest import mock

import editor


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_verify_key_empty_is_disabled():
    ok, msg = editor.verify_serper_key("")
    assert ok is False and "No Serper API key" in msg


def test_verify_key_rejected_token_notifies():
    with mock.patch.object(editor.requests, "post", return_value=_Resp(401)):
        ok, msg = editor.verify_serper_key("bad-token")
    assert ok is False and "rejected" in msg.lower()


def test_verify_key_quota_exceeded():
    with mock.patch.object(editor.requests, "post", return_value=_Resp(429)):
        ok, msg = editor.verify_serper_key("k")
    assert ok is False and "quota" in msg.lower()


def test_verify_key_ok():
    with mock.patch.object(editor.requests, "post", return_value=_Resp(200, {})):
        ok, msg = editor.verify_serper_key("good")
    assert ok is True


def test_verify_key_network_error_notifies():
    err = editor.requests.exceptions.ConnectionError("down")
    with mock.patch.object(editor.requests, "post", side_effect=err):
        ok, msg = editor.verify_serper_key("k")
    assert ok is False and "unreachable" in msg.lower()


def test_fetch_doi_no_key_returns_none():
    # No network call should happen without a key.
    with mock.patch.object(editor.requests, "post") as p:
        assert editor.fetch_serper_scholar_doi("Smith J. A study. 2020.", "") is None
        p.assert_not_called()


def test_fetch_doi_extracts_from_matching_result():
    citation = "Hsu SC. The impact of anxiety on sleep. 2009."
    payload = {"organic": [
        {"title": "The impact of anxiety on sleep",
         "link": "https://doi.org/10.1016/j.comppsych.2008.07.002",
         "snippet": "..."},
    ]}
    with mock.patch.object(editor.requests, "post", return_value=_Resp(200, payload)):
        doi = editor.fetch_serper_scholar_doi(citation, "key")
    assert doi == "https://doi.org/10.1016/j.comppsych.2008.07.002"


def test_fetch_doi_skips_unrelated_title():
    # A result whose title does not overlap the citation must NOT yield a DOI.
    citation = "Hsu SC. The impact of anxiety on sleep. 2009."
    payload = {"organic": [
        {"title": "A completely unrelated paper about volcanoes",
         "link": "https://doi.org/10.9999/wrong.doi", "snippet": ""},
    ]}
    with mock.patch.object(editor.requests, "post", return_value=_Resp(200, payload)):
        assert editor.fetch_serper_scholar_doi(citation, "key") is None


def test_fetch_doi_http_error_returns_none():
    with mock.patch.object(editor.requests, "post", return_value=_Resp(403)):
        assert editor.fetch_serper_scholar_doi("x" * 40, "key") is None
