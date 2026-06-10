import logging
from datetime import date, datetime, timedelta

from ..database import SessionLocal
from ..models import AnimalSubject, SyncLog
from .congress_api import CongressAPIClient
from .sync import process_bill, OUTCOME_INACTIVE

logger = logging.getLogger(__name__)

# Current congressional session targeted by the daily incremental sync.
CURRENT_CONGRESS = 119

# Must match AI_THRESHOLD in sync.py — process_bill() already enforces this during
# backfill and daily sync via the shared pipeline; this constant is kept for logging only.
ANIMAL_RELEVANCE_THRESHOLD = 40


def process_daily_sync():
    """Daily incremental sync for the current congress.

    Fetches bills updated yesterday using fromDateTime/toDateTime filters,
    then runs each through the shared process_bill pipeline.
    """
    # Look back 3 days so bills whose Congress.gov updateDate lags behind
    # their actual action date (typically 1-2 days) are still captured.
    # Hash dedup in process_bill makes re-fetching already-stored bills cheap.
    lookback_start = date.today() - timedelta(days=3)
    from_dt = f"{lookback_start.isoformat()}T00:00:00Z"
    to_dt = f"{date.today().isoformat()}T00:00:00Z"
    logger.info(f"Starting daily sync for Congress {CURRENT_CONGRESS}, range {from_dt} to {to_dt}.")

    db = SessionLocal()
    client = CongressAPIClient()

    sync_log = SyncLog(
        sync_type="daily_sync",
        status="running",
        congress=CURRENT_CONGRESS,
        start_time=datetime.now(),
        started_at=datetime.now(),
    )
    db.add(sync_log)
    db.commit()

    records_processed = 0
    active_bills_stored = 0
    inactive_bills_skipped = 0
    api_request_count = 0

    try:
        # Active animal subjects drive the matching rules (shared with backfill).
        active_subject_names = {
            s.subject_name
            for s in db.query(AnimalSubject).filter(AnimalSubject.active == True).all()
        }

        offset = 0
        limit = 200
        stop = False

        while not stop:
            response = client.fetch_bills(CURRENT_CONGRESS, offset=offset, limit=limit, from_date_time=from_dt, to_date_time=to_dt)
            api_request_count += 1

            bills = response.get("bills", [])
            if not bills:
                break

            for list_bill in bills:
                records_processed += 1
                result = process_bill(
                    db=db,
                    client=client,
                    list_bill=list_bill,
                    congress=CURRENT_CONGRESS,
                    active_subject_names=active_subject_names,
                )
                if result is None:
                    continue

                api_request_count += result.api_requests
                if result.outcome == OUTCOME_INACTIVE:
                    inactive_bills_skipped += 1
                elif result.stored:
                    score = result.document.relevance_score or 0
                    active_bills_stored += 1
                    logger.info(f"Daily sync {result.outcome} bill {result.source_id} (score={score}).")

            if len(bills) < limit:
                break
            offset += limit

        sync_log.status = "completed"
        sync_log.records_processed = records_processed
        sync_log.active_bills_stored = active_bills_stored
        sync_log.inactive_bills_skipped = inactive_bills_skipped
        sync_log.api_requests_made = api_request_count
        sync_log.error_message = (
            f"Daily sync completed. {records_processed} bills analyzed, "
            f"{active_bills_stored} stored/updated, {inactive_bills_skipped} inactive skipped."
        )
        sync_log.end_time = datetime.now()
        db.commit()
        logger.info(sync_log.error_message)

    except Exception as e:
        db.rollback()
        sync_log.status = "failed"
        sync_log.records_processed = records_processed
        sync_log.active_bills_stored = active_bills_stored
        sync_log.inactive_bills_skipped = inactive_bills_skipped
        sync_log.api_requests_made = api_request_count
        sync_log.error_message = str(e)
        sync_log.end_time = datetime.now()
        db.commit()
        logger.exception(f"Daily sync failed: {e}")
        raise
    finally:
        client.close()
        db.close()
