"""The register may not contain a claim that is no longer true.

A quality log is only worth reading if it cannot drift. These tests fail when an entry
names a guard that has been renamed or deleted, or a test that does not exist — which
is exactly what happens six months from now, quietly, unless something checks.
"""
import importlib
import pathlib
import re

import pytest

from quality_log import LESSONS, as_rows

HERE = pathlib.Path(__file__).parent


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda x: x.found_in + " " + x.fixed_on)
def test_the_guard_named_by_an_entry_exists(lesson):
    module_name, _, attribute = lesson.prevented_by.rpartition(".")
    module = importlib.import_module(module_name)
    assert hasattr(module, attribute), (
        f"{lesson.prevented_by} is named as the guard for '{lesson.went_wrong[:60]}…' "
        f"and is not there. Either the guard moved and this entry must follow it, or "
        f"the guard is gone and the defect is unguarded again.")


@pytest.mark.parametrize("lesson", LESSONS, ids=lambda x: x.found_in + " " + x.fixed_on)
def test_the_test_named_by_an_entry_exists(lesson):
    file_name, _, test_name = lesson.proved_by.partition("::")
    path = HERE / file_name
    assert path.exists(), f"{file_name} does not exist ({lesson.proved_by})"
    source = path.read_text(encoding="utf-8")
    assert re.search(rf"^def {re.escape(test_name)}\(", source, re.M), (
        f"{lesson.proved_by} is named as the proof for '{lesson.went_wrong[:60]}…' "
        f"and no such test is in {file_name}.")


def test_an_entry_says_what_the_tool_does_now():
    """The column the quality team actually reads. An entry without it is a bug
    report, not a lesson."""
    for lesson in LESSONS:
        assert lesson.now.strip(), lesson.went_wrong
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", lesson.fixed_on), lesson.fixed_on


def test_the_register_renders():
    rows = as_rows()
    assert len(rows) == len(LESSONS)
    assert set(rows[0]) == {"What went wrong", "Where", "Fixed", "What stops it now",
                            "Guarded by", "Proved by", "Measured"}


def test_a_wrong_entry_is_caught():
    """The guard on the guard. A register that cannot go red is decoration."""
    from quality_log import Lesson
    invented = Lesson(
        went_wrong="x", found_in="job #0", fixed_on="2026-01-01",
        prevented_by="edit_guards.a_guard_that_was_never_written",
        proved_by="test_edit_guards.py::test_that_was_never_written", now="x")
    with pytest.raises(AssertionError):
        test_the_guard_named_by_an_entry_exists(invented)
    with pytest.raises(AssertionError):
        test_the_test_named_by_an_entry_exists(invented)
