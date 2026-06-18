"""Tests for JATS/XML export of an edited manuscript."""

import xml.etree.ElementTree as ET

from editor import build_jats_xml, validate_jats


SAMPLE = [
    "Deep Learning for Electrical Machine Fault Diagnosis",
    "Abstract",
    "We present a method for diagnosing faults using deep neural networks.",
    "Introduction",
    "Electrical machines are critical to industry.",
    "This paper proposes a new approach.",
    "Methods",
    "We trained a convolutional network on sensor data.",
    "Results",
    "The model achieved 98% accuracy.",
    "References",
    "Smith JA, Jones BR. Title of article. J Sci. 2020;10(2):100-10.",
    "Doe J. A Book on Machines. Springer; 2019.",
]


def _parse(xml_text):
    # Strip the DOCTYPE line so the stdlib parser (no DTD fetch) accepts it.
    body = "\n".join(
        ln for ln in xml_text.splitlines() if not ln.strip().startswith("<!DOCTYPE")
    )
    return ET.fromstring(body)


def test_is_well_formed_xml():
    root = _parse(build_jats_xml(SAMPLE))
    assert root.tag == "article"
    assert root.get("article-type") == "research-article"


def test_title_detected_in_front():
    root = _parse(build_jats_xml(SAMPLE))
    title = root.find("./front/article-meta/title-group/article-title")
    assert title is not None
    assert "Electrical Machine Fault Diagnosis" in title.text


def test_abstract_lifted_to_front():
    root = _parse(build_jats_xml(SAMPLE))
    abstract = root.find("./front/article-meta/abstract")
    assert abstract is not None
    assert "deep neural networks" in abstract.find("p").text
    # abstract must NOT also appear as a body section
    body_titles = [t.text for t in root.findall("./body/sec/title")]
    assert "Abstract" not in body_titles


def test_body_sections_split_by_heading():
    root = _parse(build_jats_xml(SAMPLE))
    titles = [t.text for t in root.findall("./body/sec/title")]
    assert "Introduction" in titles
    assert "Methods" in titles
    assert "Results" in titles


def test_references_become_ref_list():
    root = _parse(build_jats_xml(SAMPLE))
    refs = root.findall("./back/ref-list/ref")
    assert len(refs) == 2
    # first ref is a journal article -> structured element-citation
    ec = refs[0].find("element-citation")
    assert ec is not None
    surnames = [n.find("surname").text for n in ec.findall("./person-group/name")]
    assert "Smith" in surnames
    # second ref is a book -> structured book element-citation
    book = refs[1].find("element-citation")
    assert book is not None and book.get("publication-type") == "book"
    assert book.find("source").text == "A Book on Machines"
    # references must not leak into the body
    assert "References" not in [t.text for t in root.findall("./body/sec/title")]


def test_special_characters_escaped():
    # raw &, <, > must be safely encoded, not break the XML
    paras = ["Title & Scope", "Introduction", "A < B and C > D in R&D analysis."]
    xml_text = build_jats_xml(paras)
    assert "&amp;" in xml_text and "&lt;" in xml_text and "&gt;" in xml_text
    root = _parse(xml_text)  # still parses cleanly
    assert root.tag == "article"


def test_journal_title_included_when_provided():
    root = _parse(build_jats_xml(SAMPLE, journal_title="Journal of Testing"))
    jt = root.find("./front/journal-meta/journal-title-group/journal-title")
    assert jt is not None and jt.text == "Journal of Testing"


def test_explicit_title_overrides_first_paragraph():
    root = _parse(build_jats_xml(SAMPLE, title="Custom Title"))
    title = root.find("./front/article-meta/title-group/article-title")
    assert title.text == "Custom Title"


def test_empty_input_is_safe():
    root = _parse(build_jats_xml([]))
    title = root.find("./front/article-meta/title-group/article-title")
    assert title.text == "Untitled Manuscript"


# --- enhanced structure ---

WITH_AUTHORS = [
    "A Study of Fault Diagnosis",
    "John A. Smith, Maria Garcia, Wei Chen",
    "Department of Electrical Engineering, MIT",
    "Abstract",
    "We study faults.",
    "Keywords: deep learning, fault diagnosis, sensors",
    "Introduction",
    "Prior work established baselines [1]. A book also covers this [2].",
    "References",
    "Smith JA, Jones BR, Lee C. Fault diagnosis methods. J Sci. 2020;10(2):100-10. https://doi.org/10.1000/abc123",
    "Doe J. A Book on Machines. Springer; 2019.",
]


def test_authors_parsed_into_contrib_group():
    root = _parse(build_jats_xml(WITH_AUTHORS))
    contribs = root.findall("./front/article-meta/contrib-group/contrib")
    assert len(contribs) == 3
    surnames = [c.find("./name/surname").text for c in contribs]
    given = [c.find("./name/given-names").text for c in contribs]
    assert surnames == ["Smith", "Garcia", "Chen"]
    assert given[0] == "John A."  # byline: surname=last word, given=rest


