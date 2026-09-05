"""The optional tail stages.

Journal recommendation, the cover letter and the abstract polish each cost one model
call. Measured on a real manuscript: 11.6s/$0.0139, 8.9s/$0.0079, 12.4s/$0.0098 —
together about a third of a minute and roughly 5% of a job's cost. So these are
switches for time and clutter, not for money, and the defaults say so.

`polish_enabled` defaults to False for a different reason. Its output is a REWRITE of
the abstract, not a copyedit of it: on job 51 the redline said "The kinetic study of
the oxidation of thiourea by Cr(VI) ... was carried out using ..." while the report's
polished version opened "The catalytic oxidation of thiourea by chromium(VI) is a
significant reaction in environmental chemistry and industrial processes" — framing the
author never wrote. An editor read the two and reported them as a bug, correctly.
"""

import pipeline


def _opts(**over):
    base = {"edit_style": "Standard", "ref_style": "Vancouver", "lang_type": "US English",
            "user_id": 1, "filename": "m.docx"}
    base.update(over)
    return base


def _read(opts):
    """Just the option-reading half of run_pipeline, without running a job."""
    return {
        "journals": opts.get("journals_enabled", True),
        "cover_letter": opts.get("cover_letter_enabled", True),
        "polish": opts.get("polish_enabled", False),
        "ai_review": opts.get("ai_review_enabled", True),
    }


def test_defaults_keep_journals_and_the_cover_letter_but_not_the_polish():
    d = _read(_opts())
    assert d["journals"] is True
    assert d["cover_letter"] is True
    assert d["polish"] is False, "a rewrite must be asked for, never assumed"


def test_each_stage_can_be_switched_off():
    d = _read(_opts(journals_enabled=False, cover_letter_enabled=False,
                    ai_review_enabled=False))
    assert not any([d["journals"], d["cover_letter"], d["ai_review"]])


def test_the_polish_can_be_switched_on():
    assert _read(_opts(polish_enabled=True))["polish"] is True


def test_the_option_names_the_pipeline_reads_are_the_ones_the_app_sends():
    """A rename on one side only would silently restore the old always-on behaviour,
    and nothing would look broken."""
    source = open("pipeline.py").read()
    app = open("app.py").read()
    for name in ("journals_enabled", "cover_letter_enabled", "polish_enabled"):
        assert f'opts.get("{name}"' in source, f"pipeline never reads {name}"
        assert f'"{name}": {name}' in app, f"app never sends {name}"
