"""Background jobs. Slow OCR/LLM work runs here, never inside a web request.

With CELERY_BROKER_URL set (Docker Compose), jobs go through Redis to a Celery worker:
    celery -A sensedoc.worker worker --loglevel=info
Without it (local demo), the API runs the same function in a background thread.
"""

from celery import Celery

from sensedoc import config
from sensedoc.pipeline import process_document

celery_app = Celery("sensedoc", broker=config.CELERY_BROKER_URL or "memory://")
celery_app.conf.task_acks_late = True  # a job is only removed from the queue once it finished
celery_app.conf.worker_prefetch_multiplier = 1  # one slow LLM job at a time per worker process


@celery_app.task(autoretry_for=(Exception,), retry_backoff=True, max_retries=2)
def process_document_task(document_id: int) -> str:
    return process_document(document_id)


def enqueue(document_id: int, background_tasks) -> None:
    if config.CELERY_BROKER_URL:
        process_document_task.delay(document_id)
    else:
        background_tasks.add_task(process_document, document_id)
