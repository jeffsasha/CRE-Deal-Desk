"""The deal's price, entered with the deal and edited from its page.

  sale / business: the Sale price is the contract's purchase price (an approved term);
                   once the deal is closed the same field edits the closing price.
  lease:           rent with its unit, NNN or Gross, and optional NNN charges,
                   utilities, free rent, TI allowance and annual escalation.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_noop, gettext, pgettext_lazy

from core.choices import RATE_UNIT_SUFFIX, RATE_UNITS
from core.fields import AmountField, MoneyField

from . import services
from .models import Deal, DealTerm, log_activity

LEASE_BASE_LABELS = {"nnn": pgettext_lazy("rent basis", "NNN"), "gross": pgettext_lazy("rent basis", "Gross")}

LEASE_FIELDS = ["lease_starting_rent", "lease_rent_unit", "lease_rent_basis", "lease_nnn_amount", "lease_utility_amount",
                "lease_utility_unit", "lease_free_rent_months", "lease_ti_amount", "lease_ti_unit", "lease_escalation_pct",
                "lease_area_sf", "lease_term_months"]


def lease_total_cents(data):
    """Signed initial term only. Free months start at month 1; increases apply
    every 12 months. Sum exact Decimal amounts and round the final total to cents.
    Separately entered charges, incentives and renewal options are excluded.
    """
    months, rent, unit = data.get("lease_term_months"), data.get("lease_starting_rent"), data.get("lease_rent_unit")
    if months is None or rent is None or not unit:
        return None
    if not 1 <= months <= 1200:
        raise ValidationError({"lease_term_months": gettext("Enter a signed term between 1 and 1,200 months.")})
    free = data.get("lease_free_rent_months") or Decimal(0)
    increase = data.get("lease_escalation_pct") or Decimal(0)
    if rent < 0:
        raise ValidationError({"lease_starting_rent": gettext("Amount cannot be negative.")})
    if free < 0 or free > months:
        raise ValidationError({"lease_free_rent_months": gettext("Free rent must be between zero and the signed lease term.")})
    if not 0 <= increase <= 100:
        raise ValidationError({"lease_escalation_pct": gettext("Enter an annual increase between 0 and 100 percent.")})
    if unit == "usd_total":
        if free or increase:
            raise ValidationError({"lease_rent_unit": gettext("Lump-sum rent is already the full total. Choose a recurring unit to calculate free rent or annual increases.")})
        total = rent
    elif unit in {"usd_month", "usd_year", "usd_sf_month", "usd_sf_year"}:
        area = data.get("lease_area_sf")
        if unit in {"usd_sf_month", "usd_sf_year"} and (area is None or area <= 0):
            return None
        with localcontext() as context:
            context.prec = 50
            monthly = rent * area if unit in {"usd_sf_month", "usd_sf_year"} else rent
            if unit in {"usd_year", "usd_sf_year"}:
                monthly /= 12
            growth = 1 + increase / 100
            total = sum((monthly * growth ** (month // 12) * max(Decimal(0), min(Decimal(1), Decimal(month + 1) - free))
                         for month in range(months)), Decimal(0))
    else:
        return None
    if total > Decimal("92233720368547758.07"):
        raise ValidationError({"lease_starting_rent": gettext("The calculated rent total is too large. Check the rent, term and annual increase.")})
    return int((total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculated_total(deal):
    return lease_total_cents({name: getattr(deal, name) for name in LEASE_FIELDS})


def validate_lease_data(form, data):
    """Apply the same calculation checks before anything is saved."""
    try:
        lease_total_cents(data)
    except ValidationError as exc:
        form.add_error(None, exc)
    if data.get("lease_term_months") and data.get("lease_starting_rent") is not None:
        unit = data.get("lease_rent_unit")
        if not unit:
            form.add_error("lease_rent_unit", gettext("Choose the rent unit to calculate the signed lease total."))
        elif unit in {"usd_sf_month", "usd_sf_year"} and not data.get("lease_area_sf"):
            form.add_error("lease_area_sf", gettext("Enter the leased area to calculate rent quoted per square foot."))


def add_price_fields(form, lease):
    """Add the price inputs to a form (New deal or Edit)."""
    f = form.fields
    if lease:
        f["lease_term_months"] = forms.IntegerField(label=gettext_noop("Signed lease term (months)"), required=False,
                                                      min_value=1, max_value=1200,
                                                      help_text=gettext_noop("5 years = 60 months; 10 years = 120 months. Exclude unexercised renewal options."))
        f["lease_starting_rent"] = AmountField(label=gettext_noop("Rent"), max_digits=14, decimal_places=4)
        f["lease_rent_unit"] = forms.ChoiceField(label=gettext_noop("Rent unit"), choices=RATE_UNITS[1:] + RATE_UNITS[:1],
                                                 initial="usd_month", required=False)
        f["lease_rent_basis"] = forms.ChoiceField(label=gettext_noop("Rent type"), choices=[(k, LEASE_BASE_LABELS[k]) for k, v in Deal.LEASE_BASES], initial="nnn",
                                                  widget=forms.RadioSelect, required=False)
        f["lease_nnn_amount"] = AmountField(label=gettext_noop("NNN charges"), help_text=gettext_noop("Same unit as the rent. Optional."))
        f["lease_utility_amount"] = AmountField(label=gettext_noop("Utilities"), help_text=gettext_noop("Optional."))
        f["lease_utility_unit"] = forms.ChoiceField(label=gettext_noop("Utilities unit"), choices=RATE_UNITS[1:] + RATE_UNITS[:1],
                                                    initial="usd_month", required=False)
        f["lease_area_sf"] = forms.DecimalField(label=gettext_noop("Area (SF)"), required=False, min_value=0, max_digits=12, decimal_places=2)
        f["lease_free_rent_months"] = forms.DecimalField(label=gettext_noop("Free rent (months)"), required=False, min_value=0,
                                                         max_digits=5, decimal_places=1)
        f["lease_ti_amount"] = AmountField(label=gettext_noop("TI allowance"), help_text=gettext_noop("Optional."))
        f["lease_ti_unit"] = forms.ChoiceField(label=gettext_noop("TI unit"), choices=Deal.TI_UNITS, initial="usd_total", required=False)
        f["lease_escalation_pct"] = forms.DecimalField(label=gettext_noop("Annual escalation (%)"), required=False, min_value=0,
                                                       max_value=100, max_digits=5, decimal_places=2)
        for name in ("lease_area_sf", "lease_free_rent_months", "lease_escalation_pct"):
            f[name].widget.attrs.update({"inputmode": "decimal", "step": "any"})
    else:
        f["price"] = MoneyField(label=gettext_noop("Sale price"), help_text="")


def initial(deal):
    """Current values for the Edit form."""
    if deal.is_lease:
        return {name: getattr(deal, name) for name in LEASE_FIELDS}
    return {"price": deal.actual_closing_price_cents if deal.is_closed else deal.executed_contract_price_cents}


@transaction.atomic
def save(deal, data, actor):
    """Apply the price inputs. Returns True if anything changed."""
    if deal.is_lease:
        # Units and the rent type are text ("" = not chosen); amounts are Decimal or None.
        changed = [n for n in LEASE_FIELDS if n in data and getattr(deal, n) != data[n]]
        for n in changed:
            setattr(deal, n, data[n])
        if deal.lease_term_months is not None or "lease_term_months" in changed:
            total = calculated_total(deal)
            if total != deal.lease_total_consideration_cents:
                deal.lease_total_consideration_cents = total
                changed.append("lease_total_consideration_cents")
        if changed:
            deal.save(update_fields=changed + ["updated_at"])
            log_activity(deal, "Lease economics updated", actor=actor)
        return bool(changed)
    if "price" not in data:
        return False
    cents = data["price"]
    if deal.is_closed:
        if deal.actual_closing_price_cents == cents:
            return False
        deal.actual_closing_price_cents = cents
        deal.save(update_fields=["actual_closing_price_cents", "updated_at"])
        log_activity(deal, "Closing price updated", actor=actor)
        return True
    if deal.executed_contract_price_cents == cents:
        return False
    if cents is None:
        term = deal.terms.filter(key="purchase_price", status=DealTerm.STATUS_ACTIVE).first()
        if term:
            term.status = DealTerm.STATUS_SUPERSEDED
            term.save(update_fields=["status"])
        services.sync_deal(deal, actor)
    else:
        services.set_term(deal, "purchase_price", cents, actor, note="Entered with the deal", recompute=False)
    return True


def _amount(value, unit, precision=2):
    if value is None:
        return None
    if value == int(value):
        text = f"${value:,.0f}"
    else:
        whole, fraction = f"{value:,.{precision}f}".split(".")
        text = "$" + whole + "." + fraction.rstrip("0").ljust(2, "0")
    return text + RATE_UNIT_SUFFIX.get(unit or "usd_total", "")


def rent_display(deal):
    """e.g. '$1,400/mo NNN'."""
    text = _amount(deal.lease_starting_rent, deal.lease_rent_unit, precision=4)
    if text and deal.lease_rent_basis:
        text += " " + str(LEASE_BASE_LABELS.get(deal.lease_rent_basis, deal.get_lease_rent_basis_display()))
    return text


def lease_details(deal):
    """(label, value) pairs for the optional lease economics that were entered."""
    rows = []
    if deal.lease_term_months is not None:
        rows.append((gettext_noop("Signed lease term (months)"), str(deal.lease_term_months)))
        rows.append((gettext_noop("Signed lease rent total"), _amount(Decimal(deal.lease_total_consideration_cents) / 100, None)
                     if deal.lease_total_consideration_cents is not None else gettext("Not entered")))
    if deal.lease_nnn_amount is not None:
        rows.append((gettext_noop("NNN charges"), _amount(deal.lease_nnn_amount, deal.lease_rent_unit)))
    if deal.lease_utility_amount is not None:
        rows.append((gettext_noop("Utilities"), _amount(deal.lease_utility_amount, deal.lease_utility_unit)))
    if deal.lease_area_sf is not None:
        rows.append((gettext_noop("Area (SF)"), f"{deal.lease_area_sf:,.0f}"))
    if deal.lease_free_rent_months is not None:
        rows.append((gettext_noop("Free rent (months)"), f"{deal.lease_free_rent_months.normalize():f}"))
    if deal.lease_ti_amount is not None:
        rows.append((gettext_noop("TI allowance"), _amount(deal.lease_ti_amount, None) + (gettext("/SF") if deal.lease_ti_unit == "usd_sf" else "")))
    if deal.lease_escalation_pct is not None:
        rows.append((gettext_noop("Annual escalation (%)"), f"{deal.lease_escalation_pct.normalize():f}%"))
    return rows


def headline(deal):
    """The price shown at the top of the deal and in lists, as text (or None)."""
    if deal.is_lease:
        return rent_display(deal)
    cents = deal.actual_closing_price_cents if deal.is_closed and deal.actual_closing_price_cents is not None \
        else deal.executed_contract_price_cents
    if cents is None:
        return None
    return f"${Decimal(cents) / 100:,.0f}" if cents % 100 == 0 else f"${Decimal(cents) / 100:,.2f}"
