"""Machine-learning similarity: compares the MEANING of passages with a
pre-trained Sentence-BERT language model (all-MiniLM-L6-v2, a neural network
that turns text into 384-number "meaning vectors"). Reworded copying is found
even when the words are different. It runs next to TF-IDF (core/utils.py):
the AI score decides the result, and TF-IDF only counts for a near-exact copy
(TFIDF_NEAR_COPY); without the model, TF-IDF decides on its own.

How the score works
1. The main text is split into passages of about 120 words. The reference
   list, the appendices after it and table-of-contents style passages are
   left out (they look alike in every thesis).
2. The model turns each passage into a meaning vector.
3. For every passage of the checked file, the closest passage in a study is
   found (cosine similarity). It counts as a full match at MATCH_HIGH or above,
   not at all at MATCH_LOW or below, and partly in between.
4. The score is the share of the file's passages that match that study: 40%
   means about 40% of the paper says the same thing as that study.

MATCH_LOW / MATCH_HIGH were calibrated on the repository in November 2026:
the most sensitive setting under which no two DIFFERENT studies scored above
30%, while a re-uploaded paper scored 100% and a hand-reworded section 81%.

Repository studies are embedded once (in the background when approved, or with
`python manage.py build_semantic_index`) and stored on the submission, so a
check only has to embed the uploaded file. If the model can't be loaded the
check still runs on TF-IDF alone.
"""
import logging
import re
import threading

import numpy as np
from django.conf import settings

from .completeness import _REFERENCES, _YEAR, _headings

logger = logging.getLogger(__name__)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_LABEL = "Sentence-BERT (all-MiniLM-L6-v2)"
# Stored with each saved index; changing the model or passage settings means
# changing this, so outdated indexes are rebuilt instead of compared wrongly.
INDEX_VERSION = "minilm-l6-v2/w120-s60/pymupdf-v2"
WINDOW_WORDS = 120
INDEX_STRIDE = 60          # repository passages overlap, so a copied block lines up
QUERY_STRIDE = 120         # the checked file is split without overlap (faster)
MIN_PASSAGE_WORDS = 40
MATCH_LOW = 0.65
MATCH_HIGH = 0.88
EMBED_BATCH = 32
# "Template" text: a study passage with the same meaning (>= TEMPLATE_SIM) as
# passages in TEMPLATE_MIN_OTHER or more OTHER studies (ethics statements,
# questionnaire items, standard method write-ups). It's ignored when matching,
# so studies that only share the school's template don't look alike.
TEMPLATE_SIM = 0.80
TEMPLATE_MIN_OTHER = 2
# Copied-section rule: SECTION_MIN_PASSAGES or more passages IN A ROW (about
# 600+ words) with the same meaning (>= SECTION_SIM) as one study count as a
# copied section, even when it's a small part of a long paper. Calibrated so no
# two different studies in the repository reach it (their longest run was 3)
# while every copied chapter inside a full thesis did (6-9).
SECTION_SIM = 0.82
SECTION_MIN_PASSAGES = 5

_model = None
_model_failed = False
_model_lock = threading.Lock()


def is_enabled():
    return getattr(settings, "SEMANTIC_SIMILARITY_ENABLED", True)


def get_model():
    """The loaded model, or None when it isn't available (TF-IDF still works)."""
    global _model, _model_failed
    if not is_enabled() or _model_failed:
        return None
    if _model is None:
        with _model_lock:
            if _model is None and not _model_failed:
                try:
                    from fastembed import TextEmbedding

                    _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(settings.ML_MODELS_DIR))
                except Exception:  # noqa: BLE001 - any failure just turns the AI score off
                    logger.exception("Semantic similarity model could not be loaded; using TF-IDF only.")
                    _model_failed = True
    return _model


def warm_up_in_background():
    """Start loading the model while someone is still choosing a file, so the
    first check after the server starts doesn't wait for it."""
    if _model is not None or _model_failed or not is_enabled():
        return
    threading.Thread(target=get_model, daemon=True).start()


# --- Passages -----------------------------------------------------------------

def body_text(text):
    """The paper's main text: stops at the reference list (appendices follow it)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    for match in _headings(_REFERENCES, text):
        if match.start() > len(text) * 0.4 and len(_YEAR.findall(text[match.end():match.end() + 2500])) >= 4:
            return text[:match.start()]
    return text


def passages(text, stride):
    """~120-word passages of the main text, skipping table-of-contents and
    data-table style passages (mostly numbers or dot leaders)."""
    words = body_text(text).split()
    out = []
    for start in range(0, max(1, len(words) - WINDOW_WORDS // 2), stride):
        chunk = words[start:start + WINDOW_WORDS]
        if len(chunk) < MIN_PASSAGE_WORDS:
            continue
        numbers = sum(1 for word in chunk if re.fullmatch(r"[\d.,%()\-–]+", word))
        if numbers / len(chunk) > 0.15 or " ".join(chunk).count("....") >= 2:
            continue
        out.append(" ".join(chunk))
    return out


def embed(texts):
    """Unit-length meaning vectors (float32), or None if the model is unavailable."""
    model = get_model()
    if model is None or not texts:
        return None
    vectors = np.array(list(model.embed(texts, batch_size=EMBED_BATCH)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def pack(vectors):
    return np.asarray(vectors, dtype=np.float16).tobytes()


def unpack(blob):
    if not blob:
        return None
    return np.frombuffer(bytes(blob), dtype=np.float16).astype(np.float32).reshape(-1, 384)


# --- The checked file ---------------------------------------------------------

def query_vectors(text):
    """(passages, vectors) for an uploaded file; vectors is None when the AI
    score can't be computed (model off/unavailable, or no usable text)."""
    query_passages = passages(text, QUERY_STRIDE)
    if not query_passages:
        return [], None
    try:
        return query_passages, embed(query_passages)
    except Exception:  # noqa: BLE001
        logger.exception("Could not embed the checked file; using TF-IDF only.")
        return query_passages, None


