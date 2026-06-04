import logging
from datetime import date, datetime, timedelta

from ..database import SessionLocal
from ..models import AnimalSubject, SyncLog
from .congress_api import CongressAPIClient
from .sync import process_bill, OUTCOME_INACTIVE
from .ai_processing import process_bill_ai

logger = logging.getLogger(__name__)

# Current congressional session targeted by the daily incremental sync.
CURRENT_CONGRESS = 119


def process_daily_sync():
    """Daily incremental sync for the current congress.

    Fetches bills whose latest action landed yesterday, then runs each through the
    shared ``process_bill`` pipeline (active-check -> animal match -> hash dedup ->
    upsert). Newly stored or updated bills are handed to the AI processing pipeline.

    Using the same ``process_bill`` as the historical backfill guarantees the two
    paths apply identical matching, filtering, and dedup rules.
    """
    yesterday = date.today() - timedelta(days=1)
    logger.info(f"Starting daily sync for Congress {CURRENT_CONGRESS}, action date {yesterday.isoformat()}.")

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
            # The list endpoint is sorted by latest action date (desc), so once we
            # page past yesterday we can stop early.
            response = client.fetch_bills(CURRENT_CONGRESS, offset=offset, limit=limit)
            api_request_count += 1

            bills = response.get("bills", [])
            if not bills:
                break

            for list_bill in bills:
                latest_action = list_bill.get("latestAction", {}) or {}
                action_date_str = latest_action.get("actionDate")
                if not action_date_str:
                    continue

                try:
                    action_date = date.fromisoformat(action_date_str[:10])
                except ValueError:
                    continue

                # Only bills updated yesterday; older entries mean we're done.
                if action_date < yesterday:
                    stop = True
                    break
                if action_date > yesterday:
                    continue

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
                    active_bills_stored += 1
                    logger.info(f"Daily sync {result.outcome} bill {result.source_id}.")
                    # Hand newly stored/updated bills to the AI pipeline.
                    process_bill_ai(result.document, db=db)

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