def test_affiliation_captured():
    root = _parse(build_jats_xml(WITH_AUTHORS))
    aff = root.find("./front/article-meta/aff")
    assert aff is not None and "MIT" in aff.text
    # the affiliation line must not leak into the body
    body_paras = [p.text or "" for p in root.findall("./body//p")]
    assert not any("Department of Electrical" in t for t in body_paras)


def test_keywords_group():
    root = _parse(build_jats_xml(WITH_AUTHORS))
    kwds = [k.text for k in root.findall("./front/article-meta/kwd-group/kwd")]
    assert kwds == ["deep learning", "fault diagnosis", "sensors"]


def test_structured_journal_reference():
    root = _parse(build_jats_xml(WITH_AUTHORS))
    ec = root.find("./back/ref-list/ref[@id='ref1']/element-citation")
    assert ec is not None
    assert ec.get("publication-type") == "journal"
    assert ec.find("article-title").text == "Fault diagnosis methods"
    assert ec.find("source").text == "J Sci"
    assert ec.find("year").text == "2020"
    assert ec.find("volume").text == "10"
    assert ec.find("issue").text == "2"
    assert ec.find("fpage").text == "100"
    assert ec.find("lpage").text == "10"
    assert ec.find("pub-id[@pub-id-type='doi']").text == "10.1000/abc123"
    # reference authors use Vancouver surname/initials parsing
    surnames = [n.find("surname").text for n in ec.findall("./person-group/name")]
    assert surnames == ["Smith", "Jones", "Lee"]


def test_non_journal_reference_falls_back_to_mixed():
    # A reference with no recognizable journal/book/chapter structure (no year
    # block, no 'In:', no 'Publisher; Year') falls back to mixed-citation.
    paras = ["T", "Refs", "References",
             "World Health Organization. Global health note [Internet]. Available from: http://who.int/note"]
    root = _parse(build_jats_xml(paras))
    ref1 = root.find("./back/ref-list/ref[@id='ref1']")
    assert ref1.find("mixed-citation") is not None
    assert ref1.find("element-citation") is None


def test_in_text_citations_linked_to_refs():
    root = _parse(build_jats_xml(WITH_AUTHORS))
    xrefs = root.findall("./body//xref[@ref-type='bibr']")
    rids = sorted(x.get("rid") for x in xrefs)
    assert rids == ["ref1", "ref2"]
    # the xref label preserves the original number
    assert {x.text for x in xrefs} == {"1", "2"}


def test_out_of_range_citation_not_linked():
    # [9] has no matching reference, so it must stay plain text (no xref)
    paras = ["T", "Intro", "See [1] and [9].", "References",
             "Smith JA. Only ref. J X. 2020;1(1):1-2."]
    root = _parse(build_jats_xml(paras))
    rids = [x.get("rid") for x in root.findall("./body//xref[@ref-type='bibr']")]
    assert rids == ["ref1"]


def test_numbered_subsections_nest():
    paras = [
        "Title Here",
        "1 Methods",
        "Overview text.",
        "1.1 Data Collection",
        "We collected data.",
        "2 Results",
        "Findings.",
    ]
    root = _parse(build_jats_xml(paras))
    top = root.findall("./body/sec")
    titles = [s.find("title").text for s in top]
    assert "Methods" in titles and "Results" in titles
    methods = next(s for s in top if s.find("title").text == "Methods")
    # 1.1 should nest inside 1
    sub = methods.find("./sec/title")
    assert sub is not None and sub.text == "Data Collection"
    assert methods.find("./label").text == "1"


# --- remaining-limitation coverage ---

def test_single_author_detected_with_affiliation():
    paras = [
        "A Single Author Paper",
        "Jane Roe",
        "Department of Physics, Stanford University",
        "Introduction",
        "Body text.",
    ]
    root = _parse(build_jats_xml(paras))
    contribs = root.findall("./front/article-meta/contrib-group/contrib")
    assert len(contribs) == 1
    assert contribs[0].find("./name/surname").text == "Roe"
    assert root.find("./front/article-meta/aff") is not None


def test_single_name_heading_not_mistaken_for_author():
    # "Conclusions" alone (no affiliation after) must remain a section, not an author
    paras = ["Title", "Introduction", "Text.", "Conclusions", "We conclude."]
    root = _parse(build_jats_xml(paras))
    assert root.find("./front/article-meta/contrib-group") is None
    titles = [t.text for t in root.findall("./body/sec/title")]
    assert "Conclusions" in titles


def test_book_reference_structured():
    paras = ["T", "Refs intro", "References",
             "Doe J, Roe R. Machine Learning Foundations. 2nd ed. Cambridge: MIT Press; 2019."]
    root = _parse(build_jats_xml(paras))
    ec = root.find("./back/ref-list/ref[@id='ref1']/element-citation")
    assert ec is not None and ec.get("publication-type") == "book"
    assert ec.find("source").text == "Machine Learning Foundations"
    assert ec.find("edition").text.startswith("2nd")
    assert ec.find("publisher-loc").text == "Cambridge"
    assert ec.find("publisher-name").text == "MIT Press"
    assert ec.find("year").text == "2019"


