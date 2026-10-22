"""Small database-backed job queue.

`manage.py run_worker` processes queued jobs and due reminders. Views may also run a
job inline (e.g. "Process now"); failures are recorded on the job and never delete the
uploaded file or block manual entry.
"""
import logging
import traceback
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Job

log = logging.getLogger(__name__)

HANDLERS = {}


def handler(kind):
    def register(fn):
        HANDLERS[kind] = fn
        return fn

    return register


def enqueue(kind, **payload):
    return Job.objects.create(kind=kind, payload=payload)


def run_job(job):
    fn = HANDLERS.get(job.kind)
    job.attempts += 1
    job.status = Job.STATUS_RUNNING
    job.save(update_fields=["attempts", "status", "updated_at"])
    if fn is None:
        job.status = Job.STATUS_FAILED
        job.last_error = f"No handler registered for job kind '{job.kind}'."
        job.save(update_fields=["status", "last_error", "updated_at"])
        return job
    try:
        fn(**job.payload)
    except Exception as exc:  # noqa: BLE001 - recorded on the job for the UI
        log.exception("Job %s failed", job.pk)
        job.last_error = f"{exc}\n\n{traceback.format_exc(limit=5)}"
        if job.attempts >= job.max_attempts:
            job.status = Job.STATUS_FAILED
        else:
            job.status = Job.STATUS_QUEUED
            job.run_after = timezone.now() + timedelta(minutes=2 ** job.attempts)
        job.save(update_fields=["status", "last_error", "run_after", "updated_at"])
        return job
    job.status = Job.STATUS_SUCCEEDED
    job.last_error = ""
    job.save(update_fields=["status", "last_error", "updated_at"])
    return job


def run_pending(limit=20):
    done = []
    for _ in range(limit):
        with transaction.atomic():
            job = (
                Job.objects.select_for_update()
                .filter(status=Job.STATUS_QUEUED, run_after__lte=timezone.now())
                .order_by("created_at")
                .first()
            )
            if job is None:
                break
            job.status = Job.STATUS_RUNNING
            job.save(update_fields=["status", "updated_at"])
        done.append(run_job(job))
    return done