_template_cache = {"key": None, "masks": None}


def template_masks(records):
    """For each study (in order), which of its passages are template text: the
    same meaning as passages in TEMPLATE_MIN_OTHER+ other studies. Computed
    once per set of studies and reused until the repository changes."""
    vectors = [r.get("semantic_vectors") for r in records]
    key = tuple((r.get("id"), None if v is None else len(v)) for r, v in zip(records, vectors))
    if _template_cache["key"] == key:
        return _template_cache["masks"]
    masks = []
    for i, own in enumerate(vectors):
        if own is None or not len(own):
            masks.append(None)
            continue
        count = np.zeros(len(own), dtype=int)
        for j, other in enumerate(vectors):
            if j != i and other is not None and len(other):
                best = (own @ other.T).max(axis=1)
                if best.mean() >= 0.95:
                    continue  # the same study uploaded twice isn't "another study"
                count += best >= TEMPLATE_SIM
        masks.append(count >= TEMPLATE_MIN_OTHER)
    _template_cache.update(key=key, masks=masks)
    return masks


def match(query, record, template_mask=None):
    """Meaning match between the checked file and one study, ignoring the
    study's template passages. Returns:
      share:   % of the file's passages with the same meaning as the study
      section: match strength of the longest block of SECTION_MIN_PASSAGES+
               consecutive matching passages (0 if there's no such block)
      score:   the higher of the two (what counts toward the result)
      section_words: about how many words that block covers
      pair:    (file passage #, study passage #, cosine) to show side by side"""
    sims = query @ record.T
    if template_mask is not None and template_mask.any():
        sims[:, template_mask] = -1.0
    best_index = sims.argmax(axis=1)
    best = sims[np.arange(len(sims)), best_index]
    strength = np.clip((best - MATCH_LOW) / (MATCH_HIGH - MATCH_LOW), 0.0, 1.0)
    share = float(strength.mean() * 100)

    run_start, run_length, start = 0, 0, None
    for i, value in enumerate(best):
        if value >= SECTION_SIM:
            start = i if start is None else start
            if i - start + 1 > run_length:
                run_start, run_length = start, i - start + 1
        else:
            start = None
    section = 0.0
    if run_length >= SECTION_MIN_PASSAGES:
        section = float(strength[run_start:run_start + run_length].mean() * 100)
        top = run_start + int(best[run_start:run_start + run_length].argmax())
    else:
        top = int(best.argmax())
    return {"score": max(share, section), "share": share, "section": section,
            "section_words": run_length * WINDOW_WORDS if section else 0,
            "pair": (top, int(best_index[top]), float(best[top]))}


def meaning_section(result, query_passages, record_text):
    """The "Same meaning (AI model)" card for a study's View details."""
    entry = {"key": "meaning", "label": f"Same meaning — AI model, {MODEL_LABEL}", "available": False,
             "note": "", "terms": [], "yours": [], "theirs": [], "passage_score": None}
    pair = result.get("semantic_pair")
    if result.get("semantic_score") is None or not pair:
        entry["note"] = "The AI model wasn't used for this study (no document on file, or the model is off)."
        return entry
    q_index, r_index, cosine = pair
    record_passages = passages(record_text, INDEX_STRIDE)
    if q_index >= len(query_passages) or r_index >= len(record_passages) or cosine <= MATCH_LOW:
        entry["available"] = True
        entry["note"] = "No passage of your file has the same meaning as a passage in this study."
        return entry
    section_words = result.get("semantic_section_words") or 0
    note = "Passages compared by meaning, so reworded text is found too."
    if section_words:
        note = (f"About {section_words} words in a row of your file have the same meaning as this study "
                f"(a copied or reworded section). " + note)
    entry.update({
        "available": True,
        "note": note,
        "yours": [{"t": query_passages[q_index], "m": False}],
        "theirs": [{"t": record_passages[r_index], "m": False}],
        "passage_score": round(cosine * 100),
    })
    return entry


# --- Saved indexes for repository studies ---------------------------------------

def index_for(submission):
    """The saved vectors of an approved study, or None if missing or outdated."""
    if getattr(submission, "semantic_index_version", "") != INDEX_VERSION:
        return None
    return unpack(submission.semantic_index)


def build_index(submission):
    """Embed one study's document and save it. Returns True when saved."""
    from .utils import extract_text_from_stored_document

    text = submission.cached_document_text
    if text is None:
        try:
            text = extract_text_from_stored_document(submission.document)
        except Exception as exc:  # noqa: BLE001 - a damaged file just gets no AI vectors
            logger.warning("Could not read the document of submission %s for the AI model: %s", submission.pk, exc)
            return False
        submission.cached_document_text = text
        submission.save(update_fields=["cached_document_text"])
    vectors = embed(passages(text or "", INDEX_STRIDE))
    if vectors is None:
        return False
    submission.semantic_index = pack(vectors)
    submission.semantic_index_version = INDEX_VERSION
    submission.save(update_fields=["semantic_index", "semantic_index_version"])
    return True


def index_in_background(submission_id):
    """Embed a newly approved study without making the person wait."""
    if not is_enabled():
        return

    def _worker():
        from django.db import connection

        from .models import ResearchSubmission

        try:
            submission = ResearchSubmission.objects.filter(pk=submission_id).first()
            if submission and submission.document:
                build_index(submission)
        except Exception:  # noqa: BLE001
            logger.exception("Could not build the meaning index for submission %s.", submission_id)
        finally:
            connection.close()

    threading.Thread(target=_worker, daemon=True).start()
