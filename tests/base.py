import shutil
from pathlib import Path
import tempfile
from decimal import Decimal

from django.test import TestCase, override_settings

from core.models import User
from deals.models import Stage
from deals.services import create_deal
from properties.models import Property

_TMP = tempfile.mkdtemp(prefix="dealdesk-test-")


@override_settings(MEDIA_ROOT=_TMP, PRIVATE_STORAGE_ROOT=_TMP, EMAIL_CONFIGURED=False, AUTO_LOGIN=False, BRAND_DIR=Path(_TMP) / "brand")
class DeskTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TMP, ignore_errors=True)

    def user(self, role="broker", username=None, **extra):
        username = username or f"{role}-{User.objects.count() + 1}"
        u = User.objects.create(username=username, first_name=username.title(), role=role, **extra)
        u.set_password("x-test-password-123")
        u.save()
        return u

    def prop(self, name="Test Property", **kw):
        defaults = {"street": f"{abs(hash(name)) % 9999} Test St", "city": "Houston", "property_type": "retail"}
        defaults.update(kw)
        return Property.objects.create(name=name, **defaults)

    def deal(self, name="Test Deal", stage="under_contract", transaction_type="purchase", properties=None, actor=None, **kw):
        return create_deal(actor, properties=properties if properties is not None else [self.prop(name + " property")],
                           name=name, transaction_type=transaction_type, stage=Stage.objects.get(key=stage), **kw)


D = Decimal
