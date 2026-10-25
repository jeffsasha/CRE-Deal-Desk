from django import forms
from django.utils.translation import gettext_lazy as _

from core.fields import MoneyField
from core.forms import DateInput, LocalizedForm
from .models import Paycheck


class MonthInput(forms.DateInput):
    # A year-month text field stays language-neutral across browser/OS locales.
    input_type = "text"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("format", "%Y-%m")
        super().__init__(*args, **kwargs)
        self.attrs.update({"placeholder": "YYYY-MM", "maxlength": 7, "pattern": r"[0-9]{4}-(0[1-9]|1[0-2])"})


class PaycheckForm(LocalizedForm):
    full_width = ("notes",)

    pay_month = forms.DateField(label=_("Salary month"), input_formats=["%Y-%m"], widget=MonthInput(),
                               help_text=_("The month worked, which may differ from the pay date."))
    net_pay = MoneyField(label=_("Net pay (after tax)"), required=True,
                         help_text=_("Enter the NET PAY amount, not gross wages or year-to-date totals."))
    paid_on = forms.DateField(label=_("Pay date"), required=False, widget=DateInput())
    check_number = forms.CharField(label=_("Check number"), max_length=60, required=False)
    hours = forms.DecimalField(label=_("Hours worked"), max_digits=7, decimal_places=2, min_value=0, max_value=744, required=False)
    employer = forms.CharField(label=_("Employer"), max_length=160, initial="SKW Realty LLC")
    notes = forms.CharField(label=_("Notes"), max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, owner, instance=None, **kwargs):
        self.owner = owner
        self.instance = instance
        if instance is not None and not args:
            kwargs["initial"] = {name: getattr(instance, name) for name in self.base_fields if name != "net_pay"}
            kwargs["initial"]["net_pay"] = instance.net_pay_cents
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if data.get("check_number") and data.get("employer"):
            matches = Paycheck.objects.filter(owner=self.owner, employer=data["employer"], check_number=data["check_number"])
            if self.instance:
                matches = matches.exclude(pk=self.instance.pk)
            if matches.exists():
                self.add_error("check_number", _("This check is already recorded, including archived records."))
        return data

    def save(self):
        row = self.instance or Paycheck(owner=self.owner)
        for name, value in self.cleaned_data.items():
            setattr(row, "net_pay_cents" if name == "net_pay" else name, value)
        row.full_clean()
        row.save()
        return row
