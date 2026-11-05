import os
import re
import unicodedata
from io import BytesIO

from django.utils import timezone

try:
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine_similarity
except ImportError:
    ENGLISH_STOP_WORDS = frozenset([
        "a", "about", "above", "across", "after", "afterwards", "again", "against",
        "all", "almost", "alone", "along", "already", "also", "although", "always",
        "am", "among", "amongst", "amoungst", "amount", "an", "and", "another",
        "any", "anyhow", "anyone", "anything", "anyway", "anywhere", "are",
        "around", "as", "at", "back", "be", "became", "because", "become",
        "becomes", "becoming", "been", "before", "beforehand", "behind", "being",
        "below", "beside", "besides", "between", "beyond", "bill", "both",
        "bottom", "but", "by", "call", "can", "cannot", "cant", "co", "con",
        "could", "couldnt", "cry", "de", "describe", "detail", "do", "done",
        "down", "due", "during", "each", "eg", "eight", "either", "eleven", "else",
        "elsewhere", "empty", "enough", "etc", "even", "ever", "every", "everyone",
        "everything", "everywhere", "except", "few", "fifteen", "fify", "fill",
        "find", "fire", "first", "five", "for", "former", "formerly", "forty",
        "found", "four", "from", "front", "full", "further", "get", "give", "go",
        "had", "has", "hasnt", "have", "he", "hence", "her", "here", "hereafter",
        "hereby", "herein", "hereupon", "hers", "herself", "him", "himself", "his",
        "how", "however", "hundred", "ie", "if", "in", "inc", "indeed",
        "interest", "into", "is", "it", "its", "itself", "keep", "last", "latter",
        "latterly", "least", "less", "ltd", "made", "many", "may", "me",
        "meanwhile", "might", "mill", "mine", "more", "moreover", "most", "mostly",
        "move", "much", "must", "my", "myself", "name", "namely", "neither",
        "never", "nevertheless", "next", "nine", "no", "nobody", "none", "noone",
        "nor", "not", "nothing", "now", "nowhere", "of", "off", "often", "on",
        "once", "one", "only", "onto", "or", "other", "others", "otherwise", "our",
        "ours", "ourselves", "out", "over", "own", "part", "per", "perhaps",
        "please", "put", "rather", "re", "same", "see", "seem", "seemed",
        "seeming", "seems", "serious", "several", "she", "should", "show", "side",
        "since", "sincere", "six", "sixty", "so", "some", "somehow", "someone",
        "something", "sometime", "sometimes", "somewhere", "still", "such",
        "system", "take", "ten", "than", "that", "the", "their", "them",
        "themselves", "then", "thence", "there", "thereafter", "thereby",
        "therefore", "therein", "thereupon", "these", "they", "thick", "thin",
        "third", "this", "those", "though", "three", "through", "throughout",
        "thru", "thus", "to", "together", "too", "top", "toward", "towards",
        "twelve", "twenty", "two", "un", "under", "until", "up", "upon", "us",
        "very", "via", "was", "we", "well", "were", "what", "whatever", "when",
        "whence", "whenever", "where", "whereafter", "whereas", "whereby",
        "wherein", "whereupon", "wherever", "whether", "which", "while", "whither",
        "who", "whoever", "whole", "whom", "whose", "why", "will", "with",
        "within", "without", "would", "yet", "you", "your", "yours", "yourself",
        "yourselves",
    ])
    TfidfVectorizer = None
    sklearn_cosine_similarity = None


def greet_user(name):
    return f"Hello, {name}! Welcome to FOOD HUB!"


