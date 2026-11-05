"""Completeness check: FOOD MATCH only accepts finished research papers.

A finished paper has, in this order:

  1. Results and Discussion -- with real content (data values such as means,
     percentages and p-values, or a substantial written discussion),
  2. Conclusions,
  3. Recommendations,
  4. References -- followed by actual citations.

A proposal stops after the Methodology, so it fails at step 1.

The check looks for these parts by their headings, not by chapter number,
because schools number them differently (Results is Chapter III in a 4-chapter
thesis and Chapter IV in a 5-chapter one). It skips Table of Contents entries
(a heading followed by its page number), because a proposal's Table of Contents
may already list "Results and Discussion", "Conclusions" and so on. It also
tolerates headings whose letters the PDF reader split apart ("RESUL TS").

Scanned copies and photos have (almost) no text to check. They are reported as
"unverified" so each upload page can decide what to do with them.
"""
import re
from io import BytesIO

# PDF pages of real (typed) theses carry 120-175 words each; a scanned copy
# carries almost none.
SCANNED_WORDS_PER_PAGE = 40

MIN_RESULTS_DATA_VALUES = 10   # e.g. "4.72", "48.5%", "p = 0.034"
MIN_RESULTS_WORDS_WITH_DATA = 200
MIN_RESULTS_WORDS_WITHOUT_DATA = 800  # written (qualitative) results
MIN_WORDS_AFTER_HEADING = 40
MIN_CITATION_YEARS = 4

RESULTS_LABEL = "Results and Discussion (with your data)"
CONCLUSIONS_LABEL = "Conclusions"
RECOMMENDATIONS_LABEL = "Recommendations"
REFERENCES_LABEL = "References"


def _letters(word):
    """An upper-case word whose letters the PDF reader may have split ("RESUL TS")."""
    return r"\s?".join(re.escape(char) for char in word)


_AND = rf"(?:{_letters('AND')}|&)"
_CHAPTER = r"(?:CHAPTER|Chapter)\s+(?:[IVX]+|\d{1,2})\s*[.:\-]?\s*"

_RESULTS = re.compile(
    rf"(?:{_CHAPTER})?(?:"
    rf"{_letters('RESULT')}(?:\s?S)?\s*{_AND}\s*{_letters('DISCUSSION')}(?:\s?S)?"
    rf"|{_letters('FINDINGS')}\s*{_AND}\s*{_letters('DISCUSSION')}(?:\s?S)?"
    rf"|{_letters('PRESENTATION')}\s*,?\s*{_letters('ANALYSIS')}\s*,?\s*(?:{_AND}\s*)?{_letters('INTERPRETATION')}"
    rf"|{_letters('PRESENTATION')}\s*(?:,|{_AND})\s*{_letters('ANALYSIS')}"
    rf"|{_letters('ANALYSIS')}\s*(?:,|{_AND})\s*{_letters('INTERPRETATION')}"
    rf")"
    rf"|{_CHAPTER}(?:{_letters('RESULTS')}\b|Results\b(?:\s+(?:and|&)\s+Discussions?)?"
    rf"|Presentation,?\s+(?:Analysis,?\s+)?(?:and\s+)?(?:Interpretation|Analysis)|Findings\s+and\s+Discussions?)"
)
_CONCLUSIONS = re.compile(rf"{_letters('CONCLUSION')}(?:\s?S)?|\bConclusions\b")
_RECOMMENDATIONS = re.compile(rf"{_letters('RECOMMENDATION')}(?:\s?S)?|\bRecommendations\b")
_REFERENCES = re.compile(
    rf"{_letters('REFERENCE')}(?:\s?S)?|{_letters('BIBLIOGRAPHY')}|{_letters('LITERATURE')}\s+{_letters('CITED')}"
    r"|\b(?:References?|Bibliography|Literature\s+Cited|Works\s+Cited)\b"
)
# A Table of Contents entry: the heading is followed by its page number
# ("REFERENCES ..... 71"), unlike a numbered list item ("1. The study ...").
_TOC_PAGE_NUMBER = re.compile(r"\s*(?:\.{2,}\s*)?\d{1,3}(?![\d.)]|,\d)")
_DATA_VALUE = re.compile(r"(?<![\w.])\d+\.\d+(?![\w.])|\b\d+(?:\.\d+)?\s?%|\bp\s*[<=>]\s*0?\.\d+", re.I)
_YEAR = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b")


def _headings(pattern, text):
    for match in pattern.finditer(text):
        if not _TOC_PAGE_NUMBER.match(text, match.end()):
            yield match


