"""Deterministic checks applied to every extraction proposal, whatever produced it.

These do not decide anything; they flag proposals so a reviewer looks harder. A
flagged proposal starts in "Needs Review" and cannot be published until a person
resolves it.
"""
import re
import unicodedata

from deals.catalog import TERM_CATALOG, term_type


def _norm(text):
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^a-z0-9$%./ ]+", " ", text.lower())
    return " ".join(text.split())


def locate_quote(quote, pages, page_hint=None):
    """Return the 1-based page where the quote appears, or None."""
    q = _norm(quote)
    if len(q) < 8:
        return None
    probes = [q] if len(q) <= 80 else [q[:60], q[len(q) // 2 - 30: len(q) // 2 + 30], q[-60:]]
    order = list(range(1, len(pages) + 1))
    if page_hint and 1 <= page_hint <= len(pages):
        order.remove(page_hint)
        order.insert(0, page_hint)
    for p in order:
        hay = _norm(pages[p - 1])
        hits = sum(1 for probe in probes if probe in hay)
        if hits >= max(1, len(probes) - 1):
            return p
    return None


def _normalized_value(key, value):
    from deals.services import parse_term_value

    try:
        v = parse_term_value(key, value)
        return str(v)
    except ValueError:
        return _norm(value)


def apply(proposals, pages, doc_type):
    """Mutates proposals: adds flags, corrects pages, and returns
    [(proposal, quote_verified, review_status)]."""
    from deals.services import parse_term_value

    has_text = any((t or "").strip() for t in pages)
    by_key = {}
    for p in proposals:
        by_key.setdefault(p.key, []).append(p)

    results = []
    for p in proposals:
        flags = list(p.flags)
        verified = False
        if p.supporting_text:
            if not has_text:
                flags.append("Could not verify the supporting text: the document has no readable text (OCR unavailable).")
            else:
                found = locate_quote(p.supporting_text, pages, p.page)
                if found is None:
                    flags.append("Supporting text was not found in the document text. Verify against the original.")
                else:
                    verified = True
                    if p.page and found != p.page:
                        flags.append(f"Page corrected from {p.page} to {found} (where the supporting text appears).")
                    p.page = found
        else:
            flags.append("No supporting text was provided.")

        if p.key != "effective_date" and p.key not in TERM_CATALOG:
            flags.append("Unrecognized field key.")
        if p.value.strip() == "":
            flags.append("No value proposed.")
        elif p.key == "effective_date":
            try:
                parse_term_value("closing_date", p.value)  # date parse
            except ValueError:
                flags.append("Effective date is not a recognizable date.")
        else:
            try:
                parse_term_value(p.key, p.value)
            except ValueError as exc:
                flags.append(f"Value does not parse as {term_type(p.key)}: {exc}")

        if p.key == "effective_date":
            st = (p.supporting_text or "").lower()
            if re.search(r"\b(sign|signed|signature|execut)", st) and "effective date" not in st:
                flags.append("The supporting text appears to be a signature or execution date, which is not automatically the effective date.")

        siblings = by_key.get(p.key, [])
        if len(siblings) > 1:
            distinct = {_normalized_value(s.key, s.value) for s in siblings if s.value.strip()}
            if len(distinct) > 1:
                listed = "; ".join(f"{s.value} (p. {s.page or '?'})" for s in siblings)
                flags.append(f"Conflicting values found in this document: {listed}.")

        if p.basis == "calculated":
            flags.append("Value is calculated, not stated explicitly. Confirm the calculation.")
        if doc_type in {"amendment", "extension"}:
            flags.append("From an amendment/extension: changes apply only after execution is confirmed and the amendment is applied.")

        p.flags = list(dict.fromkeys(flags))
        blocking = [f for f in p.flags if not f.startswith("From an amendment")]
        status = "needs_review" if (blocking or p.confidence == "low") else "pending"
        results.append((p, verified, status))
    return results