def _simple_stem(token):
    """Lightweight stemming to normalize common word forms without extra dependencies."""
    if len(token) <= 4:
        return token

    for suffix in ("ingly", "edly", "ing", "ed", "ies", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            if suffix == "ies":
                return token[:-3] + "y"
            return token[: -len(suffix)]

    return token


def normalize_text(*parts):
    """Lowercase, remove punctuation, remove stop words, tokenize, and normalize text."""
    raw_text = " ".join(part.strip() for part in parts if part and part.strip())
    lowered_text = raw_text.lower()
    cleaned_text = re.sub(r"[^a-z0-9\s]", " ", lowered_text)
    tokens = cleaned_text.split()
    normalized_tokens = [
        _simple_stem(token)
        for token in tokens
        if token and token not in ENGLISH_STOP_WORDS
    ]
    return " ".join(normalized_tokens)


# Similarity levels: Low 0–30%, Moderate 31–49%, High 50% and up.
# (A student's upload is blocked above the Low range.)
SIMILARITY_LOW_MAX = 30
SIMILARITY_HIGH_MIN = 50
# When the AI model compared a study, TF-IDF alone only counts at this level or
# above (a near-exact copy). Chosen from the November 2026 evaluation: with it,
# no different study was flagged (precision 100%, F1 0.873 vs 0.820 before).
TFIDF_NEAR_COPY = 80
SIMILARITY_LEVELS = {
    "low": ("Low Similarity", "Original"),
    "moderate": ("Moderate Similarity", "Related Study"),
    "high": ("High Similarity", "Possible Duplication"),
}
SIMILARITY_RANGES = {
    "low": f"0–{SIMILARITY_LOW_MAX}%",
    "moderate": f"{SIMILARITY_LOW_MAX + 1}–{SIMILARITY_HIGH_MIN - 1}%",
    "high": f"{SIMILARITY_HIGH_MIN}–100%",
}


def similarity_level_for_percent(score_percent):
    if score_percent <= SIMILARITY_LOW_MAX:
        return "low"
    if score_percent < SIMILARITY_HIGH_MIN:
        return "moderate"
    return "high"


def categorize_similarity_score(score):
    score_percent = round(float(score) * 100, 2)
    level = similarity_level_for_percent(score_percent)
    label, summary = SIMILARITY_LEVELS[level]
    return {
        "score_percent": score_percent,
        "similarity_label": label,
        "similarity_summary": summary,
        "similarity_level": level,
    }


# Food research weighting: the ingredients/process section is the single most
# telling signal, title and abstract are supporting signals, and the rest of the
# paper (introduction, review of literature, results, discussion, etc.) still
# counts so the whole document is part of the result. Weights must sum to 1.0.
SIMILARITY_WEIGHTS = {
    "ingredients": 0.30,  # materials/ingredients & procedure section specifically
    "general": 0.30,      # the rest of the paper — everything not covered above
    "title": 0.20,
    "abstract": 0.20,
}

_ABSTRACT_HEADINGS = ("abstract", "executive summary", "research summary", "summary", "synopsis", "overview")
_NEXT_SECTION_HEADINGS = (
    "keywords", "key words", "introduction", "chapter 1", "chapter i",
    "background of the study", "table of contents", "acknowledgment",
    "acknowledgement", "list of tables", "list of figures", "dedication",
    "statement of the problem",
)
_INGREDIENTS_HEADINGS = (
    "materials and methods", "materials & methods", "material and methods",
    "methodology", "research methodology", "research method", "methods",
    "method", "procedure", "procedures", "preparation", "ingredients",
    "experimental procedure", "product development", "research design and methods",
    "process flow", "materials",
)
_INGREDIENTS_STOP_HEADINGS = (
    "results", "results and discussion", "discussion", "conclusion",
    "conclusions", "recommendation", "recommendations", "chapter 3",
    "chapter iii", "chapter 4", "chapter iv", "chapter 5", "chapter v",
    "references", "bibliography", "appendix", "appendices",
    "list of tables", "list of figures",
)
_TITLE_PAGE_NOISE = (
    "republic of the philippines", "college of", "department of", "university",
    "institute of", "school of", "in partial fulfillment", "presented to",
    "a thesis", "a research", "a capstone", "a study proposal", "requirements for",
    "degree of", "bachelor of", "bachelor in", "master of", "master in",
    "submitted by", "submitted to",
    "school year", "s.y.", "adviser", "panel", "researchers", "proponents",
    "approval sheet", "statement of authorship", "certification", "declaration",
    "originality of the study", "table of contents", "list of tables",
    "list of figures", "list of appendices", "dedication", "acknowledgment",
    "acknowledgement", "chapter", "appendix", "appendices", "references",
    "bibliography", "curriculum vitae", "biographical sketch",
)


def _extract_section(lines, lowered, heading_set, stop_set, max_chars, max_heading_len=40):
    """Find a heading line matching `heading_set`, then collect the lines after it
    up to the next heading in `stop_set` (or `max_chars`). Returns
    (section_text, heading_line_index, end_line_index) — the indices bound the
    slice `[heading_line_index:end_line_index]` so a caller can excise it, or
    (\"\", None, None) if no matching heading was found."""
    start = None
    for i, low in enumerate(lowered):
        heading = low.strip(" :.-")
        if len(low) <= max_heading_len and heading in heading_set:
            start = i
            break
    if start is None:
        return "", None, None

    collected = []
    total_len = 0
    end = len(lines)
    for j in range(start + 1, len(lines)):
        heading = lines[j].lower().strip(" :.-")
        if any(heading == h or heading.startswith(h) for h in stop_set):
            end = j
            break
        collected.append(lines[j])
        total_len += len(lines[j])
        if total_len >= max_chars:
            end = j + 1
            break

    return " ".join(collected).strip()[:max_chars], start, end


def extract_food_research_sections(raw_text, max_abstract_chars=1500, max_ingredients_chars=2500):
    """Best-effort guess of a food-research document's Title, Abstract, and
    Ingredients/Procedure section from its raw extracted text (line breaks
    preserved). Returns (title, abstract, ingredients_text, general_text) where
    `general_text` is everything else in the document (so the whole paper still
    counts toward the result, not just the pieces above).

    This is a heuristic over unstructured text — headings vary a lot between
    schools/formats, so any of these can come back empty, and callers must
    handle that gracefully (see `rank_similar_documents_weighted`)."""
    lines = [line.strip() for line in (raw_text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return "", "", "", ""

    lowered = [line.lower() for line in lines]

    # No weak "grab any long lines" fallback here on purpose — if there's no
    # detectable Abstract heading, leave it blank rather than guess at
    # something that might just be front matter or an unrelated paragraph;
    # the person reviewing the auto-fill should type the real abstract in.
    abstract, abstract_start, _abstract_end = _extract_section(
        lines, lowered, _ABSTRACT_HEADINGS, _NEXT_SECTION_HEADINGS, max_abstract_chars
    )

    ingredients_text, ing_start, ing_end = _extract_section(
        lines, lowered, _INGREDIENTS_HEADINGS, _INGREDIENTS_STOP_HEADINGS, max_ingredients_chars
    )

    # "General" = everything except the lines identified as the ingredients/
    # procedure section (title and abstract text are left in — TF-IDF handles a
    # little overlap fine, and each is weighted separately anyway).
    if ing_start is not None:
        general_lines = lines[:ing_start] + lines[ing_end:]
    else:
        general_lines = lines
    general_text = " ".join(general_lines)

    # ---- Title: prefer an ALL CAPS block near the top (common on PH thesis title
    # pages), skipping known title-page boilerplate lines. The search is bounded to
    # before the Abstract / Table of Contents / Chapter 1 — past that point, chapter
    # and section headings ("REVIEW OF RELATED LITERATURE", etc.) are often longer,
    # ALL-CAPS lines that would otherwise out-compete the real title. ----
    def is_titleish(line):
        # Food research titles often carry a scientific/binomial name in
        # parentheses ("... TOMATO (Solanum lycopersicum) CHIPS ...") which is
        # conventionally mixed-case even when the rest of an ALL-CAPS title
        # isn't. Ignore parenthetical content when judging the line so a
        # title mentioning one doesn't fail this check.
        line_for_ratio = re.sub(r"\([^)]*\)", "", line)
        letters = [c for c in line_for_ratio if c.isalpha()]
        if len(letters) < 8:
            return False
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        return upper_ratio > 0.8 and 10 <= len(line) <= 200

    # Blank lines are kept here (not stripped, unlike `lines` above) — a blank
    # line is itself a real section break in a title page (e.g. the title,
    # then a gap, then the author names, then a gap, then the date), and
    # without that signal, consecutive ALL-CAPS blocks separated only by a
    # blank line (a title followed by a list of author names, say) would
    # otherwise get glued into one "candidate", picking the wrong text.
    raw_lines = [line.strip() for line in (raw_text or "").splitlines()][:200]
    candidates = []
    buf = []

    def _flush():
        if buf:
            candidates.append(" ".join(buf))
            buf.clear()

    for line in raw_lines:
        low = line.lower()
        if not line:
            _flush()
            continue
        heading = low.strip(" :.-")
        if (heading in _ABSTRACT_HEADINGS and len(low) <= 40) or any(
            marker in low for marker in ("table of contents", "chapter 1", "chapter i", "chapter one")
        ):
            break
        if any(noise in low for noise in _TITLE_PAGE_NOISE):
            _flush()
            continue
        if is_titleish(line):
            buf.append(line)
        else:
            _flush()
    _flush()

    candidates = [c for c in candidates if 10 <= len(c) <= 220]
    # The first surviving ALL-CAPS block (after institutional boilerplate is
    # filtered out) is the title — on a real title page it always comes
    # before the author list, thesis-type line, and date, so picking by
    # position is far more reliable than picking the longest block (which
    # would sometimes grab a multi-line author list instead, since it can
    # add up to more characters than a short title).
    # No weak "first long-enough line" fallback here on purpose — if no
    # ALL-CAPS title block was found, leave it blank rather than guess at
    # some arbitrary line; the person reviewing the auto-fill should type
    # the real title in.
    title = candidates[0] if candidates else ""

    return title.strip(), abstract.strip(), ingredients_text.strip(), general_text.strip()


_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
_AUTHOR_LEAD_PATTERN = re.compile(
    r"(?i)^(?:"
    r"prepared\s+and\s+submitted\s+by|presented\s+by|submitted\s+by|prepared\s+by|conducted\s+by|"
    r"the\s+researchers?|researchers?|the\s+proponents?|proponents?|names?\s+of\s+researchers?|by"
    r")\s*[:\-]?\s*(.*)$"
)
# Word-boundary match on purpose (not a plain substring check) so a heading
# like "Thesis Advisory Committee" doesn't false-positive as an adviser label
# just because "advisory" contains "adviser"/"advisor" as a prefix.
_ADVISER_MARKER_PATTERN = re.compile(r"\badvis(?:ers?|ors?)\b", re.IGNORECASE)
# "Mrs. X, our dedicated thesis adviser, ..." — common Acknowledgement-section
# phrasing where the name comes first, as an appositive before the label.
_ADVISER_APPOSITIVE_PATTERN = re.compile(
    r"(?i)^(.*?),\s*(?:our|the|my|a)?\s*(?:dedicated|beloved|esteemed|respected|kind|loving)?\s*"
    r"(?:thesis|research|capstone)?\s*advis(?:er|or)\b"
)
_NAME_CONNECTORS = {"de", "dela", "del", "van", "der", "los", "la", "y", "san", "sta", "mc", "mac", "di"}


def _clean_name_spacing(text):
    # PDF text extraction sometimes inserts a stray space before a hyphen in a
    # hyphenated surname ("PAY -AO" instead of "PAY-AO") — rejoin those so the
    # name doesn't get split into a bogus extra "word" (here, or downstream
    # wherever the cleaned name ends up stored/displayed).
    return re.sub(r"\s+-\s*", "-", (text or "").strip())


def _looks_like_person_name(text):
    text = _clean_name_spacing(text)
    if not text or len(text) > 60:
        return False
    words = text.split()
    if not (2 <= len(words) <= 6):
        return False
    for word in words:
        core = word.strip(".,")
        if not core or any(ch.isdigit() for ch in core):
            return False
        if core.lower() not in _NAME_CONNECTORS and not core[0].isupper():
            return False
    return True


def extract_research_metadata_from_text(raw_text):
    """Best-effort guess of Title, Abstract, Authors, Adviser, Published Month,
    and Published Year from a research document's raw extracted text. Every
    field can come back empty (or `authors` an empty list) — this is a heuristic
    over unstructured text meant to pre-fill a form for a human to review and
    correct, never to be trusted blindly or relied on to block submission."""
    title, abstract, _ingredients, _general = extract_food_research_sections(raw_text)

    lines = [line.strip() for line in (raw_text or "").splitlines()]
    lines = [line for line in lines if line]
    lowered = [line.lower() for line in lines]

    # ---- Authors: a "By:" / "Presented by" / "Researchers:" lead-in near the
    # top. The name(s) can be on that SAME line ("By: Juan Dela Cruz") or on the
    # line(s) right after it ("By:\nJuan Dela Cruz\nMaria Santos"). ----
    def _extract_names_from_line(line):
        found = []
        for piece in re.split(r"\s*(?:,|;|&|\band\b)\s*", line, flags=re.IGNORECASE):
            piece = piece.strip(" .")
            if piece and _looks_like_person_name(piece):
                found.append(_clean_name_spacing(piece))
        return found

    authors = []
    for i, line in enumerate(lines[:80]):
        match = _AUTHOR_LEAD_PATTERN.match(line.strip())
        if not match:
            continue
        inline_rest = match.group(1).strip(" :.-")
        if inline_rest:
            authors.extend(_extract_names_from_line(inline_rest))
        for j in range(i + 1, min(i + 6, len(lines))):
            candidate = lines[j]
            low2 = candidate.lower()
            # Deliberately NOT looking ahead at the next line to guess "this is
            # actually the adviser, not another author" (e.g. because a bare
            # "Thesis Adviser" label follows shortly after) — that guess isn't
            # reliable enough to risk silently dropping a real author, and the
            # dedicated adviser search below finds the adviser on its own
            # regardless. Worst case here, the adviser's name ends up as an
            # extra (removable) chip, which is far cheaper than losing a name.
            if any(noise in low2 for noise in _TITLE_PAGE_NOISE) or _ADVISER_MARKER_PATTERN.search(
                candidate
            ):
                break
            found_names = _extract_names_from_line(candidate)
            if found_names:
                authors.extend(found_names)
            elif authors:
                break
        if authors:
            break

    # ---- Fallback: many title pages have no "By:"/"Researchers:" label at
    # all — just one name per line, in ALL CAPS, sitting right after the title
    # (and before the college/adviser/publication-date lines). Find the
    # longest contiguous run of name-like lines in the front-matter region. ----
    if not authors:
        boundary = None
        for idx, low in enumerate(lowered):
            heading = low.strip(" :.-")
            if heading in _ABSTRACT_HEADINGS and len(low) <= 40:
                boundary = idx
                break
            if any(marker in low for marker in ("table of contents", "chapter 1", "chapter i", "chapter one")):
                boundary = idx if boundary is None else min(boundary, idx)
                break
        search_window = lines[:boundary] if boundary is not None else lines[:80]
        search_window = search_window[:80]

        best_run, current_run = [], []
        for line in search_window:
            low = line.lower()
            is_noise = line.strip() == title.strip() or any(noise in low for noise in _TITLE_PAGE_NOISE)
            if is_noise:
                if len(current_run) > len(best_run):
                    best_run = current_run
                current_run = []
                continue
            if _looks_like_person_name(line):
                current_run.append(_clean_name_spacing(line))
            else:
                if len(current_run) > len(best_run):
                    best_run = current_run
                current_run = []
        if len(current_run) > len(best_run):
            best_run = current_run
        if best_run:
            authors = best_run

    # ---- Adviser: a line mentioning "adviser"/"advisor". The name can be on
    # that same line — as a lead-in ("Adviser: Dr. X"), as a trailing label
    # ("Dr. X, Adviser"), or as an appositive naming them first, common in an
    # Acknowledgement section ("Mrs. X, our dedicated thesis adviser, ...") —
    # or, when the marker is a standalone label ("Thesis Adviser" on its own
    # line), on the line right before it. ----
    adviser = ""
    for idx, line in enumerate(lines[:150]):
        if not _ADVISER_MARKER_PATTERN.search(line):
            continue
        candidate = ""
        appositive = _ADVISER_APPOSITIVE_PATTERN.match(line)
        if appositive:
            candidate = appositive.group(1).strip(" ,.-")
        if not candidate:
            after_colon = line.split(":", 1)
            candidate = after_colon[1].strip() if len(after_colon) == 2 and after_colon[1].strip() else ""
        if not candidate:
            candidate = re.sub(r"(?i)\b(thesis|research|capstone)?\s*advis(?:ers?|ors?)\b", "", line).strip(" ,.-")
        if not candidate and idx > 0:
            prev_line = lines[idx - 1].strip()
            prev_low = prev_line.lower()
            # Guard the "name on the line above a bare label" guess: if that
            # line is actually the title or another front-matter/heading line
            # (e.g. the label sits right after the title with no name between
            # them), it's not an adviser's name — leave it blank rather than
            # hand back something clearly wrong.
            is_title = bool(title) and prev_low == title.strip().lower()
            is_noise = any(noise in prev_low for noise in _TITLE_PAGE_NOISE)
            if not is_title and not is_noise:
                candidate = prev_line
        if candidate and _looks_like_person_name(candidate):
            adviser = candidate
            break

    # ---- Published Month/Year: a "Month YYYY" pattern near the front matter. ----
    published_month = ""
    published_year = None
    month_pattern = re.compile(r"\b(" + "|".join(_MONTH_NAMES) + r")\s+((?:19|20)\d{2})\b", re.IGNORECASE)
    for line in lines[:150]:
        match = month_pattern.search(line)
        if match:
            published_month = match.group(1).capitalize()
            published_year = int(match.group(2))
            break
    if published_year is None:
        year_pattern = re.compile(r"\b((?:19|20)\d{2})\b")
        for line in lines[:150]:
            match = year_pattern.search(line)
            if match:
                published_year = int(match.group(1))
                break

    # ---- Title sanity check: the ALL-CAPS-block heuristic above assumes the
    # title itself is in ALL CAPS, which isn't always true — some title pages
    # print the title in normal Title Case but the author names in ALL CAPS
    # for emphasis, which then wins that heuristic instead. If the detected
    # "title" is really just the author list, it's wrong — clear it rather
    # than take another guess; the person reviewing the auto-fill should type
    # the real title in instead of getting handed something incorrect. ----
    if authors and title:
        author_set = {name.strip().lower() for name in authors}
        title_words = {w.strip() for w in title.lower().split() if w.strip()}
        if title.strip().lower() in author_set or (title_words and title_words <= set(" ".join(authors).lower().split())):
            title = ""

    return {
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "adviser": adviser,
        "published_month": published_month,
        "published_year": published_year,
    }


def rank_similar_documents_weighted(query_fields, records, threshold=0.0, weights=None, query_semantic=None):
    """Compare a query document against repository records using four separately
    weighted TF-IDF/cosine components, then combine them into one score:

        score = 0.30 * ingredients_similarity  (materials/ingredients & procedure)
              + 0.30 * general_similarity       (the rest of the paper)
              + 0.20 * title_similarity
              + 0.20 * abstract_similarity

    `query_fields` is {"ingredients": str, "general": str, "title": str,
    "abstract": str}. Each record should expose "ingredients_text",
    "general_text" (falls back to "content_text"/"text"), "title", and
    "abstract".

    If the query is missing one of these (most often "ingredients", since
    pinpointing that section by heading is the least reliable guess — or title/
    abstract when detection fails), that component's weight is proportionally
    redistributed onto whichever components the query does have, so a missed
    heading never silently caps every score below 100%. A record that has no
    abstract, or that has a document but no clearly-detected ingredients
    section, still scores 0 on that one component — that is real signal, not
    a data-availability artifact. But a record with no document at all (a
    repository entry added with only a title/abstract/keywords, never an
    uploaded file) has no way to score on "ingredients" or "the rest of the
    paper" through no fault of its own; for that record only, that 60% is
    redistributed onto title/abstract instead of being scored as 0% twice
    (flagged in its result as "metadata_only").

    The final score is never lower than a plain whole-document similarity
    (ingredients + general combined, i.e. the paper's full body text): splitting
    the body into an ingredients section and "everything else" is itself a
    best-effort guess (it can misplace the section boundary) and a bad guess
    there must never hide a real match; it can only add precision on top.
    """
    from .semantic import match as semantic_match
    from .semantic import template_masks as semantic_template_masks

    weights = weights or SIMILARITY_WEIGHTS
    query_ingredients = normalize_text(query_fields.get("ingredients", ""))
    query_general = normalize_text(query_fields.get("general", ""))
    query_title = normalize_text(query_fields.get("title", ""))
    query_abstract = normalize_text(query_fields.get("abstract", ""))
    query_whole = normalize_text(f"{query_fields.get('ingredients', '')} {query_fields.get('general', '')}")

    if not query_whole.strip():
        return [], {}

    field_query_values = {
        "ingredients": query_ingredients,
        "general": query_general,
        "title": query_title,
        "abstract": query_abstract,
    }

    active_weights = {}
    total_weight = 0.0
    for key, value in field_query_values.items():
        if value.strip():
            active_weights[key] = weights.get(key, 0.0)
            total_weight += weights.get(key, 0.0)

    if total_weight <= 0:
        return [], {}

    effective_weights = {key: value / total_weight for key, value in active_weights.items()}

    prepared_records = []
    for record in records:
        ingredients_text = record.get("ingredients_text", "")
        general_text = record.get("general_text", record.get("content_text", record.get("text", "")))
        # Explicit flag set at record-construction time — NOT inferred from
        # ingredients_text/general_text, since keywords alone (routed into
        # "ingredients_text") would otherwise make a document-less metadata
        # entry look like it has a document.
        has_document = record.get("has_document")
        if has_document is None:
            has_document = bool(general_text.strip())
        prepared_records.append(
            {
                "record": record,
                "ingredients": normalize_text(ingredients_text),
                "general": normalize_text(general_text),
                "title": normalize_text(record.get("title", "")),
                "abstract": normalize_text(record.get("abstract", "")),
                "whole": normalize_text(f"{ingredients_text} {general_text}"),
                "has_document": bool(has_document),
            }
        )

    if not any(item["whole"].strip() for item in prepared_records):
        return [], {}

    def field_scores(query_value, field_key):
        if not query_value.strip() or not any(item[field_key].strip() for item in prepared_records):
            return [0.0] * len(prepared_records)
        corpus = [query_value, *[item[field_key] for item in prepared_records]]
        vectorizer = TfidfVectorizer(stop_words="english")
        try:
            matrix = vectorizer.fit_transform(corpus)
        except ValueError:
            return [0.0] * len(prepared_records)
        return sklearn_cosine_similarity(matrix[0:1], matrix[1:]).flatten().tolist()

    scores_by_field = {}
    for key in ("ingredients", "general", "title", "abstract"):
        if key in effective_weights:
            scores_by_field[key] = field_scores(field_query_values[key], key)
    whole_scores = field_scores(query_whole, "whole")

    ranked_results = []
    # Template text shared by many studies is ignored by the AI comparison.
    template_masks = semantic_template_masks([item["record"] for item in prepared_records]) if query_semantic is not None else None
    for idx, item in enumerate(prepared_records):
        component_scores = {key: scores[idx] for key, scores in scores_by_field.items()}

        # A record with no document body at all (a repository entry added with
        # only a title/abstract/keywords, never an uploaded file) has no real
        # signal for "ingredients" or "the rest of the paper" through no fault
        # of its own — that is a data-availability gap, not a dissimilarity
        # signal, unlike the query-side redistribution above. Shift that 60%
        # onto title/abstract for this record only, so a metadata-only entry
        # that matches on title and abstract isn't buried under two 0% scores.
        record_has_document = item["has_document"]
        if record_has_document:
            record_weights = effective_weights
        else:
            record_weights = {k: w for k, w in effective_weights.items() if k in ("title", "abstract")}
            record_total = sum(record_weights.values())
            record_weights = (
                {k: w / record_total for k, w in record_weights.items()} if record_total > 0 else effective_weights
            )

        blended = sum(record_weights.get(key, 0.0) * value for key, value in component_scores.items())
        combined = max(blended, whole_scores[idx])
        # Machine-learning meaning match (core/semantic.py), when both sides have
        # meaning vectors; it replaces TF-IDF as the deciding score (see below).
        tfidf_combined = combined
        semantic_score = None
        semantic_pair = None
        semantic_section_words = 0
        record_vectors = item["record"].get("semantic_vectors")
        if query_semantic is not None and record_vectors is not None and len(record_vectors):
            meaning = semantic_match(query_semantic, record_vectors, template_masks[idx])
            semantic_score = round(meaning["score"], 2)
            semantic_pair = meaning["pair"]
            semantic_section_words = meaning["section_words"]
            # The AI meaning score decides. TF-IDF only counts when it shows a
            # near-exact copy: studies on the same topic share a lot of
            # vocabulary (TF-IDF up to 67% for different studies), which the AI
            # model doesn't mistake for copying. Without AI vectors, TF-IDF decides.
            combined = max(meaning["score"] / 100, tfidf_combined if tfidf_combined * 100 >= TFIDF_NEAR_COPY else 0.0)
        if combined >= threshold:
            similarity_category = categorize_similarity_score(combined)
            ranked_results.append(
                {
                    **item["record"],
                    "score": combined,
                    "ingredients_score": round(component_scores.get("ingredients", 0.0) * 100, 2),
                    "general_score": round(component_scores.get("general", 0.0) * 100, 2),
                    "title_score": round(component_scores.get("title", 0.0) * 100, 2),
                    "abstract_score": round(component_scores.get("abstract", 0.0) * 100, 2),
                    # The weight actually applied to each component for THIS match —
                    # equal to the nominal 30/30/20/20 split unless redistributed
                    # (missing query field, or this record has no document on file).
                    # Shown alongside the raw scores above so the basis is never
                    # misread as "this score should have been capped by 20%".
                    "ingredients_weight": round(record_weights.get("ingredients", 0.0) * 100, 1),
                    "general_weight": round(record_weights.get("general", 0.0) * 100, 1),
                    "title_weight": round(record_weights.get("title", 0.0) * 100, 1),
                    "abstract_weight": round(record_weights.get("abstract", 0.0) * 100, 1),
                    "metadata_only": not record_has_document,
                    "semantic_score": semantic_score,
                    "semantic_pair": semantic_pair,
                    "semantic_section_words": semantic_section_words,
                    "tfidf_score": round(tfidf_combined * 100, 2),
                    **similarity_category,
                }
            )

    ranked_results.sort(key=lambda entry: entry["score"], reverse=True)
    return ranked_results, effective_weights


# --- "What matched" explanation for one result ------------------------------
# The scores above say HOW similar each part is; these helpers show WHAT is
# similar: the key terms both texts share and the closest pair of passages.
_MATCH_WORD_RE = re.compile(r"[A-Za-z0-9]+|[^A-Za-z0-9]+")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?;])\s+")
MATCH_TERMS_LIMIT = 8
MATCH_PASSAGE_MAX_CHARS = 320
MATCH_PASSAGE_MIN_SCORE = 0.15
# Sentences considered per side when looking for the closest passage pair; keeps
# a full-paper comparison to a bounded (cap x cap) similarity matrix.
MATCH_SENTENCE_CAP = 600

MATCH_SECTIONS = (
    ("title", "Title"),
    ("ingredients", "Ingredients & Procedure"),
    ("abstract", "Abstract"),
    ("general", "Rest of Paper"),
)


# Section headings and words every research paper uses; sharing them says
# nothing about two studies being alike, so they are never shown as matches.
_MATCH_NOISE_WORDS = frozenset(
    _simple_stem(word) for word in (
        "abstract", "introduction", "chapter", "results", "result", "discussion", "conclusion",
        "conclusions", "recommendation", "recommendations", "materials", "methods", "method",
        "methodology", "procedure", "procedures", "ingredients", "references", "keywords",
        "table", "figure", "appendix", "study", "studies", "research", "researcher", "researchers",
        "respondents", "paper", "data", "using", "used", "showed", "shows",
    )
)


def _match_stem(word):
    word = word.lower()
    if len(word) < 3 or word.isdigit() or word in ENGLISH_STOP_WORDS:
        return ""
    stem = _simple_stem(word)
    return "" if stem in _MATCH_NOISE_WORDS else stem


def _shared_terms(query_raw, record_raw, limit=MATCH_TERMS_LIMIT):
    """Words both texts use, most frequent in both first, shown as written in the query."""
    query_counts, record_counts, display = {}, {}, {}
    for word in re.findall(r"[A-Za-z0-9]+", query_raw or ""):
        stem = _match_stem(word)
        if stem:
            query_counts[stem] = query_counts.get(stem, 0) + 1
            display.setdefault(stem, {}).setdefault(word.lower(), 0)
            display[stem][word.lower()] += 1
    for word in re.findall(r"[A-Za-z0-9]+", record_raw or ""):
        stem = _match_stem(word)
        if stem:
            record_counts[stem] = record_counts.get(stem, 0) + 1
    shared = [stem for stem in query_counts if stem in record_counts]
    shared.sort(key=lambda stem: (-(query_counts[stem] * record_counts[stem]), stem))
    top = shared[:limit]
    words = [max(display[stem].items(), key=lambda item: item[1])[0] for stem in top]
    return words, set(top)


def _split_passages(raw):
    text = " ".join((raw or "").split())
    passages = []
    for sentence in _SENTENCE_END_RE.split(text):
        words = sentence.split()
        # PDF text often has no punctuation for long stretches; window it.
        for start in range(0, len(words), 45):
            chunk = " ".join(words[start:start + 45])
            if len(chunk) >= 25:
                passages.append(chunk)
    return passages


def _trim_passage(text, stems):
    if len(text) <= MATCH_PASSAGE_MAX_CHARS:
        return text
    # Start the window just before the first shared word so the match stays visible.
    first = 0
    for match in re.finditer(r"[A-Za-z0-9]+", text):
        if _match_stem(match.group()) in stems:
            first = match.start()
            break
    start = max(0, min(first - 60, len(text) - MATCH_PASSAGE_MAX_CHARS))
    if start:
        start = text.find(" ", start) + 1 or start
    end = start + MATCH_PASSAGE_MAX_CHARS
    if end < len(text):
        cut = text.rfind(" ", start, end)
        if cut > start:
            end = cut
    return ("… " if start else "") + text[start:end].strip() + (" …" if end < len(text) else "")


def _highlight_segments(text, stems):
    """Split text into [{"t": str, "m": bool}] runs, m = word shared with the other text."""
    segments = []
    for piece in _MATCH_WORD_RE.findall(text or ""):
        marked = piece[0].isalnum() and _match_stem(piece) in stems
        if segments and segments[-1]["m"] == marked:
            segments[-1]["t"] += piece
        else:
            segments.append({"t": piece, "m": marked})
    return segments


def _closest_passages(query_raw, record_raw, stems):
    def candidates(raw):
        passages = _split_passages(raw)
        focused = [p for p in passages if any(_match_stem(w) in stems for w in re.findall(r"[A-Za-z0-9]+", p))]
        return (focused or passages)[:MATCH_SENTENCE_CAP]

    query_passages = candidates(query_raw)
    record_passages = candidates(record_raw)
    query_norm = [normalize_text(p) for p in query_passages]
    record_norm = [normalize_text(p) for p in record_passages]
    if TfidfVectorizer is None or not any(query_norm) or not any(record_norm):
        return None
    import numpy as np  # ships with scikit-learn, which is present past the check above

    try:
        vectorizer = TfidfVectorizer().fit(query_norm + record_norm)
    except ValueError:
        return None
    query_matrix = vectorizer.transform(query_norm)
    record_matrix = vectorizer.transform(record_norm)
    sims = sklearn_cosine_similarity(query_matrix, record_matrix)
    # Cosine alone favours very short passages (two words in common can look
    # "identical"), so rank pairs by cosine x log(1 + key terms they share).
    key_terms = sorted(stems)

    def key_term_matrix(passages):
        rows = []
        for passage in passages:
            present = {_match_stem(w) for w in re.findall(r"[A-Za-z0-9]+", passage)}
            rows.append([1 if term in present else 0 for term in key_terms])
        return np.array(rows, dtype=float).reshape(len(passages), len(key_terms))

    shared_counts = key_term_matrix(query_passages) @ key_term_matrix(record_passages).T
    ranking = sims * np.log1p(shared_counts) if key_terms else sims
    q_idx, r_idx = divmod(int(ranking.argmax()), ranking.shape[1])
    best = float(sims[q_idx, r_idx])
    if best < MATCH_PASSAGE_MIN_SCORE:
        return None
    return query_passages[q_idx], record_passages[r_idx], best


def explain_similarity_match(query_fields, record):
    """What one repository record has in common with the uploaded file, per part.

    `query_fields` is the raw {"title", "abstract", "ingredients", "general"}
    text detected in the upload; the record supplies raw "title", "abstract",
    "ingredients_raw" and "general_raw". Returns one entry per part with the
    shared key terms and, when close enough, the most similar passage pair
    with the shared words marked.
    """
    record_raw = {
        "title": record.get("title", ""),
        "abstract": record.get("abstract", ""),
        "ingredients": record.get("ingredients_raw", ""),
        "general": record.get("general_raw", ""),
    }
    sections = []
    for key, label in MATCH_SECTIONS:
        query_text = (query_fields.get(key) or "").strip()
        record_text = (record_raw[key] or "").strip()
        entry = {"key": key, "label": label, "available": False, "note": "", "terms": [],
                 "yours": [], "theirs": [], "passage_score": None}
        if not query_text:
            entry["note"] = "This part was not detected in your file."
        elif not record_text:
            entry["note"] = ("No document is on file for this study." if key in ("ingredients", "general")
                             else "This study has no " + label.lower() + " on record.")
        else:
            entry["available"] = True
            words, stems = _shared_terms(query_text, record_text)
            entry["terms"] = words
            if key == "title":
                entry["yours"] = _highlight_segments(_trim_passage(query_text, stems), stems)
                entry["theirs"] = _highlight_segments(_trim_passage(record_text, stems), stems)
            else:
                pair = _closest_passages(query_text, record_text, stems)
                if pair:
                    yours, theirs, score = pair
                    entry["yours"] = _highlight_segments(_trim_passage(yours, stems), stems)
                    entry["theirs"] = _highlight_segments(_trim_passage(theirs, stems), stems)
                    entry["passage_score"] = round(score * 100)
            if not words:
                entry["note"] = "No shared key terms."
        sections.append(entry)
    return sections


def rank_similar_documents(query_text, records, threshold=0.0):
    """Compare one query document against stored records using scikit-learn TF-IDF and cosine similarity."""
    query_document = normalize_text(query_text)
    normalized_records = [
        {
            **record,
            "text": normalize_text(record.get("text", "")),
        }
        for record in records
    ]
    corpus = [query_document, *[record["text"] for record in normalized_records]]

    if not query_document.strip():
        return []

    if not any(record["text"].strip() for record in normalized_records):
        return []

    vectorizer = TfidfVectorizer(stop_words="english")

    try:
        matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        return []

    similarity_scores = sklearn_cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    ranked_results = []

    for record, score in zip(normalized_records, similarity_scores):
        score = float(score)
        if score >= threshold:
            similarity_category = categorize_similarity_score(score)
            ranked_results.append(
                {
                    **record,
                    "score": score,
                    **similarity_category,
                }
            )

    return sorted(ranked_results, key=lambda item: item["score"], reverse=True)


IMAGE_UPLOAD_EXTENSIONS = (".jpg", ".jpeg", ".png")
DOCUMENT_UPLOAD_EXTENSIONS = (".pdf", ".docx", ".txt") + IMAGE_UPLOAD_EXTENSIONS
# Scanned documents can run long; cap OCR at this many pages so one upload
# can't stall a request indefinitely. Pages beyond this are simply not OCR'd.
OCR_MAX_PDF_PAGES = 40

_TESSERACT_CONFIGURED = False


def _configure_tesseract():
    """Point pytesseract at the Tesseract binary. On Linux/macOS this is
    normally already on PATH once the tesseract-ocr package is installed, so
    nothing to do. On Windows, the common UB-Mannheim installer path is used
    as a fallback if it's not already on PATH."""
    global _TESSERACT_CONFIGURED
    if _TESSERACT_CONFIGURED:
        return
    _TESSERACT_CONFIGURED = True
    try:
        import shutil

        import pytesseract

        if shutil.which("tesseract"):
            return
        for candidate in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.exists(candidate):
                pytesseract.pytesseract.tesseract_cmd = candidate
                return
    except ImportError:
        pass


def _ocr_image_bytes(image_bytes):
    """Run OCR on a single image and return its text, or "" if OCR isn't
    available/fails — this must never raise, since it's always a fallback."""
    try:
        import pytesseract
        from PIL import Image

        _configure_tesseract()
        with Image.open(BytesIO(image_bytes)) as image:
            return pytesseract.image_to_string(image).strip()
    except Exception:
        return ""


def _ocr_pdf_bytes(file_bytes, max_pages=OCR_MAX_PDF_PAGES):
    """Rasterize a scanned/image-only PDF page by page and OCR each page.
    Returns "" if PyMuPDF/Tesseract aren't available or the file can't be
    opened — callers already treat an empty result as "nothing extracted"."""
    try:
        import pymupdf as fitz  # PyMuPDF: `pymupdf` is the modern import name
    except ImportError:
        try:
            import fitz  # older PyMuPDF releases only expose this name
        except ImportError:
            return ""
    try:
        pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return ""
    try:
        pages_text = []
        for page_index in range(min(len(pdf_document), max_pages)):
            pixmap = pdf_document[page_index].get_pixmap(dpi=200)
            pages_text.append(_ocr_image_bytes(pixmap.tobytes("png")))
        return "\n\n".join(text for text in pages_text if text.strip())
    finally:
        pdf_document.close()


def extract_text_from_uploaded_file(uploaded_file, use_ocr=True):
    """`use_ocr=False` is used by the Similarity Check flow, which needs to
    stay fast even with hundreds of repository documents and can't afford
    OCR's per-page cost there; a scanned/image file then simply yields little
    or no text (handled as "not readable" by the caller) instead of being
    OCR'd. Other callers (e.g. the metadata auto-fill on upload) keep OCR on."""
    file_name = uploaded_file.name.lower()
    file_bytes = uploaded_file.read()
    uploaded_file.seek(0)

    if file_name.endswith(".pdf"):
        return extract_pdf_text(file_bytes, use_ocr=use_ocr)
    if file_name.endswith(".docx"):
        return extract_docx_text(file_bytes)
    if file_name.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="ignore")
    if file_name.endswith(IMAGE_UPLOAD_EXTENSIONS):
        return _ocr_image_bytes(file_bytes) if use_ocr else ""

    raise ValueError("Unsupported file format. Please upload a PDF, DOCX, TXT, JPG, or PNG file.")


