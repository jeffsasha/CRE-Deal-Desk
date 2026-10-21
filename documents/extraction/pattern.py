"""Offline pattern extractor.

Used when no AI credential is configured. It recognizes common phrasings in
commercial purchase contracts, leases and amendments, always with the page and the
matching text. It is deliberately conservative: anything it cannot read cleanly is
left out or marked for review, and it never supplies a period that is not written.
"""
import re

from deals.catalog import term_label

from . import ExtractionOutput, Proposal

MONEY = r"\$\s?([\d,]+(?:\.\d{2})?)"
NUM_WORD = (r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
            r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)")
NUM_DAYS = rf"((?:{NUM_WORD}(?:[\s-]{NUM_WORD})*\s*)?\(\d+\)|\d+|{NUM_WORD}(?:[\s-]{NUM_WORD})*)"
SPAN = r"(?:[^.]|\.(?=\d))"  # any character except a sentence-ending period
DATE = r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})"

# (key, pattern, value group, confidence)
RULES = [
    ("purchase_price", rf"\b(?:purchase|sales)\s+price\b[^$.]{{0,80}}?{MONEY}", 1, "medium"),
    ("earnest_money_amount", rf"\bearnest\s+money\b(?:\s+in\s+the\s+amount\s+of|[^$.]{{0,100}}?)\s*{MONEY}", 1, "medium"),
    ("additional_deposit_amount", rf"\badditional\s+(?:earnest\s+money|deposit)\b[^$.]{{0,120}}?{MONEY}", 1, "medium"),
    ("earnest_money_deposit_days",
     rf"\bwithin\s+{NUM_DAYS}\s+((?:business|calendar)\s+)?days\s+after\s+the\s+effective\s+date,?\s+{SPAN}{{0,40}}?\b(?:deposit|deliver)\b{SPAN}{{0,40}}?\bearnest\s+money\b", 1, "medium"),
    ("earnest_money_deposit_days",
     rf"\b(?:deposit|deliver)\b{SPAN}{{0,100}}?\bearnest\s+money\b{SPAN}{{0,120}}?\bwithin\s+{NUM_DAYS}\s+((?:business|calendar)\s+)?days", 1, "medium"),
    ("feasibility_period_days",
     rf"\b(?:feasibility|inspection|due\s+diligence)\s+period\b{SPAN}{{0,140}}?\b{NUM_DAYS}\s+((?:business|calendar)\s+)?days\b", 1, "medium"),
    ("title_commitment_delivery_days",
     rf"\b(?:title\s+)?commitment\b{SPAN}{{0,180}}?\bwithin\s+{NUM_DAYS}\s+((?:business|calendar)\s+)?days\s+after\s+the\s+effective\s+date", 1, "medium"),
    ("survey_delivery_days",
     rf"\bsurvey\b{SPAN}{{0,180}}?\bwithin\s+{NUM_DAYS}\s+((?:business|calendar)\s+)?days\s+after\s+the\s+effective\s+date", 1, "medium"),
    ("title_objection_days",
     rf"\bobject(?:ion|ions)?\b{SPAN}{{0,200}}?\bwithin\s+{NUM_DAYS}\s+((?:business|calendar)\s+)?days\s+after\s+(?:the\s+later\s+of|receipt)", 1, "medium"),
    ("cure_period_days", rf"\bcure\b{SPAN}{{0,140}}?\bwithin\s+{NUM_DAYS}\s+((?:business|calendar)\s+)?days\b", 1, "low"),
    ("financing_contingency_days",
     rf"\bfinancing\b{SPAN}{{0,160}}?\bwithin\s+{NUM_DAYS}\s+((?:business|calendar)\s+)?days\s+after\s+the\s+effective\s+date", 1, "medium"),
    ("closing_date", rf"\bclosing\b{SPAN}{{0,100}}?\bon\s+or\s+before\s+{DATE}", 1, "medium"),
    ("closing_date", rf"\bclosing\s+date\s+(?:is|shall\s+be)\s+(?:hereby\s+)?(?:extended|amended|changed|moved)\s+to\s+{DATE}", 1, "medium"),
    ("closing_days_after_effective",
     rf"\bclosing\b{SPAN}{{0,120}}?\bwithin\s+{NUM_DAYS}\s+((?:business|calendar)\s+)?days\s+after\s+the\s+effective\s+date", 1, "low"),
    ("outside_closing_date", rf"\boutside\s+(?:closing\s+)?date\b{SPAN}{{0,60}}?{DATE}", 1, "medium"),
    ("lease_term_months", rf"\b(?:primary\s+|initial\s+)?term\s+of\s+{NUM_DAYS}\s+months\b", 1, "medium"),
    ("security_deposit", rf"\bsecurity\s+deposit\b[^$.]{{0,80}}?{MONEY}", 1, "medium"),
    ("commencement_date", rf"\bcommencement\s+date\b{SPAN}{{0,40}}?(?:is|shall\s+be|means)\s+{DATE}", 1, "medium"),
]