def test_book_chapter_reference_structured():
    paras = ["T", "Refs intro", "References",
             "Smith JA. Neural nets. In: Brown G, editors. Handbook of AI. "
             "London: Springer; 2020. p. 33-58."]
    root = _parse(build_jats_xml(paras))
    ec = root.find("./back/ref-list/ref[@id='ref1']/element-citation")
    assert ec is not None and ec.get("publication-type") == "book-chapter"
    assert ec.find("chapter-title").text == "Neural nets"
    assert ec.find("source").text == "Handbook of AI"
    editors = ec.findall("./person-group[@person-group-type='editor']/name/surname")
    assert [e.text for e in editors] == ["Brown"]
    assert ec.find("publisher-name").text == "Springer"
    assert ec.find("fpage").text == "33" and ec.find("lpage").text == "58"


def test_figure_caption_becomes_fig():
    paras = ["T", "Results", "We saw effects.",
             "Figure 1. System architecture overview of the proposed model."]
    root = _parse(build_jats_xml(paras))
    fig = root.find(".//fig")
    assert fig is not None
    assert fig.find("label").text == "Figure 1"
    assert "architecture" in fig.find("./caption/p").text


def test_table_caption_becomes_table_wrap():
    paras = ["T", "Results", "Data follows.",
             "Table 2: Summary of accuracy across all datasets."]
    root = _parse(build_jats_xml(paras))
    tw = root.find(".//table-wrap")
    assert tw is not None
    assert tw.find("label").text == "Table 2"
    assert "accuracy" in tw.find("./caption/p").text


def test_validate_jats_ok():
    ok, issues = validate_jats(build_jats_xml(SAMPLE))
    assert ok and issues == []


def test_validate_jats_detects_broken_xref():
    bad = (
        '<?xml version="1.0"?>'
        '<article><front><article-meta><title-group>'
        '<article-title>T</article-title></title-group></article-meta></front>'
        '<body><sec><p>See <xref ref-type="bibr" rid="ref9">9</xref>.</p></sec></body>'
        '<back><ref-list><ref id="ref1"><mixed-citation>X</mixed-citation></ref>'
        '</ref-list></back></article>'
    )
    ok, issues = validate_jats(bad)
    assert not ok
    assert any("ref9" in i for i in issues)


def test_validate_jats_rejects_malformed():
    ok, issues = validate_jats("<article><front></article>")
    assert not ok
    assert any("well-formed" in i.lower() for i in issues)


# --- article metadata + structured authors ---

def test_article_metadata_emitted():
    meta = {
        "article_doi": "10.1234/test.2026.1",
        "pub_date": "2026-06-18",
        "copyright_holder": "Acme Press",
        "copyright_year": 2026,
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "license_text": "CC BY 4.0",
        "funding": [{"funder": "NSF", "award_id": "ABC-123"}],
    }
    xml = build_jats_xml(SAMPLE, metadata=meta)
    root = _parse(xml)
    am = root.find("./front/article-meta")
    assert am.find("article-id[@pub-id-type='doi']").text == "10.1234/test.2026.1"
    pd = am.find("pub-date")
    assert pd.find("year").text == "2026" and pd.find("month").text == "06"
    perm = am.find("permissions")
    assert perm.find("copyright-holder").text == "Acme Press"
    assert perm.find("copyright-year").text == "2026"
    assert perm.find("license/license-p").text == "CC BY 4.0"
    fg = am.find("funding-group/award-group")
    assert fg.find("funding-source").text == "NSF"
    assert fg.find("award-id").text == "ABC-123"
    # license href is emitted with the xlink namespace declared
    assert 'xlink:href="https://creativecommons.org/licenses/by/4.0/"' in xml


def test_structured_authors_with_orcid_and_corresponding():
    authors = [
        {"surname": "Smith", "given_names": "Jane A.",
         "orcid": "0000-0002-1825-0097", "corresponding": True,
         "email": "jane@example.edu"},
        {"name": "Wei Chen"},
    ]
    root = _parse(build_jats_xml(["Title Only Paper", "Introduction", "Body."],
                                 authors=authors))
    contribs = root.findall("./front/article-meta/contrib-group/contrib")
    assert len(contribs) == 2
    assert contribs[0].get("corresp") == "yes"
    assert contribs[0].find("contrib-id[@contrib-id-type='orcid']").text.endswith("0000-0002-1825-0097")
    assert contribs[0].find("./name/surname").text == "Smith"
    assert contribs[0].find("email").text == "jane@example.edu"
    # full-name fallback: surname = last word
    assert contribs[1].find("./name/surname").text == "Chen"


def test_metadata_is_optional():
    # building without metadata still works and stays valid
    ok, issues = validate_jats(build_jats_xml(SAMPLE))
    assert ok and issues == []
    root = _parse(build_jats_xml(SAMPLE))
    assert root.find("./front/article-meta/permissions") is None
    assert root.find("./front/article-meta/pub-date") is None
