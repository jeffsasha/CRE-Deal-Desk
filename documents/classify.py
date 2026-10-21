"""Heuristic document-type and execution-status detection.

These are *apparent* findings shown to the reviewer. Only a user can confirm that a
document is executed; an uploaded file is never treated as executed by default.
"""
import re

TYPE_PATTERNS = [
    ("extension", [r"\bextension (agreement|of (the )?closing)", r"\bextends? the closing", r"\bfirst extension\b"]),
    ("amendment", [r"\b(first|second|third|fourth)?\s*amendment to\b", r"\bamendment no\.", r"^\s*amendment\b"]),
    ("loi", [r"\bletter of intent\b", r"\bnon-binding\b.*\bproposal\b", r"\bterms? sheet\b"]),
    ("title_commitment", [r"commitment for title insurance", r"\btitle commitment\b", r"schedule b-?\s*(part)?\s*(i|1|ii|2)"]),
    ("owner_title_policy", [r"owner'?s policy of title insurance"]),
    ("lender_title_policy", [r"\bloan policy of title insurance", r"\blender'?s policy\b"]),
    ("closing_statement", [r"\b(closing|settlement) statement\b", r"\bALTA settlement\b"]),
    ("commission_agreement", [r"\bcommission agreement\b", r"\blisting agreement\b", r"\bbrokerage (fee|commission) agreement\b"]),
    ("lease", [r"\blease agreement\b", r"\bcommercial lease\b", r"\blandlord\b.*\btenant\b.*\bpremises\b"]),
    ("purchase_contract", [r"\bpurchase and sale agreement\b", r"\bcommercial contract\b", r"\bcontract of sale\b",
                           r"\bpurchase agreement\b", r"\bearnest money\b.*\bseller\b"]),
    ("survey", [r"\bregistered professional land surveyor\b", r"\bALTA/NSPS\b", r"\bland title survey\b"]),
    ("environmental_report", [r"\bphase i environmental site assessment\b", r"\bASTM E1527\b"]),
    ("inspection_report", [r"\binspection report\b", r"\bproperty condition (assessment|report)\b"]),
    ("insurance", [r"\bevidence of (commercial )?property insurance\b", r"\binsurance binder\b", r"\bcertificate of liability insurance\b"]),
]


def detect_doc_type(pages):
    if not pages:
        return "unknown"
    first = (pages[0] or "")[:3000]
    body = "\n".join(pages)[:60000]
    # The title block decides amending documents: an amendment to a contract also
    # contains contract vocabulary, but it is not the base contract.
    title = "\n".join([line for line in first.splitlines() if line.strip()][:6])
    if re.search(r"\bextension\b", title, re.I):
        return "extension"
    if re.search(r"\bamendment\b", title, re.I):
        return "amendment"
    best, best_score = "unknown", 0
    for doc_type, patterns in TYPE_PATTERNS:
        score = 0
        for pat in patterns:
            if re.search(pat, first, re.I | re.S | re.M):
                score += 3
            elif re.search(pat, body, re.I | re.S | re.M):
                score += 1
        if score > best_score:
            best, best_score = doc_type, score
    return best


BLANK_SIG = re.compile(r"\b(By|Signature|Signed)\s*:?\s*_{4,}", re.I)
FILLED_SIG = re.compile(r"\bBy\s*:\s*(/s/|[A-Z][a-z]+ [A-Z][a-z]+)", re.M)
CONFORMED = re.compile(r"/s/\s*[A-Z]", re.M)
ESIGN = re.compile(r"(DocuSign Envelope ID|dotloop verified|Authentisign|Signed by:)", re.I)
DRAFT = re.compile(r"(\bDRAFT\b|\bfor discussion purposes only\b|\bnot for execution\b)")


def detect_execution(pages):
    """Return (apparent_status, signals[])."""
    text = "\n".join(pages or [])
    signals = []
    draft = bool(DRAFT.search(text))
    blank = len(BLANK_SIG.findall(text))
    filled = len(FILLED_SIG.findall(text)) + len(CONFORMED.findall(text))
    esign = bool(ESIGN.search(text))
    if draft:
        signals.append("Draft marking found (e.g. 'DRAFT' or 'for discussion purposes only').")
    if blank:
        signals.append(f"{blank} blank signature line(s) found.")
    if filled:
        signals.append(f"{filled} signature block(s) appear to contain a name or conformed '/s/' signature.")
    if esign:
        signals.append("Electronic-signature platform marker found (does not by itself prove completion).")
    if not text.strip():
        signals.append("No readable text; execution cannot be assessed from text.")
        return "unknown", signals
    if draft:
        return "draft", signals
    if blank and filled:
        return "partially_signed", signals
    if blank and not filled:
        return "draft", signals
    if filled and not blank:
        return "appears_executed", signals
    signals.append("No signature blocks recognized.")
    return "unknown", signals