def _docx_text_in_order(file_bytes):
    """Paragraphs and table cells of a Word file, in the order they appear."""
    from docx import Document
    from docx.oxml.ns import qn

    document = Document(BytesIO(file_bytes))
    parts = []
    for block in document.element.body.iterchildren():
        if block.tag == qn("w:p"):
            parts.append("".join(node.text or "" for node in block.iter(qn("w:t"))))
        elif block.tag == qn("w:tbl"):
            for cell_text in block.iter(qn("w:t")):
                parts.append(cell_text.text or "")
    return "\n".join(part.strip() for part in parts if part and part.strip())


def read_text_layer(uploaded_file):
    """The text a file itself contains (no OCR), plus its page count for PDFs."""
    name = (getattr(uploaded_file, "name", "") or "").lower()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    data = uploaded_file.read()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    try:
        if name.endswith(".pdf"):
            from PyPDF2 import PdfReader

            reader = PdfReader(BytesIO(data))
            text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
            return {"kind": "pdf", "text": text, "pages": len(reader.pages)}
        if name.endswith(".docx"):
            return {"kind": "docx", "text": _docx_text_in_order(data), "pages": None}
        if name.endswith(".txt"):
            return {"kind": "txt", "text": data.decode("utf-8", errors="ignore"), "pages": None}
    except Exception:
        return {"kind": "unreadable", "text": "", "pages": None}
    return {"kind": "image", "text": "", "pages": None}


def assess_completeness(text):
    """Decide from the text alone whether a paper is finished.

    Returns {"status": "complete" | "incomplete", "missing": [labels]}.
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    conclusion_starts = [m.start() for m in _headings(_CONCLUSIONS, text)]
    reference_starts = [m.start() for m in _headings(_REFERENCES, text)]

    # The real Results heading is the one followed by actual results; the
    # section ends where the Conclusions (or References) begin.
    results_start = None
    best_score = -1
    for match in _headings(_RESULTS, text):
        stop = min([p for p in conclusion_starts + reference_starts if p > match.end()] or [len(text)])
        section_words = text[match.end():stop].split()[:8000]
        values = len(_DATA_VALUE.findall(" ".join(section_words)))
        has_results = (values >= MIN_RESULTS_DATA_VALUES and len(section_words) >= MIN_RESULTS_WORDS_WITH_DATA) \
            or len(section_words) >= MIN_RESULTS_WORDS_WITHOUT_DATA
        score = values * 10 + len(section_words) // 100
        if has_results and score > best_score:
            results_start, best_score = match.start(), score

    if results_start is None:
        # Without results, nothing after them can count either.
        return {"status": "incomplete",
                "missing": [RESULTS_LABEL, CONCLUSIONS_LABEL, RECOMMENDATIONS_LABEL, REFERENCES_LABEL]}

    def written_after_results(pattern):
        for match in _headings(pattern, text):
            if match.start() > results_start and \
                    len(text[match.end():match.end() + 1500].split()) >= MIN_WORDS_AFTER_HEADING:
                return True
        return False

    def references_after_results():
        for match in _headings(_REFERENCES, text):
            if match.start() > results_start and \
                    len(_YEAR.findall(text[match.end():match.end() + 2500])) >= MIN_CITATION_YEARS:
                return True
        return False

    missing = []
    if not written_after_results(_CONCLUSIONS):
        missing.append(CONCLUSIONS_LABEL)
    if not written_after_results(_RECOMMENDATIONS):
        missing.append(RECOMMENDATIONS_LABEL)
    if not references_after_results():
        missing.append(REFERENCES_LABEL)
    return {"status": "complete" if not missing else "incomplete", "missing": missing}


def assess_document(layer):
    """Like assess_completeness, but first rules out scanned copies and photos,
    which have no text to check ("unverified")."""
    kind, text, pages = layer.get("kind"), layer.get("text") or "", layer.get("pages")
    if kind in ("image", "unreadable"):
        return {"status": "unverified", "missing": []}
    if kind == "pdf" and pages and len(text.split()) / pages < SCANNED_WORDS_PER_PAGE:
        return {"status": "unverified", "missing": []}
    return assess_completeness(text)


def check_uploaded_completeness(uploaded_file):
    return assess_document(read_text_layer(uploaded_file))


def incomplete_research_error(assessment):
    return (
        "This research paper looks unfinished, and only complete research is accepted. "
        "A complete paper has Results and Discussion, Conclusions, Recommendations, and References. "
        f"Missing: {', '.join(assessment.get('missing') or [])}."
    )


UNVERIFIED_RESEARCH_ERROR = (
    "This file can't be checked for completeness because it is a scanned copy or a photo. "
    "Please upload the original PDF or Word file of your complete research paper."
)