# (key, sentence trigger) — clause text fields returned as the full sentence.
CLAUSES = [
    ("parties", r"\bby\s+and\s+between\b"),
    ("property_description", r"\bcommonly\s+known\s+as\b|\blegally\s+described\b"),
    ("effective_date_definition", r"[\"“]?effective\s+date[\"”]?\s+(?:means|shall\s+mean|is\s+the\s+date)"),
    ("earnest_money_holder", r"\bearnest\s+money\b[^.]*\b(?:title|escrow)\s+(?:company|agent)\b"),
    ("earnest_money_refundability", r"\bearnest\s+money\b[^.]*\b(?:refund|non-?refundable|released\s+to)\b"),
    ("additional_deposit_trigger", r"\badditional\s+(?:earnest\s+money|deposit)\b"),
    ("termination_notice", r"\bterminat\w*\b[^.]*\bnotice\b"),
    ("appraisal_contingency", r"\bapprais"),
    ("extension_options", r"\b(?:option|right)\s+to\s+extend\b|\bextend\s+the\s+closing\b"),
    ("possession_delivery", r"\bpossession\b"),
    ("notice_recipients", r"\bnotices?\b[^.]*\b(?:shall\s+be\s+(?:sent|delivered|given)|addressed)\b"),
    ("commission_provision", r"\b(?:commission|brokerage\s+fee)\b"),
    ("closing_preconditions", r"\bconditions?\s+(?:precedent\s+)?to\s+closing\b"),
    ("weekend_holiday_rule", r"\b(?:saturday|sunday|legal\s+holiday)\b[^.]*\b(?:extend|next)\b"),
    ("base_rent", r"\bbase\s+rent\b"),
    ("ti_allowance", r"\b(?:tenant\s+improvement|TI)\s+allowance\b"),
    ("free_rent", r"\b(?:free|abated)\s+rent\b|\brent\s+abatement\b"),
    ("permitted_use", r"\bpermitted\s+use\b|\bshall\s+use\s+the\s+premises\b"),
    ("renewal_options", r"\b(?:renewal|renew)\b"),
    ("guaranty", r"\bguarant(?:y|ee|or)\b"),
]

SECTION_RE = re.compile(
    r"^\s*((?:section|article)\s+[\dIVXLC]+(?:\.\d+)*[^\n]{0,60}|\d{1,2}(?:\.\d{1,2})*\.\s+[A-Z][^\n]{0,60})", re.I | re.M
)
EFFECTIVE_EXPLICIT = re.compile(rf"\beffective\s+date\b[^.]{{0,40}}?\b(?:is|shall\s+be|of)\s+{DATE}", re.I)
SIGNATURE_DATE = re.compile(rf"\b(?:date(?:d)?|signed|executed)\s*(?:on)?\s*:?\s*{DATE}", re.I)


