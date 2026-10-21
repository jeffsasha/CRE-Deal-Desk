"""Historical import: mapping, validation, unknown commission, LOI protection,
duplicate detection and safe batch reversal."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from commissions.models import CommissionAgreement
from deals.models import Activity, Deal
from imports import services
from properties.models import Property
from reports import services as r

from .base import DeskTestCase

HEADER = "Deal name,Type,Status,Property,Address,City,Closing date,Closing price,Commission,Commission received,Received date\n"


def csv_file(body, name="deals.csv"):
    return SimpleUploadedFile(name, (HEADER + body).encode(), content_type="text/csv")


class ImportTests(DeskTestCase):
    def setUp(self):
        self.admin = self.user("admin")
        self.y = timezone.localdate().year - 1

    def run_import(self, body):
        batch = services.create_batch(csv_file(body), "deals", self.admin)
        services.validate_batch(batch)
        return batch

    def test_known_price_unknown_commission(self):
        batch = self.run_import(f"Hist sale,Sale,Closed,Bldg,77 Example Blvd,Houston,{self.y}-05-14,\"$1,975,000.00\",,,\n")
        row = batch.rows.get()
        self.assertEqual(row.status, "valid")
        self.assertTrue(any("remain unknown" in w for w in row.warnings))
        services.commit_batch(batch, self.admin)
        deal = Deal.objects.get(name="Hist sale")
        self.assertEqual(deal.actual_closing_price_cents, 197500000)
        self.assertFalse(CommissionAgreement.objects.filter(deal=deal).exists())
        f = r.filters_from_params({"year": self.y})
        self.assertIn(deal, r.closed_without_commission(f)["deals"])
        self.assertEqual(deal.source_reference, "deals.csv row 2")
        self.assertEqual(deal.import_batch, batch)

    def test_loi_and_closed_without_date(self):
        batch = self.run_import("Prop,Purchase,LOI,,,,,,,,\nNo date,Sale,Closed,,,,,$500,,,\nCounter,Sale,Closed (counteroffer),,,,2020-01-01,$1,,,\n")
        rows = {r.mapped["deal_name"]: r for r in batch.rows.all()}
        self.assertEqual(rows["Prop"].mapped["stage"], "loi")
        self.assertEqual(rows["No date"].status, "invalid")
        self.assertEqual(rows["Counter"].status, "invalid")
        services.commit_batch(batch, self.admin)
        self.assertEqual(Deal.objects.get(name="Prop").stage.key, "loi")
        self.assertFalse(Deal.objects.filter(name="No date").exists())

    def test_receipt_requires_date(self):
        batch = self.run_import(f"X,Sale,Closed,,,,{self.y}-01-01,$1,$100,$100,\n")
        self.assertEqual(batch.rows.get().status, "invalid")

    def test_duplicates_in_file_and_existing(self):
        batch = self.run_import(f"Dup,Sale,Closed,B,1 A St,Houston,{self.y}-01-01,$1,,,\nDup,Sale,Closed,B,1 A St,Houston,{self.y}-01-01,$1,,,\n")
        rows = list(batch.rows.all())
        self.assertEqual(rows[0].status, "valid")
        self.assertEqual(rows[1].status, "invalid")
        services.commit_batch(batch, self.admin)
        again = self.run_import(f"Dup,Sale,Closed,B,1 A Street,Houston,{self.y}-01-01,$1,,,\n")
        row = again.rows.get()
        self.assertIn("Possible duplicate", row.duplicate_note)
        self.assertEqual(row.action, "skip")
        # The property is matched by normalized address, not duplicated.
        self.assertEqual(row.matches["property"][0], Property.objects.get(street="1 A St").pk)

    def test_revert_only_untouched_records(self):
        batch = self.run_import(
            f"Keep,Sale,Closed,P1,10 One St,Houston,{self.y}-01-01,$1,$5,$5,{self.y}-01-05\n"
            f"Remove,Sale,Closed,P2,20 Two St,Houston,{self.y}-01-02,$2,,,\n")
        services.commit_batch(batch, self.admin)
        unrelated = self.deal("Unrelated work")
        keep = Deal.objects.get(name="Keep")
        Activity.objects.create(deal=keep, kind="note", summary="Added after import", created_by=self.admin)
        reverted, blocked = services.revert_batch(batch, self.admin)
        self.assertEqual((reverted, blocked), (1, 1))
        self.assertTrue(Deal.objects.filter(name="Keep").exists())
        self.assertFalse(Deal.objects.filter(name="Remove").exists())
        self.assertFalse(Property.objects.filter(street="20 Two St").exists())
        self.assertTrue(Deal.objects.filter(pk=unrelated.pk).exists())
        batch.refresh_from_db()
        self.assertEqual(batch.status, "partially_reverted")

    def test_xlsx(self):
        import io

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Deal name", "Type", "Status", "Closing date", "Closing price"])
        ws.append(["Excel deal", "Lease", "Leased", f"{self.y}-03-01", 125000])
        buf = io.BytesIO()
        wb.save(buf)
        f = SimpleUploadedFile("deals.xlsx", buf.getvalue())
        batch = services.create_batch(f, "deals", self.admin)
        self.assertEqual(batch.mapping["deal_name"], "Deal name")
        services.validate_batch(batch)
        self.assertEqual(batch.rows.get().status, "valid")
