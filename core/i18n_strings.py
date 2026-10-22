"""Strings that are stored in the database or built at runtime but shown in the
interface. Listing them here lets `makemessages` extract them for translation;
templates translate them with `{% translate value %}`."""
from django.utils.translation import gettext_noop as _

STAGE_NAMES = [
    _("Lead"), _("Evaluating"), _("Listed"), _("Touring"), _("LOI"), _("Negotiating"), _("Under Contract"), _("Due Diligence"),
    _("Preparing to Close"), _("Closed"), _("On Hold"), _("Terminated"), _("Lost"), _("Archived"),
]
ROLE_NAMES = [_("Administrator"), _("Broker"), _("Coordinator"), _("Read-only")]

# Statuses derived at runtime (commissions/ledger.py, deals.models.Deposit.status).
COMPUTED_STATUSES = [
    _("Agreement not executed"), _("Commission unknown"), _("Disputed"), _("Earned — amount unknown"),
    _("Earned — awaiting payment"), _("Earned — past due"), _("No distributions recorded"), _("Not yet earned"),
    _("Partially received"), _("Received before earned — reconcile"), _("Received in full"),
    _("Received more than earned — reconcile"), _("Received to date — later installments pending"), _("Void"),
    _("Awaiting receipt"), _("Distribution amounts unknown"), _("Distributions outstanding"), _("Fully distributed"),
    _("Not yet deposited"), _("Receipt confirmed"), _("Released / applied"), _("Sent — awaiting receipt confirmation"),
]
