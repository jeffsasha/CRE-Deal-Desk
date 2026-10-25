from datetime import date

from django import forms
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from core.fields import MoneyField
from core.forms import LocalizedForm
from .models import Paycheck


class YearMonthWidget(forms.MultiWidget):
    def __init__(self, attrs=None):
        years = [("", _("Year"))] + [(year, str(year)) for year in range(timezone.localdate().year + 5, 2024, -1)]
        months = [("", _("Month"))] + [(month, f"{month:02d}") for month in range(1, 13)]
        super().__init__([forms.Select(choices=years, attrs={"aria-label": _("Year")}),
                          forms.Select(choices=months, attrs={"aria-label": _("Month")})], attrs)

    def decompress(self, value):
        return [value.year, value.month] if value else [None, None]

    def id_for_label(self, id_):
        return f"{id_}_0" if id_ else ""

    def render(self, name, value, attrs=None, renderer=None):
        return format_html('<div class="salary-month-picker">{}</div>', super().render(name, value, attrs, renderer))


class SalaryMonthField(forms.MultiValueField):
    def __init__(self, **kwargs):
        super().__init__(fields=[forms.IntegerField(min_value=2025, max_value=9999),
                                 forms.IntegerField(min_value=1, max_value=12)], widget=YearMonthWidget(), **kwargs)

    def compress(self, values):
        return date(values[0], values[1], 1) if values else None


class PaycheckForm(LocalizedForm):
    full_width = ("notes",)

    pay_month = SalaryMonthField(label=_("Salary month"),
                                 help_text=_("Select the year and month the salary belongs to."))
    net_pay = MoneyField(label=_("Net pay (after tax)"), required=True,
                         help_text=_("Enter the NET PAY amount, not gross wages or year-to-date totals."))
    employer = forms.CharField(label=_("Employer"), max_length=160, initial="SKW Realty LLC")
    notes = forms.CharField(label=_("Notes"), max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, owner, instance=None, **kwargs):
        self.owner = owner
        self.instance = instance
        if instance is not None and not args:
            kwargs["initial"] = {name: getattr(instance, name) for name in self.base_fields if name != "net_pay"}
            kwargs["initial"]["net_pay"] = instance.net_pay_cents
        super().__init__(*args, **kwargs)

    def save(self):
        row = self.instance or Paycheck(owner=self.owner)
        for name, value in self.cleaned_data.items():
            setattr(row, "net_pay_cents" if name == "net_pay" else name, value)
        row.full_clean()
        row.save()
        return row
