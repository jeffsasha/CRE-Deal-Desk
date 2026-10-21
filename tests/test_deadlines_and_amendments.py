"""Receipt-triggered deadlines, ambiguous effective dates, amendments (executed vs
unsigned), revision history and reminder replacement."""
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from deadlines.models import Reminder
from deadlines.services import create_deadline, generate_standard_deadlines
from deals.models import DealEvent
from deals.services import record_event, set_term
from demo import pdf, samples
from documents import services as docs
from documents.processing import read_text, run_extraction

from .base import DeskTestCase


class ReceiptTriggerTests(DeskTestCase):
    def setUp(self):
        self.broker = self.user("broker")
        self.deal = self.deal(actor=self.broker, responsible_broker=self.broker)
        set_term(self.deal, "title_objection_days", 10, self.broker)
        self.objection = create_deadline(actor=self.broker, deal=self.deal, name="Objection deadline", category="title",
                                         rule_type="later_of", trigger_keys=["title_commitment_received", "survey_received"],
                                         offset_term_key="title_objection_days")

    def test_awaiting_until_receipts_recorded(self):
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.computation, "awaiting_trigger")
        self.assertIsNone(self.objection.current_date)
        record_event(self.deal, "title_commitment_received", date(2026, 3, 4), self.broker, evidence_note="email")
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.computation, "awaiting_trigger")  # survey still missing
        record_event(self.deal, "survey_received", date(2026, 3, 9), self.broker, evidence_note="email")
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.computation, "computed")
        self.assertEqual(self.objection.current_date, date(2026, 3, 19))

    def test_upload_date_is_not_a_receipt(self):
        # Uploading a title commitment does not record the receipt event.
        f = SimpleUploadedFile("commitment.pdf", pdf.text_pdf([["COMMITMENT FOR TITLE INSURANCE", "Schedule B"]]))
        docs.upload(f, self.broker, title="Commitment", category="title", deal=self.deal, process=False)
        self.assertFalse(DealEvent.objects.filter(deal=self.deal, key="title_commitment_received").exists())
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.computation, "awaiting_trigger")

    def test_unconfirmed_receipt_needs_review(self):
        record_event(self.deal, "title_commitment_received", date(2026, 3, 4), self.broker, status="needs_review")
        record_event(self.deal, "survey_received", date(2026, 3, 9), self.broker, evidence_note="x")
        self.objection.refresh_from_db()
        self.assertEqual(self.objection.computation, "needs_review")
        self.assertIsNone(self.objection.current_date)

    def test_confirmed_event_requires_date(self):
        with self.assertRaises(ValidationError):
            record_event(self.deal, "survey_received", None, self.broker)


class GenerateDeadlinesTests(DeskTestCase):
    def test_only_approved_terms_generate_deadlines(self):
        broker = self.user("broker")
        deal = self.deal(actor=broker)
        set_term(deal, "feasibility_period_days", 45, broker)
        created, skipped = generate_standard_deadlines(deal, broker)
        self.assertEqual([d.template_key for d in created], ["feasibility_expiration"])
        self.assertTrue(any("not approved" in s for s in skipped))
        self.assertEqual(created[0].computation, "awaiting_trigger")  # no effective date


