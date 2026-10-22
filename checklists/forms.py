from core.forms import StyledModelForm
from core.models import User
from crm.models import Contact

from .models import ChecklistItem, ChecklistTemplate, TemplateItem


class ChecklistItemForm(StyledModelForm):
    class Meta:
        model = ChecklistItem
        fields = ["title", "category", "status", "owner", "outside_party", "outside_party_note", "due_date", "deadline",
                  "depends_on", "requested_on", "received_on", "reviewed_on", "approved_on", "follow_up_on",
                  "not_applicable_reason", "blocked_reason", "unresolved_issues", "notes", "description"]
        help_texts = {
            "status": "Received does not mean reviewed or approved — each has its own status and date.",
        }

    def __init__(self, *args, deal=None, **kwargs):
        super().__init__(*args, **kwargs)
        deal = deal or self.instance.deal
        self.fields["owner"].queryset = User.objects.filter(is_active=True).exclude(role="read_only")
        self.fields["outside_party"].queryset = Contact.objects.active()
        self.fields["deadline"].queryset = deal.deadlines.exclude(state__in=["superseded", "cancelled"])
        self.fields["depends_on"].queryset = deal.checklist_items.exclude(pk=self.instance.pk or 0)


class TemplateForm(StyledModelForm):
    class Meta:
        model = ChecklistTemplate
        fields = ["name", "description", "enabled"]


class TemplateItemForm(StyledModelForm):
    class Meta:
        model = TemplateItem
        fields = ["category", "title", "order", "condition", "responsible_party_hint", "description"]
