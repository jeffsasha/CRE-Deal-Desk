"""Strings that are stored in the database or built at runtime but shown in the
interface. Listing them here lets `makemessages` extract them for translation;
templates translate them with `{% translate value %}`."""
from django.utils.translation import gettext_noop as _

STAGE_NAMES = [
    _("Lead"), _("Evaluating"), _("Touring"), _("LOI"), _("Negotiating"), _("Under Contract"), _("Due Diligence"),
    _("Preparing to Close"), _("Closed"), _("On Hold"), _("Terminated"), _("Lost"), _("Archived"),
]
ROLE_NAMES = [_("Administrator"), _("Broker"), _("Coordinator"), _("Read-only")]