def _section(text, pos):
    best = ""
    for m in SECTION_RE.finditer(text, 0, pos):
        best = m.group(1).strip()
    return best[:120]


HEADING_LINE = re.compile(r"^[A-Z0-9 \-–—:()'\"&,./]{4,}$")


SENTENCE_END = re.compile(r"\.(?!\d)|\n\s*\n")


def _sentence(text, start, end):
    left = 0
    for m in SENTENCE_END.finditer(text, 0, start):
        left = m.end()
    m = SENTENCE_END.search(text, end)
    right = m.end() if m else len(text)
    lines = text[left:right].split("\n")
    while len(lines) > 1 and (not lines[0].strip() or HEADING_LINE.match(lines[0].strip())):
        lines.pop(0)
    return " ".join(" ".join(lines).split())[:800]


def _business_days_flag(match):
    for g in match.groups()[1:]:
        if g and "business" in g.lower():
            return ["Period is stated in business days — set the deadline rule's day basis to business days."]
    return []


def extract(pages, doc_type="unknown"):
    proposals = []
    seen_values = {}
    for page_no, text in enumerate(pages, start=1):
        if not text:
            continue
        flat = text
        for key, pattern, group, confidence in RULES:
            for m in re.finditer(pattern, flat, re.I | re.S):
                value = " ".join(m.group(group).split())
                prop = Proposal(
                    key=key, label=term_label(key), value=value, page=page_no, section=_section(flat, m.start()),
                    supporting_text=_sentence(flat, m.start(), m.end()), confidence=confidence,
                    flags=_business_days_flag(m),
                )
                sig = (key, value.lower())
                if sig in seen_values:
                    continue
                seen_values[sig] = True
                proposals.append(prop)
        for key, trigger in CLAUSES:
            m = re.search(trigger, flat, re.I | re.S)
            if m and not any(p.key == key for p in proposals):
                sentence = _sentence(flat, m.start(), m.end())
                if len(sentence) > 30:
                    proposals.append(Proposal(
                        key=key, label=term_label(key), value=sentence, page=page_no,
                        section=_section(flat, m.start()), supporting_text=sentence, confidence="low",
                    ))

    # Effective date: only an explicitly stated date is proposed. Signature dates are
    # reported as a caution, never as the effective date.
    explicit = None
    for page_no, text in enumerate(pages, start=1):
        m = EFFECTIVE_EXPLICIT.search(text or "")
        if m:
            explicit = Proposal(
                key="effective_date", label="Effective date", value=m.group(1), page=page_no,
                section=_section(text, m.start()), supporting_text=_sentence(text, m.start(), m.end()), confidence="medium",
            )
            break
    if explicit:
        proposals.append(explicit)
    else:
        sig_dates = []
        for page_no, text in enumerate(pages, start=1):
            for m in SIGNATURE_DATE.finditer(text or ""):
                sig_dates.append((page_no, m.group(1), _sentence(text, m.start(), m.end())))
        definition = next((p for p in proposals if p.key == "effective_date_definition"), None)
        if definition or sig_dates:
            note = "No explicit effective date is stated."
            if definition:
                note += " The contract defines it by an event (see definition); record the actual event date after confirming it."
            if sig_dates:
                listed = "; ".join(f"{d} (p. {p})" for p, d, _ in sig_dates[:4])
                note += f" Signature dates found: {listed}. A signature date is not automatically the effective date."
            proposals.append(Proposal(
                key="effective_date", label="Effective date", value="",
                page=definition.page if definition else sig_dates[0][0],
                section=definition.section if definition else "",
                supporting_text=definition.supporting_text if definition else sig_dates[0][2],
                confidence="low", flags=[note],
            ))

    return ExtractionOutput(engine="pattern", doc_type=doc_type, proposals=proposals,
                            summary=f"Offline pattern extractor found {len(proposals)} candidate value(s). Review each against the document.")