def _pdf_text_pymupdf(file_bytes):
    import pymupdf

    with pymupdf.open(stream=file_bytes, filetype="pdf") as document:
        return "\n\n".join(page.get_text("text").strip() for page in document).strip()


def _pdf_text_pypdf2(file_bytes):
    from PyPDF2 import PdfReader

    reader = PdfReader(BytesIO(file_bytes))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()


def clean_extracted_text(text):
    """Undo PDF layout artifacts: ligatures (ﬁ → fi) and words hyphenated
    across a line break ("bio-\\ndegrade" → "biodegrade")."""
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"(\w)-\n(?=[a-z])", r"\1", text)


def extract_pdf_text(file_bytes, use_ocr=True):
    # PyMuPDF reads thesis PDFs far more cleanly than PyPDF2 (no words split
    # into pieces like "pee ls") and about 10x faster; PyPDF2 is the fallback.
    # Pages are joined with newlines so heading-based detection (title/abstract)
    # can still find line boundaries.
    try:
        text = _pdf_text_pymupdf(file_bytes)
    except Exception:  # noqa: BLE001 - damaged/unusual PDFs fall back to PyPDF2
        text = ""
    if len(text) < 40:
        try:
            fallback = _pdf_text_pypdf2(file_bytes)
        except Exception:  # noqa: BLE001
            fallback = ""
        if len(fallback) > len(text):
            text = fallback
    text = clean_extracted_text(text)
    if len(text) >= 40 or not use_ocr:
        return text
    # Little to no embedded text -- this is very likely a scanned/image-only
    # PDF. Fall back to OCR; if that also comes up empty, keep whatever
    # (possibly blank) text PyPDF2 found rather than silently returning less.
    return _ocr_pdf_bytes(file_bytes) or text


