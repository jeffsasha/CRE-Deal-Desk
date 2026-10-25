from django import forms
from django.utils.translation import gettext_lazy

from core.forms import LocalizedForm


class StateForm(LocalizedForm):
    state = forms.ChoiceField(label="Status", choices=[("open", "Open"), ("satisfied", "Satisfied / performed"), ("waived", "Waived"),
                                       ("expired", "Passed without action"), ("cancelled", "Cancelled / not applicable")])
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}),
                           help_text="E.g. who performed, and the evidence. Required for waived or cancelled.")

    def clean(self):
        data = super().clean()
        if data.get("state") in {"waived", "cancelled"} and not data.get("note"):
            self.add_error("note", gettext_lazy("Explain the waiver or cancellation."))
        return data
