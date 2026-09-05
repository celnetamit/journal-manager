"""Character-level science formatting: species italics, formulas, sub/superscripts.

`docxmodel` has always read `italic`, `superscript` and `subscript` for every run — its
own docstring names species italics as a reason it exists — and until now nothing used
any of it. Three separate remarks from the editorial team turned out to be this one
gap: `Musa paradisiaca` not italic, `λmax` with a full-size "max", `FeCl3` with a
full-size 3.

**Detection is the whole risk, and it is not solvable from text alone.** Three
approaches were measured against 200 real manuscripts before this file was written:

* bare `Genus species` — 15,688 hits, led by "This study", "Kevlar fiber", "Breast
  cancer". Unusable at any threshold.
* a Latin-ending filter on the epithet — precise enough, but it drops `Cassia
  fistula`, `Glycyrrhiza glabra`, `Foeniculum vulgare`, `C. jejuni`. Under half the
  real ones survive.
* document frequency, on the theory that English words are common and epithets rare —
  fails on medical English: "spondylosis" appears in 0.3% of manuscripts and
  "paradisiaca" in 0.5%.

So this module does what real tools do: it carries a list. Not all of taxonomy — only
the genera these journals publish about, which is a few hundred names. Anything outside
the list is simply not reported, and that is the right way round: a missed species
costs an editor nothing, and a false "this is not italic" on `(Mild walking)` teaches
them to ignore the panel.

Nothing here rewrites italics. A wrong italic is worse than a missing one, and the
redline carries tracked *text* changes, not tracked formatting. Species and markers are
reported; only formulas are corrected, because a subscript digit is a character and
travels as text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

#: Genera these journals actually publish about — microbiology, medicinal and crop
#: plants, model organisms — plus the ones the corpus itself turned up (Pichia,
#: Aegilops, Podophyllum, Bryophyllum, Saccharomyces, Aspergillus, Escherichia).
#: Lowercase; matching is case-insensitive on the genus but the shape is checked.
SPECIES_GENERA = frozenset("""
    escherichia salmonella staphylococcus streptococcus pseudomonas klebsiella
    bacillus lactobacillus clostridium mycobacterium enterococcus acinetobacter
    campylobacter helicobacter listeria shigella vibrio proteus serratia
    xanthomonas rhizobium azotobacter agrobacterium erwinia ralstonia
    saccharomyces candida aspergillus penicillium fusarium trichoderma rhizopus
    alternaria colletotrichum cryptococcus pichia rhodotorula mucor botrytis
    chlorella spirulina scenedesmus chlamydomonas nannochloropsis dunaliella
    arabidopsis oryza triticum zea hordeum sorghum glycine cicer vigna phaseolus
    pisum lens brassica gossypium helianthus arachis solanum capsicum lycopersicon
    cucumis cucurbita daucus allium spinacia lactuca aegilops avena secale
    musa mangifera citrus punica psidium carica ananas vitis malus prunus ficus
    phoenix cocos elaeis camellia coffea theobroma piper curcuma zingiber
    azadirachta ocimum withania asparagus tinospora terminalia emblica phyllanthus
    aloe cassia senna glycyrrhiza foeniculum trigonella coriandrum cuminum
    boerhavia sida rubia moringa holarrhena randia pluchea podophyllum berberis
    bryophyllum eichhornia pontederia acacia eucalyptus tectona dalbergia
    bambusa saccharum jatropha ricinus linum sesamum brassicaceae
    caenorhabditis drosophila danio mus rattus xenopus gallus bombyx apis
    anopheles aedes culex tribolium spodoptera helicoverpa nilaparvata
    homo pan macaca sus bos capra ovis canis felis oryctolagus
    eragrostis macrotyloma cyperus madhuca ocimum plectranthus centella bacopa
    datura atropa nicotiana physalis cestrum lycianthes petunia
    andrographis adhatoda gymnema momordica trigonella eclipta bauhinia
    """.split())

#: The abbreviated form is only trusted for organisms that are near-universally written
#: that way. `S. and` and `D. holders` are author initials in a reference list, and the
#: corpus has 255 abbreviation-shaped hits of which most are exactly that.
COMMON_ABBREVIATED = frozenset({
    "e. coli", "s. aureus", "s. cerevisiae", "p. aeruginosa", "b. subtilis",
    "c. albicans", "k. pneumoniae", "s. typhi", "s. typhimurium", "l. monocytogenes",
    "h. pylori", "c. difficile", "m. tuberculosis", "a. niger", "a. flavus",
    "p. falciparum", "c. elegans", "d. melanogaster", "a. thaliana",
})

#: Formulas worth correcting. Curated rather than pattern-matched: a general
#: `[A-Z][a-z]?\d` pattern over the corpus returns `D8`, `M4`, `R2` and `M0` —
#: diffractometer models, an R-squared and a modulus — 950 hits of which most are not
#: chemistry at all. These are unambiguous.
_FORMULA_SOURCES = (
    "H2O", "H2O2", "CO2", "CO", "O2", "N2", "H2", "NH3", "CH4", "SO2", "NO2", "N2O",
    "H2SO4", "HNO3", "HCl", "H3PO4", "NaOH", "KOH", "NaCl", "KCl", "CaCl2", "MgCl2",
    "FeCl2", "FeCl3", "AlCl3", "ZnCl2", "CuCl2", "NaHCO3", "Na2CO3", "CaCO3",
    "NaNO3", "KNO3", "AgNO3", "CuSO4", "ZnSO4", "FeSO4", "MgSO4", "Na2SO4", "K2SO4",
    "Fe2O3", "Fe3O4", "Al2O3", "TiO2", "SiO2", "ZnO", "MgO", "CuO", "MnO2", "CeO2",
    "ZrO2", "SnO2", "WO3", "V2O5", "Cr2O3", "NiO", "Co3O4", "CdS", "ZnS",
    "C6H12O6", "C2H5OH", "CH3OH", "CH3COOH", "NaBH4", "KMnO4", "K2Cr2O7",
)

_SUBSCRIPT_DIGITS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _subscripted(formula: str) -> str:
    """`FeCl3` -> `FeCl₃`. Only digits move; element letters are untouched."""
    return "".join(ch.translate(_SUBSCRIPT_DIGITS) if ch.isdigit() else ch
                   for ch in formula)


#: {plain form: subscripted form}, longest first so `Fe3O4` is matched before `Fe3`.
#: Only formulas that actually contain a digit: `ZnO`, `NiO` and `CO` have nothing to
#: subscript, and reporting them said "written with full-size digits" about a string
#: with no digits in it.
FORMULAS = {f: _subscripted(f) for f in
            sorted((x for x in _FORMULA_SOURCES if any(c.isdigit() for c in x)),
                   key=len, reverse=True)}

_FORMULA_RE = re.compile(
    r"(?<![A-Za-z0-9₀-₉])(" + "|".join(re.escape(f) for f in FORMULAS) +
    r")(?![A-Za-z0-9₀-₉])")

#: Variables written with the qualifier on the line. An allowlist, not a pattern, and
#: it took two attempts to accept that. `[CTKEIRV]` plus one letter matched `Is`, `Ca`,
#: `Ra`, `Km`, `Kg`, `Ed`. Requiring three letters still matched **`Amin`** — a
#: person's name, and a common one in these manuscripts — plus `Jobs`, an ordinary
#: word, and `Teff`, which is a grain. Any capital letter followed by a real qualifier
#: spells an English word or a name often enough that only naming the variables works.
_SUBSCRIPT_VARIABLES = (
    "λmax", "λmin", "λem", "λex", "Λmax",
    "Cmax", "Cmin", "Vmax", "Vmin", "Tmax", "Tmin", "Emax", "Emin",
    "Imax", "Imin", "Rmax", "Rmin", "Pmax", "Pmin", "Dmax", "Dmin",
    "qmax", "qexp", "qcalc", "Qmax", "kobs", "Kobs", "tmax", "Ymax",
)
_SUBSCRIPT_MARKER = re.compile(
    r"(?<![A-Za-z])(" + "|".join(sorted(_SUBSCRIPT_VARIABLES, key=len, reverse=True))
    + r")(?![A-Za-z])")

#: `cm-1`, `mg L-1`, `min-1` — a negative exponent set on the line. The base must be a
#: real unit: `[a-zA-Z]{1,4}` matched `Fig-3`, `Vol-1`, `HFS-3` and `of -1`.
_EXPONENT_UNITS = ("cm", "mm", "nm", "µm", "um", "m", "km", "g", "mg", "kg", "µg",
                   "ng", "L", "mL", "µL", "l", "ml", "ha", "min", "s", "h", "mol",
                   "mmol", "K", "W", "J", "Pa", "N", "mgg", "gg", "day", "yr")
_EXPONENT_MARKER = re.compile(
    r"(?<![A-Za-z0-9-])(" + "|".join(sorted(_EXPONENT_UNITS, key=len, reverse=True))
    + r")\s?-\s?([123])\b")


#: Words that follow a genus without being its epithet. `Rhizobium strain`,
#: `Aegilops species` and `Triticum and` were 4 of the first 11 findings; a second
#: pass over the corpus added the plant-part nouns behind `Jatropha oil`,
#: `Jatropha seeds` and `Rhizobium inoculants`.
_NOT_AN_EPITHET = frozenset({
    "species", "spp", "strain", "strains", "genus", "genera", "complex", "isolate",
    "isolates", "culture", "cultures", "and", "was", "were", "has", "had", "sp",
    "population", "populations", "group", "groups", "cells", "growth", "extract",
    "extracts", "oil", "oils", "seed", "seeds", "leaf", "leaves", "root", "roots",
    "stem", "stems", "bark", "fruit", "fruits", "flower", "flowers", "peel", "peels",
    "plant", "plants", "powder", "juice", "pulp", "starch", "biomass", "inoculants",
    "inoculant", "genome", "genomes", "gene", "genes", "protein", "proteins",
    "counts", "count", "colonies", "colony", "biofilm", "infection", "infections",
    # A pharmacognosy review turned up `Solanum steroid` — the genus followed by the
    # compound class it yields. Same shape as the plant-part nouns above.
    "steroid", "steroids", "alkaloid", "alkaloids", "glycoside", "glycosides",
    "saponin", "saponins", "flavonoid", "flavonoids", "derivative", "derivatives",
    "compound", "compounds", "content", "family", "fruits", "tuber", "tubers",
    "nightshade", "extract", "oil", "based", "rich", "like", "such",
})

#: Endings that make a word English rather than a Latin epithet. `-ans` is absent on
#: purpose — `Caenorhabditis elegans` and `Thiobacillus denitrificans` end that way.
_ENGLISH_ENDING = re.compile(
    r"(?:ed|ing|ant|ants|ent|ents|ive|ness|ment|ments|tion|tions|sion|able|ible)$")


@dataclass
class FormatFinding:
    """One character-level formatting deviation."""
    rule: str
    severity: str
    paragraph: Optional[int]
    message: str
    detail: str = ""
    suggestion: Optional[str] = None

    def __str__(self) -> str:
        where = f"¶{self.paragraph + 1}" if self.paragraph is not None else "document"
        return f"[{self.severity}] {where} {self.rule}: {self.message}"


def find_binomials(text: str, known_genera=SPECIES_GENERA) -> List[tuple]:
    """(start, end, phrase) for every species binomial in `text`.

    Only names whose genus is in the list, plus the abbreviated forms that are
    near-universally written that way. Everything else is left alone on purpose —
    see the module docstring for the three detectors that were measured and rejected.
    """
    out = []
    for m in re.finditer(r"\b([A-Z][a-z]{2,})\s+([a-z]{3,})\b", text):
        if m.group(2) in _NOT_AN_EPITHET or _ENGLISH_ENDING.search(m.group(2)):
            continue
        if m.group(1).lower() in known_genera:
            out.append((m.start(), m.end(), m.group(0)))
    for m in re.finditer(r"\b([A-Z])\.\s?([a-z]{3,})\b", text):
        if f"{m.group(1).lower()}. {m.group(2).lower()}" in COMMON_ABBREVIATED:
            out.append((m.start(), m.end(), m.group(0)))
    return sorted(set(out))


def _spans_are_italic(para, start: int, end: int) -> Optional[bool]:
    """Is the text between `start` and `end` italic? None when the run cannot be found.

    `Para.text` is the concatenation of its runs, so a character offset can be walked
    back to the runs covering it. A binomial split across two runs — which is normal,
    because Word splits runs at every formatting change — must have *both* italic.

    `run.italic is None` counts as **not italic**, and getting that wrong made the
    whole check silently useless: Word only writes `w:i` onto a run that differs from
    its style, so a plain body run says None rather than False. The manuscript that
    raised this had `Musa paradisiaca` at `italic=None` in every one of its fifteen
    paragraphs, and an earlier version of this function read that as "nothing says"
    and reported not one of them.

    The cost is a species inside a style that is italic in its own right — a caption
    style, say — which would be reported wrongly. That is rare, and it is a visible
    wrong finding rather than an invisible missing one.
    """
    pos = 0
    verdicts = []
    for run in para.runs:
        n = len(run.text or "")
        if pos < end and pos + n > start and (run.text or "").strip():
            verdicts.append(run.italic)
        pos += n
    if not verdicts:
        return None
    return all(v is True for v in verdicts)


def check_species_italic(structure) -> List[FormatFinding]:
    """Species binomials that are not italic.

    Reported, never rewritten. Italicising the wrong phrase puts a visible error into
    the author's manuscript, and the redline carries tracked text changes rather than
    tracked formatting, so an automatic change here would also be invisible in Word's
    review pane — a silent edit, which is the one thing this tool must not do.
    """
    out: List[FormatFinding] = []
    seen: set = set()
    for p in structure.paragraphs:
        text = p.text
        if not text.strip():
            continue
        for start, end, phrase in find_binomials(text):
            if _spans_are_italic(p, start, end) is False and phrase not in seen:
                seen.add(phrase)
                out.append(FormatFinding(
                    "format.species-italic", "warning", p.index,
                    f"{phrase!r} is a species name and is not italic; house sets "
                    f"binomials in italic",
                    text[max(0, start - 30):end + 30].strip(),
                    phrase))
    return out


def check_formula_subscripts(structure) -> List[FormatFinding]:
    """Chemical formulas whose digits are full-size."""
    out: List[FormatFinding] = []
    seen: set = set()
    for p in structure.paragraphs:
        for m in _FORMULA_RE.finditer(p.text):
            plain = m.group(1)
            if plain in seen:
                continue
            seen.add(plain)
            out.append(FormatFinding(
                "format.formula-subscript", "info", p.index,
                f"{plain} is written with full-size digits; house sets formula "
                f"subscripts",
                p.text[max(0, m.start() - 30):m.end() + 30].strip(),
                FORMULAS[plain]))
    return out


def check_subscript_markers(structure) -> List[FormatFinding]:
    """Qualifiers and exponents set on the line — `λmax`, `cm-1`.

    Reported only. Unicode has subscript digits, which is why formulas can be
    corrected, but its subscript *letters* (ₘₐₓ) are missing several of the alphabet
    and render badly in most manuscript fonts. Turning `λmax` into `λₘₐₓ` would look
    worse than leaving it, so the editor is told and applies real subscript.
    """
    out: List[FormatFinding] = []
    seen: set = set()
    for p in structure.paragraphs:
        text = p.text
        if not text.strip():
            continue
        # A run already marked sub/superscript is correctly set; the plain text of the
        # paragraph cannot show that, so paragraphs that use them are checked run-wise.
        marked = any(r.subscript or r.superscript for r in p.runs)
        for rx, rule, what in ((_SUBSCRIPT_MARKER, "format.subscript", "subscript"),
                               (_EXPONENT_MARKER, "format.superscript", "superscript")):
            for m in rx.finditer(text):
                token = m.group(0)
                if token in seen or (marked and rx is _SUBSCRIPT_MARKER):
                    continue
                seen.add(token)
                tail = m.group(2) if rx.groups > 1 else re.sub(r"^[^a-z]*", "", token)
                out.append(FormatFinding(
                    rule, "info", p.index,
                    f"{token!r} appears to need a {what} on {tail!r}",
                    text[max(0, m.start() - 30):m.end() + 30].strip()))
    return out


def check_all(structure) -> List[FormatFinding]:
    """The checks that are *reported*, in report order.

    Formulas are deliberately absent. `enforce_formula_subscripts` corrects them in
    the edited text, so they arrive in the redline as a tracked change the editor
    accepts or rejects — and listing them here as well would put "FeCl3 is written
    with full-size digits" in the House Style panel beside a redline where it already
    reads FeCl₃. Report what is not fixed; fix what is not reported.
    `check_formula_subscripts` stays available for tests and for measuring the corpus.
    """
    return check_species_italic(structure) + check_subscript_markers(structure)


def enforce_formula_subscripts(paras: List[str]) -> List[str]:
    """`FeCl3` -> `FeCl₃`, on the edited text, so it lands in the redline.

    Safe as a text change in a way the other two are not: a subscript digit is a
    character, and the manuscripts already use them — the paper that raised this had
    `Fe₃O₄` correctly subscripted in its abstract and `FeCl3` and `Fe3O4` plain in the
    methods, one document with both conventions.

    Only the curated list is touched. A general `[A-Z][a-z]?\\d` pattern over the
    corpus returns 950 hits led by `D8`, `M4` and `R2` — a diffractometer, a modulus
    and an R-squared.
    """
    return [_FORMULA_RE.sub(lambda m: FORMULAS[m.group(1)], p) if p else p
            for p in paras]


# --------------------------------------------------------------- language variant

#: US -> UK for the forms that are unambiguous. Deliberately narrow, because several
#: of the obvious-looking pairs are traps:
#:
#: * `analyses` is the plural of "analysis" in **both** variants — "the analyses
#:   showed" is correct US English, and mapping it to "analyzes" turns a noun into a
#:   verb.
#: * `program` is correct UK spelling for a computer program; only a broadcast or a
#:   scheme is a "programme".
#: * `practice`/`practise` and `licence`/`license` are a noun/verb distinction in UK
#:   English, not a variant pair.
#: * `modeling`/`modelling` is safe; `traveled`/`travelled` is safe; `focused` has one
#:   `s` in both and `focussed` is a UK variant of a UK word, so it is left out.
_US_TO_UK = {
    "analyze": "analyse", "analyzed": "analysed", "analyzing": "analysing",
    "characterize": "characterise", "characterized": "characterised",
    "characterizing": "characterising", "characterization": "characterisation",
    "utilize": "utilise", "utilized": "utilised", "utilizing": "utilising",
    "utilization": "utilisation",
    "optimize": "optimise", "optimized": "optimised", "optimizing": "optimising",
    "optimization": "optimisation",
    "standardize": "standardise", "standardized": "standardised",
    "sterilize": "sterilise", "sterilized": "sterilised",
    "organize": "organise", "organized": "organised", "organization": "organisation",
    "recognize": "recognise", "recognized": "recognised",
    "minimize": "minimise", "minimized": "minimised",
    "maximize": "maximise", "maximized": "maximised",
    "summarize": "summarise", "summarized": "summarised",
    "emphasize": "emphasise", "emphasized": "emphasised",
    "stabilize": "stabilise", "stabilized": "stabilised",
    "polymerization": "polymerisation", "crystallization": "crystallisation",
    "color": "colour", "colors": "colours", "colored": "coloured",
    "colorless": "colourless", "behavior": "behaviour", "behaviors": "behaviours",
    "behavioral": "behavioural", "labor": "labour", "favor": "favour",
    "favorable": "favourable", "flavor": "flavour", "odor": "odour",
    "vapor": "vapour", "vapors": "vapours",
    "center": "centre", "centers": "centres", "centered": "centred",
    "fiber": "fibre", "fibers": "fibres", "liter": "litre", "liters": "litres",
    "aluminum": "aluminium", "sulfur": "sulphur", "sulfate": "sulphate",
    "sulfates": "sulphates", "sulfide": "sulphide", "sulfuric": "sulphuric",
    "modeling": "modelling", "modeled": "modelled",
    "labeling": "labelling", "labeled": "labelled", "labels": "labels",
    "catalog": "catalogue", "catalogs": "catalogues",
    "gray": "grey", "aging": "ageing",
}
_UK_TO_US = {uk: us for us, uk in _US_TO_UK.items() if uk != us}


def _match_case(source: str, replacement: str) -> str:
    """Keep the original capitalisation. `Behaviour` at the start of a sentence must
    not come back as `behavior`."""
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _variant_map(lang_type: str):
    low = (lang_type or "").lower()
    if "british" in low or "uk" in low.split():
        return _US_TO_UK
    if "american" in low or "us" in low.split():
        return _UK_TO_US
    return None


def enforce_language_variant(paras: List[str], lang_type: str) -> List[str]:
    """Spell the manuscript in the variant the job was set to.

    The copyedit is told the variant and applies it unevenly. On a real job set to US
    English it converted `analysing` to `analyzing` and left all five occurrences of
    `behaviour` — one document, both variants, which is what the editorial team
    reported.

    This is a re-spelling of an author's words, which `proofread`'s own docstring
    warns against, and it is right here for two reasons the warning does not cover:
    the editor explicitly chose the variant, and it lands in the redline as a tracked
    change they can reject. Silent is the part that was forbidden, not automatic.
    """
    table = _variant_map(lang_type)
    if not table:
        return paras
    pattern = re.compile(r"\b(" + "|".join(sorted(table, key=len, reverse=True))
                         + r")\b", re.I)

    def swap(m):
        word = m.group(0)
        target = table.get(word.lower())
        return _match_case(word, target) if target else word

    return [pattern.sub(swap, p) if p else p for p in paras]

# ------------------------------------------------- formulas beyond the curated list

#: Every element symbol. This is what separates a formula from a sample label, and it
#: is why the general `[A-Z][a-z]?\d` pattern was rejected earlier: over the corpus it
#: returned 950 hits led by `D8`, `M4`, `R2` and `M0` — a diffractometer, a modulus and
#: an R-squared. None of `D`, `M` or `R` is an element symbol, so a parser that insists
#: every symbol be real throws all four out without needing a list of exceptions.
_ELEMENTS = frozenset("""
    H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn
    Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La
    Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po
    At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg
    Cn Nh Fl Mc Lv Ts Og
    """.split())

#: A single element with a count is a formula only for the diatomics. Without this,
#: `B12` (the vitamin) and `K3` (half of a hexacyanoferrate written across brackets)
#: would be subscripted, and neither should be.
_DIATOMIC = frozenset({"H2", "N2", "O2", "F2", "Cl2", "Br2", "I2", "O3"})

#: No element in a real formula carries a count this large. The corpus supplied the
#: reason: `OV2640` is a camera sensor, `FB1035` a specimen code and `BF00581071` a
#: reference number, and all three parse cleanly as element symbols. `C6H12O6` needs
#: 12, so that is the ceiling.
_MAX_COUNT = 12

#: Tokens that parse as chemistry and are not. Kept deliberately tiny — one entry,
#: earned by measurement. `I2C` is the two-wire bus, written I²C with a *super*script
#: when it is written properly at all, and it appeared 15 times across the corpus.
#: Every entry was found by running the parser over 298 real manuscripts and reading
#: all 89 tokens it proposed to change. These five are structurally indistinguishable
#: from formulas — `HV3` has the shape of `NO3` — so no rule can separate them and
#: naming them is the honest option. `I2C` is the two-wire bus (written I²C, with a
#: *super*script), `V2I` is vehicle-to-infrastructure, `PI3K` and `P2Y12` are proteins,
#: `HV3` is a Vickers hardness.
_NOT_A_FORMULA = frozenset({"I2C", "SI6", "PI3K", "V2I", "P2Y12", "HV3", "HN6", "UP2"})

_FORMULA_TOKEN = re.compile(r"(?<![A-Za-z0-9₀-₉.])([A-Z][A-Za-z0-9]{1,14})(?![A-Za-z0-9₀-₉])")
_SYMBOL_RUN = re.compile(r"([A-Z][a-z]?)(\d*)")


def parses_as_formula(token: str) -> bool:
    """Does `token` read end to end as element symbols with counts?

    `FeCl3` -> Fe, Cl3. `M4` -> `M` is not an element, so no. The digit requirement
    keeps ordinary words out: `Bacon` happens to spell Ba-C-O-N and is rejected because
    nothing in it is a count.
    """
    if not any(ch.isdigit() for ch in token) or token in _NOT_A_FORMULA:
        return False
    pos, symbols, counts = 0, [], []
    for m in _SYMBOL_RUN.finditer(token):
        if m.start() != pos:
            return False                      # a gap means something did not parse
        if m.group(1) not in _ELEMENTS:
            return False
        if m.group(2) and (int(m.group(2)) > _MAX_COUNT
                           or m.group(2).startswith("0")):
            return False    # no formula writes a leading zero; `V11NU02` is a code
        symbols.append(m.group(1))
        counts.append(m.group(2))
        pos = m.end()
    if pos != len(token) or not symbols:
        return False
    # A count of 1 is never written in chemistry — H2O, not H2O1 — so a token that
    # carries one is a label. `SSW1` was in the corpus.
    if any(c == "1" for c in counts):
        return False
    # Three or more single-letter symbols with the only count on the last is the shape
    # of a specimen code (`SSW2`, `SCF70`), not of a formula: real ones carry their
    # counts inside (`H2SO4`), and the short ones have fewer than three symbols
    # (`CO2`).
    if (len(symbols) >= 3 and all(len(x) == 1 for x in symbols)
            and not any(counts[:-1]) and counts[-1]):
        return False
    # One element and a count is only a formula for the diatomics; `B12` and `K3` are
    # a vitamin and a fragment.
    return len(set(symbols)) >= 2 or token in _DIATOMIC


def enforce_all_formula_subscripts(paras: List[str]) -> List[str]:
    """`NH2CSNH2` -> `NH₂CSNH₂`, for any formula, not only the curated ones.

    The curated list covers the sixty formulas that turn up constantly; a manuscript
    on the catalytic oxidation of thiourea is made of the ones it does not. Every
    token is parsed against the periodic table instead, so `D8`, `M4` and `R2` are
    rejected because `D`, `M` and `R` are not element symbols — which is the same
    result the curated list gave, reached by a rule rather than by enumeration.
    """
    def fix(text: str) -> str:
        return _FORMULA_TOKEN.sub(
            lambda m: _subscripted(m.group(1)) if parses_as_formula(m.group(1))
            else m.group(1), text)
    return [fix(p) if p else p for p in paras]


# ------------------------------------------------- symbols no model gets right

#: `∆` is U+2206 INCREMENT, a mathematical operator. The thermodynamic quantity is
#: `Δ`, U+0394 GREEK CAPITAL DELTA. They look identical in most fonts and sort,
#: search and typeset differently.
#:
#: A three-model comparison on the same paragraph settled that this is not a model
#: problem. On `(∆H#) = 41.49 KJ/mol, (∆s#) = -51.754 J/mol K`:
#:   gemini-2.5-pro    fixed `∆s`->`∆S`, left the increment sign
#:   claude-sonnet-4.5 fixed the increment sign, left `Δs` lowercase
#:   gemini-2.5-flash  fixed neither
#: Each was also inconsistent with itself between chunks — all three wrote `ΔS#`
#: correctly one paragraph earlier. No model choice fixes it; a rule does.
_INCREMENT_SIGN = "\u2206"
_GREEK_DELTA = "\u0394"

#: Entropy is capital S, enthalpy capital H, Gibbs energy capital G. Only corrected
#: where the symbol is unambiguously a thermodynamic quantity — directly after a
#: delta and directly before the activation marker or a closing bracket — so an
#: ordinary `Δs` meaning "a small change in s" is never touched.
_THERMO_CASE = re.compile(f"([{_GREEK_DELTA}{_INCREMENT_SIGN}])([shgcfeu])(?=[#\u2021)\u00b0])")


def enforce_science_symbols(paras: List[str]) -> List[str]:
    """`∆s#` -> `ΔS#`. The increment sign becomes a Greek delta, and the quantity
    after it takes its proper capital."""
    def fix(text: str) -> str:
        text = text.replace(_INCREMENT_SIGN, _GREEK_DELTA)
        return _THERMO_CASE.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    return [fix(p) if p else p for p in paras]


# --- SI unit capitalisation ----------------------------------------------------

#: Unit symbols whose miscapitalisation has no valid alternative reading, so they can
#: be corrected without asking. `kilo` is always a lowercase `k`, and `pascal` always
#: a capital `P`.
_UNIT_CASE = {
    "KJ": "kJ", "Kj": "kJ",
    "KG": "kg", "Kg": "kg",
    "KM": "km", "Km": "km",
    "KHZ": "kHz", "KHz": "kHz", "Khz": "kHz",
    "MHZ": "MHz", "Mhz": "MHz",
    "GHZ": "GHz", "Ghz": "GHz",
    "HZ": "Hz",
    "Kpa": "kPa", "KPA": "kPa",
    "Mpa": "MPa", "MPA": "MPa",
    "Gpa": "GPa", "GPA": "GPa",
}

#: **Do not add these.** Every one of them is a valid SI symbol in its own right, and
#: "correcting" it changes the quantity by a factor of a billion:
#:
#:   Mg  megagram   — not milligram
#:   ML  megalitre  — not millilitre
#:   Nm  newton-metre — not nanometre
#:   Mm  megametre  — not millimetre
#:
#: This list exists so that nobody later completes the table above from a style guide
#: and silently rewrites `4.2 Nm` of torque into `4.2 nm`. A wrong unit that *looks*
#: plausible is worse than one that looks odd, because nothing downstream will query
#: it. If these ever need handling, they get a query for a human, never a rewrite.
_AMBIGUOUS_UNITS = ("Mg", "ML", "Nm", "Mm", "Min", "Cm", "Dm")

#: Only in a measurement context — a number, optional space, then the symbol. Without
#: this, `KG` inside an initialism and `Hz` in a surname both get rewritten.
_UNIT_CASE_RE = re.compile(
    r"(?<=\d)(\s*)(" + "|".join(sorted(_UNIT_CASE, key=len, reverse=True)) + r")\b"
)


def enforce_unit_case(paras: List[str]) -> List[str]:
    """`5 KJ` -> `5 kJ`. Only where the symbol follows a number, and only for symbols
    that cannot mean anything else.

    Measured across 396 corpus manuscripts before building it: wrong unit case appears
    10 times in 10 manuscripts, so this is a small rule by design. It exists because it
    was the one consistency check where a cheaper model measurably lagged, and a thing
    a machine can guarantee should not be left to one.
    """
    def fix(text: str) -> str:
        return _UNIT_CASE_RE.sub(
            lambda m: m.group(1) + _UNIT_CASE[m.group(2)], text)
    return [fix(p) if p else p for p in paras]


# --- duplicated symbols left behind by a broken conversion ---------------------

#: The artifact this repairs, seen 13 times in one real manuscript (job 45): a symbol
#: immediately repeated in two notations with nothing between them —
#:
#:     LSTM increased R2R^2 to 0.924
#:     coefficient of determination was R2=0.946R^2=0.946
#:     Damage R2R2                                   (a table header)
#:
#: It is not an author's typo. Thirteen occurrences with one consistent shape, in a
#: document that *also* contains clean `R²` in four other places, is the signature of a
#: find-and-replace that inserted where it meant to replace: the old form and the new
#: one both survived.
#:
#: Why this is a rule and not left to the model: on that manuscript the model repaired
#: 2 of the 13 and left 11, because each chunk is judged separately and nothing made the
#: decision once. That outcome is worse than doing nothing — before, every occurrence was
#: identically wrong and a reader could see a conversion had failed; after, two say `R²`
#: and eleven say `R2R^2`, which reads as two different quantities.
_DUPLICATED_SYMBOL = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<base>[A-Za-z]{1,3})\^?(?P<exp>\d)(?P<tail>\s*=\s*-?\d+(?:\.\d+)?)?"
    r"(?P=base)\^?(?P=exp)(?P<tail2>\s*=\s*-?\d+(?:\.\d+)?)?"
    r"(?![A-Za-z0-9])"
)

_SUPERSCRIPT_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def _tails_agree(tail: Optional[str], tail2: Optional[str]) -> bool:
    """Both halves must carry the same value, or neither may carry one.

    `R2=0.946R^2=0.946` is the artifact. `R2=0.9R2=0.8` is two different numbers and
    must be left alone for a person to read — collapsing it would delete a result.
    """
    if tail is None and tail2 is None:
        return True
    if tail is None or tail2 is None:
        return False
    return tail.replace(" ", "") == tail2.replace(" ", "")


def collapse_duplicated_symbols(
    paras: List[str],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Remove a symbol duplicated by a failed conversion. Returns the text and queries.

    The exponent is rendered as a real superscript only where the document itself gives
    evidence for it: a caret in one of the two halves, or the same base and digit
    already written as `R²` somewhere else in the manuscript. Without that evidence the
    duplication is still collapsed — that part is certain — but the notation is left
    exactly as the author had it.

    That restraint is the whole design. `CO2CO2` collapsed to `CO²` would be a new
    error, not a fix: in a chemical formula the 2 is a subscript, and a rule that
    guesses would turn a repair into corruption. Deciding sub versus superscript is
    `enforce_formula_subscripts`'s job and it is left to it.

    Every collapse is reported as a query. A silent repair of something this odd is
    worse than a visible one: the editor should know the source was damaged, because
    whatever damaged it probably damaged something else too.
    """
    joined = "\n".join(p or "" for p in paras)
    # Which base+digit pairs does the document already write as a true superscript?
    superscripted = {
        (m.group(1), m.group(2))
        for m in re.finditer(r"(?<![A-Za-z0-9])([A-Za-z]{1,3})([⁰¹²³⁴⁵⁶⁷⁸⁹])", joined)
    }
    superscripted = {
        (base, sup.translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")))
        for base, sup in superscripted
    }

    queries: List[Dict[str, Any]] = []
    out: List[str] = []

    for index, para in enumerate(paras):
        if not para:
            out.append(para)
            continue

        def repair(m: "re.Match[str]") -> str:
            if not _tails_agree(m.group("tail"), m.group("tail2")):
                return m.group(0)
            base, exp = m.group("base"), m.group("exp")
            caret = "^" in m.group(0)
            if caret or (base, exp) in superscripted:
                symbol = base + exp.translate(_SUPERSCRIPT_DIGITS)
            else:
                symbol = base + exp
            return symbol + (m.group("tail") or "")

        fixed = _DUPLICATED_SYMBOL.sub(repair, para)
        if fixed != para:
            for m in _DUPLICATED_SYMBOL.finditer(para):
                if _tails_agree(m.group("tail"), m.group("tail2")):
                    queries.append({
                        "index": index,
                        "severity": "warning",
                        "message": (
                            f"The source repeated '{m.group(0).strip()}' — the same "
                            f"symbol written twice with nothing between it, which a "
                            f"failed find-and-replace leaves behind. It has been "
                            f"collapsed to a single symbol. Check the rest of the "
                            f"document for the same damage."
                        ),
                    })
        out.append(fixed)

    return out, queries


def detect_language_variant(paras: List[str]) -> Tuple[Optional[str], Dict[str, int]]:
    """Which variant the author actually wrote in, from the whole manuscript.

    The editorial team's rule, and it is the right one: the variant should follow what
    the author mostly used, not a dropdown someone set before reading the paper. A
    manuscript written throughout in British English and processed as US English comes
    back with every `behaviour` rewritten — dozens of tracked changes that are not
    corrections, burying the ones that are.

    Counting is the whole method: how many words appear in their UK-only spelling
    against their US-only spelling, across every paragraph. Deciding this by eye on the
    abstract alone would be sampling the one section most likely to have been rewritten
    by someone else.

    Returns `(None, counts)` when there is not enough evidence — under five variant
    words, or a margin under 60% — so the caller keeps whatever was chosen explicitly.
    A near-even split is a genuinely mixed manuscript, and picking a side by one word
    would rewrite half of it on the strength of that word.
    """
    text = "\n".join(p or "" for p in paras)
    uk = us = 0
    for word in re.findall(r"[A-Za-z]{3,}", text):
        low = word.lower()
        if low in _UK_TO_US:
            uk += 1
        elif low in _US_TO_UK:
            us += 1

    counts = {"uk": uk, "us": us}
    total = uk + us
    if total < 5:
        return None, counts
    share = max(uk, us) / total
    if share < 0.6:
        return None, counts
    return ("UK English" if uk > us else "US English"), counts