def extract_docx_text(file_bytes):
    from docx import Document

    document = Document(BytesIO(file_bytes))
    return "\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())


def extract_text_from_stored_document(file_field):
    """Always OCR-free: the only caller is the Similarity Check corpus builder
    (build_repository_documents_from_submissions), which re-extracts every
    approved submission's document on every check and can't afford OCR's cost
    there. A scanned/image-only document on file just contributes no text."""
    if not file_field:
        return ""

    file_name = os.path.basename(file_field.name).lower()
    with file_field.open("rb") as stored_file:
        file_bytes = stored_file.read()

    if file_name.endswith(".pdf"):
        return extract_pdf_text(file_bytes, use_ocr=False)
    if file_name.endswith(".docx"):
        return extract_docx_text(file_bytes)
    if file_name.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="ignore")

    return ""


def build_repository_documents_from_submissions(submissions):
    from .models import account_display_name
    from .semantic import index_for as semantic_index_for

    repository_documents = []

    for submission in submissions:
        if submission.cached_document_text is None:
            document_text = extract_text_from_stored_document(submission.document)
            submission.cached_document_text = document_text
            submission.save(update_fields=["cached_document_text"])
        else:
            document_text = submission.cached_document_text
        combined_text = normalize_text(
            submission.title,
            submission.abstract,
            submission.keywords,
            document_text,
        )
        if not combined_text.strip():
            continue

        profile = getattr(submission.student, "registration_profile", None)
        submitter_display = account_display_name(submission.student)
        title_raw = (submission.title or "").strip()
        authors_raw = (getattr(submission, "authors", None) or "").strip() or ""
        dedup_title = title_raw.lower()
        dedup_authors = authors_raw.lower()
        dedup_key = f"{dedup_title}|{dedup_authors}"
        # Split the document body into its ingredients/procedure section (kept
        # separate from title/abstract so those aren't double-weighted) and
        # everything else, so the whole paper still counts toward the result.
        _title_guess, _abstract_guess, ingredients_raw, general_raw = extract_food_research_sections(document_text)
        ingredients_text = normalize_text(submission.keywords, ingredients_raw)
        general_text = normalize_text(general_raw)
        repository_documents.append(
            {
                "id": submission.id,
                "title": title_raw,
                "authors": authors_raw,
                "ingredients_text": ingredients_text,
                "general_text": general_text,
                # Unstemmed section text, used only to show what matched.
                "ingredients_raw": ingredients_raw,
                "general_raw": general_raw,
                "has_document": bool(document_text.strip()),
                "submitter_name": submitter_display,
                "submitter_email": submission.student.email or "",
                "submitter_program": getattr(profile, "program", "") or "",
                "submitter_college": getattr(profile, "college", "") or "",
                "submitter_login_as": getattr(profile, "login_as", "") or "",
                "adviser": "",
                "keywords": submission.keywords,
                "abstract": submission.abstract or "",
                "status": submission.status or "",
                "source_url": submission.document.url if submission.document else "",
                "submitted_at": timezone.localtime(submission.submitted_at).isoformat() if submission.submitted_at else "",
                "reviewed_at": timezone.localtime(submission.reviewed_at).isoformat() if submission.reviewed_at else "",
                "modified_time": timezone.localtime(submission.reviewed_at).isoformat() if submission.reviewed_at else "",
                "text": combined_text,
                "dedup_title": dedup_title,
                "dedup_key": dedup_key,
                # For the AI meaning comparison (core/semantic.py).
                "semantic_vectors": semantic_index_for(submission),
                "document_text": document_text,
            }
        )

    return repository_documents


