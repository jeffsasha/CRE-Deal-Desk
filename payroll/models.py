from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.models import Archivable, TimeStamped


class Paycheck(TimeStamped, Archivable):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="paychecks")
    pay_month = models.DateField(_("Salary month"))
    paid_on = models.DateField(_("Pay date"), null=True, blank=True)
    net_pay_cents = models.BigIntegerField(validators=[MinValueValidator(0)])
    hours = models.DecimalField(_("Hours worked"), max_digits=7, decimal_places=2, null=True, blank=True,
                               validators=[MinValueValidator(0)])
    employer = models.CharField(_("Employer"), max_length=160, default="SKW Realty LLC")
    check_number = models.CharField(_("Check number"), max_length=60, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    source_reference = models.CharField(max_length=255, blank=True, editable=False)

    class Meta:
        ordering = ["-pay_month", "-paid_on", "-pk"]
        indexes = [models.Index(fields=["owner", "pay_month"])]
        constraints = [
            models.CheckConstraint(condition=Q(net_pay_cents__gte=0), name="salary_net_pay_nonnegative"),
            models.UniqueConstraint(fields=["owner", "employer", "check_number"],
                                    condition=~Q(check_number=""), name="salary_owner_employer_check_unique"),
        ]

    def clean(self):
        super().clean()
        if self.pay_month and self.pay_month.day != 1:
            raise ValidationError({"pay_month": _("Choose the salary month, without a day.")})

    def get_absolute_url(self):
        return reverse("salary_list") + f"?year={self.pay_month.year}"

    def __str__(self):
        return f"Paycheck {self.pk or 'new'}"
