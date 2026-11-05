"""Which characters the typed research fields accept (Submit Research for
Students, Add Research for Admins and Super Admins).

Numbers and special characters are not accepted. Each field allows only the
few marks it needs: "-" everywhere, "." and "," in names, and parentheses in
titles and abstracts. The Abstract is the only field that also takes numbers
and "%", because abstracts report results ("30% banana peel flour").

core/static/core/js/field-rules.js applies the same rules in the browser.
"""
import re
import unicodedata

FIELD_RULES = {
    "category": {"marks": "-", "digits": False},
    "keyword": {"marks": "-", "digits": False},
    "name": {"marks": "-.,", "digits": False},
    "title": {"marks": "-.,()", "digits": False},
    "abstract": {"marks": "-.,()%", "digits": True},
}

# Typographic dashes and minus signs count as a plain "-".
_DASHES = re.compile(r"[‐-―−]")


def normalize_text_input(value):
    """Composed accents (so "ñ" is one letter) and plain hyphens."""
    return _DASHES.sub("-", unicodedata.normalize("NFC", value or ""))


def allowed_description(rule):
    """e.g. "letters, spaces, and - . ," for names."""
    spec = FIELD_RULES[rule]
    base = "letters, numbers, spaces" if spec["digits"] else "letters, spaces"
    return f"{base}, and {' '.join(spec['marks'])}"


def disallowed_characters(value, rule):
    """The distinct characters in `value` that `rule` doesn't accept, in order."""
    spec = FIELD_RULES[rule]
    found = []
    for char in normalize_text_input(value):
        if char.isalpha() or char.isspace() or char in spec["marks"] or (spec["digits"] and char.isdecimal()):
            continue
        if char not in found:
            found.append(char)
    return found


def rule_error(label, value, rule):
    """A message naming what to remove, or "" when the value is fine."""
    found = disallowed_characters(value, rule)
    if not found:
        return ""
    return f"{label} can only use {allowed_description(rule)}. Please remove: {' '.join(found[:10])}"


def list_rule_error(label, values, rule):
    """For lists entered one by one (authors, keywords): names the entries to fix."""
    bad = [value for value in values if disallowed_characters(value, rule)]
    if not bad:
        return ""
    return f"{label} can only use {allowed_description(rule)}. Please fix: {', '.join(bad[:5])}"


def tidy_to_rule(value, rule):
    """Fits text read from an uploaded file to a field's rule, so auto-filled
    fields don't start out with errors. Typed text is never changed this way;
    it is checked and the user is told what to remove."""
    spec = FIELD_RULES[rule]
    text = normalize_text_input(value)
    text = text.replace("&", " and ").replace("/", " ")
    if "(" in spec["marks"]:
        text = text.replace("[", "(").replace("]", ")").replace("{", "(").replace("}", ")")
    separator = "," if "," in spec["marks"] else " "
    text = text.replace(";", separator)
    text = text.replace(":", " - " if rule in ("title", "abstract") else separator)
    text = "".join(
        char if (char.isalpha() or char.isspace() or char in spec["marks"] or (spec["digits"] and char.isdecimal())) else " "
        for char in text
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([.,)])", r"\1", text)
    text = re.sub(r"\( +", "(", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"([.,-])(?:\s*\1)+", r"\1", text)
    return text.strip(" ,-\t\n")