def _metadata_richness_score(doc):
    score = 0
    # A document-backed entry is always preferred over a metadata-only twin of
    # the same paper, regardless of which other fields happen to be filled in —
    # it's the one similarity checks can actually match on full content.
    if doc.get("has_document"):
        score += 100
    if (doc.get("authors") or "").strip():
        score += 5
    if (doc.get("abstract") or "").strip():
        score += 3
    if (doc.get("keywords") or "").strip():
        score += 1
    if (doc.get("source_url") or "").strip():
        score += 2
    if (doc.get("submitter_name") or "").strip():
        score += 1
    if (doc.get("submitter_email") or "").strip():
        score += 1
    return score


def deduplicate_repository_documents(docs):
    if not docs:
        return []
    best_by_dedup_key = {}
    best_by_dedup_title = {}
    best_by_id = {}
    ordered_unique = []

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id")
        dedup_title = (doc.get("dedup_title") or "").strip() or (doc.get("title") or "").strip().lower()
        dedup_key = doc.get("dedup_key") or f"{dedup_title}|{(doc.get('authors') or '').strip().lower()}"
        doc = dict(doc)
        doc["dedup_title"] = dedup_title
        doc["dedup_key"] = dedup_key
        richness = _metadata_richness_score(doc)

        duplicate = False
        if doc_id is not None and doc_id in best_by_id:
            existing = best_by_id[doc_id]
            existing["_richness"] = existing.get("_richness") or _metadata_richness_score(existing)
            if richness <= existing["_richness"]:
                duplicate = True
            else:
                ordered_unique.remove(existing)
                del best_by_id[existing.get("id")]
                if existing.get("dedup_key") in best_by_dedup_key and best_by_dedup_key[existing.get("dedup_key")] is existing:
                    del best_by_dedup_key[existing.get("dedup_key")]
                if existing.get("dedup_title") in best_by_dedup_title and best_by_dedup_title[existing.get("dedup_title")] is existing:
                    del best_by_dedup_title[existing.get("dedup_title")]
        if not duplicate and dedup_key and dedup_key in best_by_dedup_key:
            existing = best_by_dedup_key[dedup_key]
            existing["_richness"] = existing.get("_richness") or _metadata_richness_score(existing)
            if richness <= existing["_richness"]:
                duplicate = True
            else:
                ordered_unique.remove(existing)
                if existing.get("id") in best_by_id and best_by_id[existing.get("id")] is existing:
                    del best_by_id[existing.get("id")]
                if existing.get("dedup_title") in best_by_dedup_title and best_by_dedup_title[existing.get("dedup_title")] is existing:
                    del best_by_dedup_title[existing.get("dedup_title")]
                del best_by_dedup_key[dedup_key]
        if not duplicate and dedup_title and dedup_title in best_by_dedup_title:
            existing = best_by_dedup_title[dedup_title]
            existing["_richness"] = existing.get("_richness") or _metadata_richness_score(existing)
            if richness <= existing["_richness"]:
                duplicate = True
            else:
                ordered_unique.remove(existing)
                if existing.get("id") in best_by_id and best_by_id[existing.get("id")] is existing:
                    del best_by_id[existing.get("id")]
                if existing.get("dedup_key") in best_by_dedup_key and best_by_dedup_key[existing.get("dedup_key")] is existing:
                    del best_by_dedup_key[existing.get("dedup_key")]
                del best_by_dedup_title[dedup_title]

        if not duplicate:
            doc["_richness"] = richness
            ordered_unique.append(doc)
            if doc_id is not None:
                best_by_id[doc_id] = doc
            if dedup_key:
                best_by_dedup_key[dedup_key] = doc
            if dedup_title:
                best_by_dedup_title[dedup_title] = doc

    for d in ordered_unique:
        d.pop("_richness", None)
    return ordered_unique