class AmendmentFlowTests(DeskTestCase):
    """Uses the sample contract documents end to end (text-layer PDFs)."""

    def setUp(self):
        self.today = timezone.localdate()
        self.o = samples.offsets(self.today)
        self.broker = self.user("broker", email="b@example.invalid")
        self.deal = self.deal(name="Gessner", actor=self.broker, responsible_broker=self.broker)
        v = self._upload(samples.executed_contract(self.o["d_effective"], self.o["d_closing"]), "contract.pdf", "contract")
        run = self._extract(v)
        docs.set_execution_status(v, "confirmed_executed", self.broker, "signed copy")
        for f in run.fields.filter(review_status="pending"):
            docs.review_field(f, self.broker, "accept")
        docs.publish(run, self.deal, self.broker)
        generate_standard_deadlines(self.deal, self.broker)
        self.closing = self.deal.deadlines.get(template_key="closing_fixed")
        self.feas = self.deal.deadlines.get(template_key="feasibility_expiration")

    def _upload(self, pages, name, category):
        f = SimpleUploadedFile(name, pdf.text_pdf(pages))
        v, _ = docs.upload(f, self.broker, title=name, category=category, deal=self.deal, process=False)
        return v

    def _extract(self, v):
        read_text(v)
        v.refresh_from_db()
        run = run_extraction(v, actor_id=self.broker.pk)
        self.assertEqual(run.status, "succeeded", run.error)
        return run

    def _prepare(self, pages, name):
        v = self._upload(pages, name, "amendment")
        run = self._extract(v)
        self.assertIn(v.document.doc_type, {"amendment", "extension"})
        for f in run.fields.filter(review_status="pending"):
            docs.review_field(f, self.broker, "accept")
        return v, docs.prepare_amendment(run, self.deal, self.broker)

    def test_base_contract_published(self):
        self.deal.refresh_from_db()
        self.assertEqual(self.deal.effective_date, self.o["d_effective"])
        self.assertEqual(self.deal.contractual_closing_date, self.o["d_closing"])
        self.assertEqual(self.deal.executed_contract_price_cents, 285000000)
        self.assertEqual(self.feas.current_date, self.o["d_effective"] + timedelta(days=45))

    def test_unsigned_extension_does_not_change_closing(self):
        v, amendment = self._prepare(samples.unsigned_extension(self.o["d_unsigned_closing"]), "ext.pdf")
        self.assertEqual(v.execution_status, "draft")
        with self.assertRaises(ValidationError):
            docs.apply_amendment(amendment, self.broker)
        self.closing.refresh_from_db()
        self.deal.refresh_from_db()
        self.assertEqual(self.closing.current_date, self.o["d_closing"])
        self.assertEqual(self.deal.contractual_closing_date, self.o["d_closing"])
        self.assertEqual(amendment.status, "proposed")
        # The preview shows the effect without applying it.
        changed = [p for p in amendment.preview if p["changed"]]
        self.assertTrue(any(p["new_date"] == self.o["d_unsigned_closing"].isoformat() for p in changed))

    def test_unsigned_base_contract_cannot_publish(self):
        v = self._upload(samples.executed_contract(self.o["d_effective"], self.o["d_closing"]), "copy.pdf", "contract")
        docs.set_execution_status(v, "draft", self.broker)
        run = self._extract(v)
        with self.assertRaises(ValidationError):
            docs.publish(run, self.deal, self.broker)

    def test_executed_amendment_updates_dates_and_preserves_history(self):
        reminders_before = set(Reminder.objects.filter(deadline=self.closing, status="scheduled").values_list("pk", flat=True))
        self.assertTrue(reminders_before)
        v, amendment = self._prepare(samples.first_amendment(self.o["d_amended_closing"]), "amend.pdf")
        docs.set_execution_status(v, "confirmed_executed", self.broker, "DocuSign completed")
        docs.apply_amendment(amendment, self.broker)
        self.closing.refresh_from_db()
        self.feas.refresh_from_db()
        self.assertEqual(self.closing.current_date, self.o["d_amended_closing"])
        self.assertEqual(self.closing.original_date, self.o["d_closing"])
        self.assertEqual(self.feas.current_date, self.o["d_effective"] + timedelta(days=60))
        # Superseded terms are kept.
        old = self.deal.terms.get(key="closing_date", status="superseded")
        self.assertEqual(old.value_date, self.o["d_closing"])
        new = self.deal.terms.get(key="closing_date", status="active")
        self.assertEqual(new.amendment, amendment)
        # Revision history records the change and the amendment.
        rev = self.closing.revisions.first()
        self.assertEqual((rev.previous_date, rev.new_date, rev.amendment), (self.o["d_closing"], self.o["d_amended_closing"], amendment))
        # Old reminders are cancelled, not deleted; new ones scheduled for the new date.
        old_reminders = Reminder.objects.filter(pk__in=reminders_before)
        self.assertEqual(old_reminders.count(), len(reminders_before))
        self.assertTrue(all(r.status == "cancelled" and "Superseded" in r.cancelled_reason for r in old_reminders))
        self.assertTrue(Reminder.objects.filter(deadline=self.closing, status="scheduled", target_revision=self.closing.revision).exists())


class AmbiguousEffectiveDateTests(DeskTestCase):
    def test_definition_by_event_leaves_effective_date_unresolved(self):
        from documents.extraction import pattern, safeguards

        o = samples.offsets(timezone.localdate())
        pages = ["\n".join(p) for p in samples.ambiguous_contract(o["c_signed_seller"], o["c_signed_buyer"])]
        out = pattern.extract(pages, "purchase_contract")
        results = safeguards.apply(out.proposals, pages, "purchase_contract")
        eff = [(p, st) for p, _v, st in results if p.key == "effective_date"]
        self.assertEqual(len(eff), 1)
        proposal, status = eff[0]
        self.assertEqual(proposal.value, "")
        self.assertEqual(status, "needs_review")
        self.assertTrue(any("signature date is not automatically the effective date" in f for f in proposal.flags))

    def test_review_cannot_accept_empty_effective_date(self):
        broker = self.user("broker")
        deal = self.deal(actor=broker)
        o = samples.offsets(timezone.localdate())
        f = SimpleUploadedFile("c.pdf", pdf.text_pdf(samples.ambiguous_contract(o["c_signed_seller"], o["c_signed_buyer"])))
        v, _ = docs.upload(f, broker, title="c", category="contract", deal=deal, process=False)
        read_text(v)
        v.refresh_from_db()
        run = run_extraction(v)
        eff = run.fields.get(key="effective_date")
        with self.assertRaises(ValidationError):
            docs.review_field(eff, broker, "accept")
        docs.set_execution_status(v, "confirmed_executed", broker, "signed")
        for fld in run.fields.filter(review_status="pending"):
            docs.review_field(fld, broker, "accept")
        docs.publish(run, deal, broker)
        self.assertFalse(DealEvent.objects.filter(deal=deal, key="effective_date").exists())
        generate_standard_deadlines(deal, broker)
        self.assertTrue(deal.deadlines.exists())
        self.assertFalse(deal.deadlines.filter(current_date__isnull=False).exists())
