from django import forms
from django.utils.translation import gettext_lazy

from core.forms import LocalizedForm, StyledModelForm
from core.models import HolidayCalendar, User
from deals.catalog import EVENT_CATALOG, TERM_CATALOG

from .models import Deadline


def _date_terms():
    return [("", "—")] + [(k, v[0]) for k, v in TERM_CATALOG.items() if v[1] == "date"]


def _day_terms():
    return [("", "— use the number of days entered above —")] + [(k, v[0]) for k, v in TERM_CATALOG.items() if v[1] == "days"]


class DeadlineForm(StyledModelForm):
    triggers = forms.MultipleChoiceField(required=False, label="Trigger event(s)",
                                         help_text="One event for 'days after'; two or more for 'later of' / 'earlier of'.")
    reminder_days_text = forms.CharField(required=False, label="Reminder lead times (days)",
                                         help_text="Comma-separated, e.g. 7, 3, 1, 0. Blank = workspace default.")
    fixed_date_term_key = forms.ChoiceField(required=False, choices=_date_terms, label="Date term")
    offset_term_key = forms.ChoiceField(required=False, choices=_day_terms, label="Take the number of days from term")

    class Meta:
        model = Deadline
        fields = ["name", "category", "is_contractual", "rule_type", "fixed_date", "fixed_date_term_key", "triggers",
                  "offset_days", "offset_term_key", "day_basis", "include_trigger_day", "holiday_calendar",
                  "weekend_rule", "weekend_rule_source", "due_time", "time_zone", "source_clause", "responsible_user", "responsible_party", "confirmation",
                  "reminder_days_text"]
        help_texts = {
            "weekend_rule": "Leave 'No adjustment' unless the contract establishes one. A Sunday deadline is not moved to Monday by default.",
            "include_trigger_day": "Most contracts exclude the trigger day. Check only if the contract counts it.",
            "offset_days": "Number of days stated in the contract.",
        }

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.deal = deal or (self.instance.deal if self.instance.pk else None)
        events = list(EVENT_CATALOG.items())
        if self.deal is not None:
            for key in self.deal.events.values_list("key", flat=True):
                if key not in EVENT_CATALOG:
                    events.append((key, key))
            others = self.deal.deadlines.exclude(pk=self.instance.pk or 0).exclude(state__in=["superseded", "cancelled"])
            events += [(f"deadline:{d.pk}", f"Deadline: {d.name}") for d in others]
        self.fields["triggers"].choices = events
        self.fields["triggers"].widget.attrs["size"] = 6
        self.fields["responsible_user"].queryset = User.objects.filter(is_active=True).exclude(role="read_only")
        self.fields["holiday_calendar"].queryset = HolidayCalendar.objects.all()
        if self.instance.pk:
            self.fields["triggers"].initial = self.instance.trigger_keys
            self.fields["reminder_days_text"].initial = ", ".join(str(x) for x in self.instance.reminder_days or [])

    def clean(self):
        data = super().clean()
        rt = data.get("rule_type")
        triggers = data.get("triggers") or []
        if rt == "fixed" and not data.get("fixed_date"):
            self.add_error("fixed_date", gettext_lazy("Enter the fixed date."))
        if rt == "fixed_term" and not data.get("fixed_date_term_key"):
            self.add_error("fixed_date_term_key", gettext_lazy("Choose the contract term that holds the date."))
        if rt == "offset" and len(triggers) != 1:
            self.add_error("triggers", gettext_lazy("Choose exactly one trigger event."))
        if rt in {"later_of", "earlier_of"} and len(triggers) < 2:
            self.add_error("triggers", gettext_lazy("Choose at least two events."))
        if rt in {"offset", "later_of", "earlier_of"}:
            if data.get("offset_days") is None and not data.get("offset_term_key"):
                self.add_error("offset_days", gettext_lazy("Enter the number of days or choose the term that states it. No default period is applied."))
            if data.get("offset_days") is not None and data.get("offset_term_key"):
                self.add_error("offset_term_key", gettext_lazy("Use either a fixed number of days or a contract term, not both."))
        if data.get("weekend_rule") and data["weekend_rule"] != "none" and not data.get("weekend_rule_source"):
            self.add_error("weekend_rule_source", gettext_lazy("Cite the contract clause that establishes this adjustment."))
        if data.get("day_basis") == "business" and not data.get("holiday_calendar"):
            self.add_error("holiday_calendar", gettext_lazy("Business-day counting needs a holiday calendar (choose 'No holidays' if none apply)."))
        if data.get("confirmation") == "confirmed" and not (data.get("source_clause") or data.get("source_version")):
            self.add_error("confirmation", gettext_lazy("A confirmed rule needs its source clause or document."))
        text = data.get("reminder_days_text", "")
        try:
            data["reminder_days"] = sorted({int(x) for x in text.split(",") if x.strip()}, reverse=True) if text else []
        except ValueError:
            self.add_error("reminder_days_text", gettext_lazy("Use whole numbers separated by commas."))
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.trigger_keys = self.cleaned_data.get("triggers") or []
        obj.reminder_days = self.cleaned_data.get("reminder_days", [])
        obj.fixed_date_term_key = self.cleaned_data.get("fixed_date_term_key") or ""
        obj.offset_term_key = self.cleaned_data.get("offset_term_key") or ""
        if self.deal is not None:
            obj.deal = self.deal
        if commit:
            obj.save()
        return obj


class StateForm(LocalizedForm):
    state = forms.ChoiceField(choices=[("open", "Open"), ("satisfied", "Satisfied / performed"), ("waived", "Waived"),
                                       ("expired", "Passed without action"), ("cancelled", "Cancelled / not applicable")])
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}),
                           help_text="E.g. who performed, and the evidence. Required for waived or cancelled.")

    def clean(self):
        data = super().clean()
        if data.get("state") in {"waived", "cancelled"} and not data.get("note"):
            self.add_error("note", gettext_lazy("Explain the waiver or cancellation."))
        return data
