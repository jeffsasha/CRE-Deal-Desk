"""Deterministic communication drafts built from the deal record. Drafts are never sent
by the system; the user copies or opens them in their own mail client and then marks
them as sent."""
from core.money import format_cents


def _party(deal, role):
    p = deal.parties.filter(role=role).select_related("contact", "organization").first()
    if not p:
        return None, ""
    email = p.contact.email if p.contact_id and p.contact.email else (p.organization.email if p.organization_id else "")
    return p, email


def _greeting(party):
    if party and party.contact_id:
        return f"Hi {party.contact.first_name or party.contact.full_name},"
    return "Hello,"


def title_status(deal):
    party, email = _party(deal, "escrow_officer")
    if not party:
        party, email = _party(deal, "title_company")
    gf = party.file_number if party and party.file_number else "[file number]"
    prop = deal.primary_property
    body = f"""{_greeting(party)}

Following up on {prop.address if prop else deal.name} (GF/file {gf}). Could you please confirm the status of the following:

- Title commitment (and the date it was or will be issued)
- Copies of all Schedule B exception documents
- Receipt of the earnest money and the receipt date

Thank you,
"""
    return {"to": email, "subject": f"Title status — {deal.name}", "body": body}


def survey_status(deal):
    party, email = _party(deal, "surveyor")
    body = f"""{_greeting(party)}

Checking on the survey for {deal.name}. Please let me know the expected delivery date and whether the survey will be certified to the buyer, lender and title company as required.

Thank you,
"""
    return {"to": email, "subject": f"Survey status — {deal.name}", "body": body}


def earnest_money(deal):
    party, email = _party(deal, "escrow_officer")
    if not party:
        party, email = _party(deal, "title_company")
    lines = []
    for dep in deal.deposits.all():
        if dep.awaiting:
            lines.append(f"- {dep.get_kind_display()}: {format_cents(dep.amount_cents)}")
    items = "\n".join(lines) or "- Earnest money"
    body = f"""{_greeting(party)}

Please confirm receipt of the following deposit(s) for {deal.name}, including the date received:

{items}

Thank you,
"""
    return {"to": email, "subject": f"Deposit receipt confirmation — {deal.name}", "body": body}


def next_action(deal):
    body = f"""Hello,

Following up on {deal.name}. Next step on our side: {deal.next_action or '[describe]'}.
{('We are currently waiting on: ' + deal.blocked_by) if deal.is_blocked else ''}

Thank you,
"""
    return {"to": "", "subject": f"Follow-up — {deal.name}", "body": body}


TEMPLATES = {
    "title_status": ("Request title commitment status", title_status),
    "survey_status": ("Request survey status", survey_status),
    "earnest_money": ("Request deposit receipt confirmation", earnest_money),
    "next_action": ("Follow-up on next action", next_action),
}
