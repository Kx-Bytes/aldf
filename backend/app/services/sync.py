import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Set, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..models import LegislativeDocument, Subject, AnimalSubject, SyncLog
from .congress_api import CongressAPIClient
from .matching import match_bill, is_action_active

# Approved subjects list from requirements
APPROVED_SUBJECTS: List[str] = [
    "Animal and plant health",
    "Animal protection and human-animal relationships",
    "Aquaculture",
    "Aquatic ecology",
    "Birds",
    "Crimes against animals and natural resources",
    "Fishes",
    "Insects",
    "Livestock",
    "Mammals",
    "Reptiles",
    "Service animals",
    "Veterinary medicine and animal diseases",
    "Wildlife conservation and habitat protection",
    "Ecology",
    "Endangered and threatened species",
    "Environmental assessment, monitoring, research",
    "Forests, forestry, trees",
    "Land use and conservation",
    "Lakes and rivers",
    "Marine and coastal resources, fisheries",
    "Marine pollution",
    "Watersheds",
    "Wetlands",
    "Wilderness and natural areas, wildlife refuges, wild rivers, habitats",
    "Agricultural practices and innovations",
    "Agricultural research",
    "Hunting and fishing",
    "Outdoor recreation",
    "Pest management",
    "Food supply, safety, and labeling",
    "Meat",
    "Seafood",
    "Environmental health",
    "Infectious and parasitic diseases",
    "World health",
    "Human trafficking",
    "Smuggling and trafficking"
]

def parse_date(date_str: Optional[str]) -> Optional[date]:
    """Helper to parse date string YYYY-MM-DD safely."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except Exception:
        return None

def parse_datetime(datetime_str: Optional[str]) -> Optional[datetime]:
    """Helper to parse datetime strings safely, handling isoformat variations."""
    if not datetime_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            clean_str = datetime_str
            if clean_str.endswith("Z"):
                clean_str = clean_str[:-1] + "+00:00"
            return datetime.fromisoformat(clean_str)
        except Exception:
            continue
    return None

def seed_animal_subjects(db: Session) -> int:
    """
    Seeds the animal_subjects table with the approved subjects list.
    Returns the number of new subjects added.
    """
    added_count = 0
    for name in APPROVED_SUBJECTS:
        exists = db.query(AnimalSubject).filter(AnimalSubject.subject_name == name).first()
        if not exists:
            db.add(AnimalSubject(subject_name=name, active=True))
            added_count += 1
    if added_count > 0:
        db.commit()
    return added_count

def calculate_payload_hash(payload: Dict[str, Any]) -> str:
    """Generates SHA-256 source_hash from sorted, normalized payload representation."""
    normalized_json = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(normalized_json.encode("utf-8")).hexdigest()


# Outcomes returned by process_bill, describing what happened to a single bill.
OUTCOME_INACTIVE = "inactive"       # skipped (and deleted if previously stored)
OUTCOME_NO_MATCH = "no_match"       # active but not animal-related
OUTCOME_UNCHANGED = "unchanged"     # matched, already stored, hash identical
OUTCOME_UPDATED = "updated"         # matched, existing record refreshed
OUTCOME_INSERTED = "inserted"       # matched, new record created


@dataclass
class BillResult:
    """Result of processing a single bill through the shared pipeline."""
    outcome: str
    source_id: str
    api_requests: int = 0
    document: Optional[LegislativeDocument] = None

    @property
    def stored(self) -> bool:
        """True when the bill was newly inserted or updated (i.e. AI should run)."""
        return self.outcome in (OUTCOME_INSERTED, OUTCOME_UPDATED)


def process_bill(
    db: Session,
    client: CongressAPIClient,
    list_bill: Dict[str, Any],
    congress: int,
    active_subject_names: Set[str],
) -> Optional[BillResult]:
    """
    Process a single bill from a /bill/{congress} list response through the full
    pipeline: active-check -> subject match -> detail fetch -> hash dedup -> upsert.

    This is the single source of truth shared by the historical backfill and the
    daily incremental sync, so the two paths cannot drift apart.

    Commits to the DB on terminal outcomes. Returns a BillResult describing what
    happened, or None if the list entry was malformed (no type/number).
    """
    bill_number = list_bill.get("number") or list_bill.get("billNumber")
    bill_type = list_bill.get("type") or list_bill.get("billType")

    if not bill_number or not bill_type:
        return None

    bill_type_upper = bill_type.upper()
    source_id = f"{congress}-{bill_type_upper}-{bill_number}"
    api_requests = 0

    # Early filtering: skip bills whose latest action marks them INACTIVE.
    latest_action_obj = list_bill.get("latestAction", {}) or {}
    action_text = latest_action_obj.get("text")
    if not is_action_active(action_text):
        print(f"Skipping inactive bill {source_id} (Status: '{action_text}').")
        # Incremental sync: if a now-inactive bill exists in our DB, remove it.
        existing_doc = db.query(LegislativeDocument).filter(
            LegislativeDocument.source_id == source_id
        ).first()
        if existing_doc:
            print(f"Removing previously stored bill {source_id} because it has become INACTIVE.")
            db.delete(existing_doc)
            db.commit()
        return BillResult(OUTCOME_INACTIVE, source_id, api_requests)

    # Fetch subjects to evaluate matching rules.
    print(f"Checking subjects for {source_id}...")
    subjects_data = client.fetch_bill_subjects(congress, bill_type, bill_number)
    api_requests += 1

    subjects_obj = subjects_data.get("subjects", {})
    policy_area_obj = subjects_obj.get("policyArea", {})
    policy_area_name = policy_area_obj.get("name") if policy_area_obj else None

    legislative_subjects = subjects_obj.get("legislativeSubjects", [])
    subject_names = [sub.get("name") for sub in legislative_subjects if sub.get("name")]

    is_matched, _matched_subjects = match_bill(
        policy_area=policy_area_name,
        legislative_subjects=subject_names,
        active_animal_subjects=active_subject_names,
    )

    if not is_matched:
        return BillResult(OUTCOME_NO_MATCH, source_id, api_requests)

    print(f"Match found! Fetching full details for {source_id}...")
    detail_data = client.fetch_bill_details(congress, bill_type, bill_number)
    api_requests += 1
    bill_detail = detail_data.get("bill", {})

    title = bill_detail.get("title")
    origin_chamber = bill_detail.get("originChamber")
    introduced_date = parse_date(bill_detail.get("introducedDate"))
    source_url = bill_detail.get("legislationUrl") or bill_detail.get("url")

    detail_action_obj = bill_detail.get("latestAction", {}) or {}
    last_action_date = parse_date(detail_action_obj.get("actionDate"))
    last_action_text = detail_action_obj.get("text")

    update_date = parse_datetime(bill_detail.get("updateDate"))
    update_date_incl_text = parse_datetime(bill_detail.get("updateDateIncludingText"))

    # Parse sponsor details.
    sponsor_data = bill_detail.get("sponsor")
    if not sponsor_data and bill_detail.get("sponsors"):
        sponsors_list = bill_detail.get("sponsors")
        if sponsors_list:
            sponsor_data = sponsors_list[0]

    sponsor_name = None
    sponsor_party = None
    sponsor_state = None
    if sponsor_data:
        sponsor_name = sponsor_data.get("fullName") or f"{sponsor_data.get('firstName', '')} {sponsor_data.get('lastName', '')}".strip() or None
        sponsor_party = sponsor_data.get("party")
        sponsor_state = sponsor_data.get("state")

    # Sub-resource URLs.
    committees_url = bill_detail.get("committees", {}).get("url")
    summaries_url = bill_detail.get("summaries", {}).get("url")

    # Fetch the latest CRS summary text if available.
    official_summary = None
    if bill_detail.get("summaries", {}).get("count", 0):
        try:
            summaries_data = client.fetch_bill_summaries(congress, bill_type, bill_number)
            api_requests += 1
            summaries_list = summaries_data.get("summaries", [])
            if summaries_list:
                # Most recent summary is last in the list.
                raw_text = summaries_list[-1].get("text") or ""
                # Strip HTML tags and collapse whitespace.
                import re as _re
                official_summary = _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", raw_text)).strip() or None
        except Exception:
            pass  # Summary fetch is best-effort; don't fail the whole bill.

    # Normalize payload to generate hash.
    normalized_payload = {
        "source_id": source_id,
        "congress": congress,
        "bill_type": bill_type_upper,
        "bill_number": bill_number,
        "title": title,
        "introduced_date": str(introduced_date) if introduced_date else None,
        "origin_chamber": origin_chamber,
        "policy_area": policy_area_name,
        "last_action_date": str(last_action_date) if last_action_date else None,
        "last_action_text": last_action_text,
        "update_date": str(update_date) if update_date else None,
        "update_date_incl_text": str(update_date_incl_text) if update_date_incl_text else None,
        "sponsor_name": sponsor_name,
        "sponsor_party": sponsor_party,
        "sponsor_state": sponsor_state,
        "source_url": source_url,
        "committees_url": committees_url,
        "summaries_url": summaries_url,
        "subjects": sorted(subject_names),
        # Include summary text so a newly added/updated CRS summary triggers a re-sync and AI re-run.
        "official_summary": official_summary,
    }
    source_hash = calculate_payload_hash(normalized_payload)

    # Upsert logic.
    doc = db.query(LegislativeDocument).filter(
        LegislativeDocument.source_id == source_id
    ).first()

    if doc:
        if doc.source_hash == source_hash:
            print(f"Skipping update for {source_id} (hash unchanged).")
            return BillResult(OUTCOME_UNCHANGED, source_id, api_requests, doc)

        print(f"Updating details for {source_id} (hash changed).")
        doc.source_url = source_url
        doc.title = title
        doc.introduced_date = introduced_date
        doc.origin_chamber = origin_chamber
        doc.policy_area = policy_area_name
        doc.last_action_date = last_action_date
        doc.last_action_text = last_action_text
        doc.update_date = update_date
        doc.update_date_incl_text = update_date_incl_text
        doc.source_hash = source_hash
        doc.api_raw = bill_detail
        doc.official_summary = official_summary
        doc.updated_at = datetime.now()

        # Refresh subjects.
        doc.subjects.clear()
        for name in subject_names:
            subj = db.query(Subject).filter(Subject.name == name).first()
            if not subj:
                subj = Subject(name=name)
                db.add(subj)
                db.flush()
            doc.subjects.append(subj)
        outcome = OUTCOME_UPDATED
    else:
        print(f"Inserting new document {source_id}.")
        doc = LegislativeDocument(
            source_id=source_id,
            source="congress.gov",
            source_url=source_url,
            congress=congress,
            bill_type=bill_type_upper,
            bill_number=bill_number,
            title=title,
            introduced_date=introduced_date,
            origin_chamber=origin_chamber,
            policy_area=policy_area_name,
            last_action_date=last_action_date,
            last_action_text=last_action_text,
            update_date=update_date,
            update_date_incl_text=update_date_incl_text,
            source_hash=source_hash,
            api_raw=bill_detail,
            official_summary=official_summary,
        )
        db.add(doc)
        db.flush()

        for name in subject_names:
            subj = db.query(Subject).filter(Subject.name == name).first()
            if not subj:
                subj = Subject(name=name)
                db.add(subj)
                db.flush()
            doc.subjects.append(subj)
        outcome = OUTCOME_INSERTED

    db.commit()  # Save progress transactionally for this bill.

    # Fetch and store all actions for this bill into bill_actions table
    try:
        from ..models import BillAction
        actions_data = client.fetch_bill_actions(congress, bill_type_upper, bill_number)
        actions = actions_data.get("actions", [])
        # Delete existing actions for this doc to avoid duplicates on re-sync
        db.query(BillAction).filter(BillAction.document_id == doc.id).delete()
        for act in actions:
            action_date = parse_date(act.get("actionDate"))
            text = (act.get("text") or "").strip()
            if not action_date or not text:
                continue
            source_system = act.get("sourceSystem") or {}
            db.add(BillAction(
                document_id=doc.id,
                action_code=act.get("actionCode"),
                action_date=action_date,
                text=text,
                action_type=act.get("type"),
                source_system_code=source_system.get("code"),
                source_system_name=source_system.get("name"),
            ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Warning: failed to sync actions for {source_id}: {e}")

    # Run AI scoring immediately after saving; reject bills below threshold.
    AI_THRESHOLD = 40
    try:
        from .ai_processing import process_bill_ai
        process_bill_ai(doc, db=db)
        if doc.relevance_score is not None and doc.relevance_score < AI_THRESHOLD:
            print(f"AI score {doc.relevance_score} < {AI_THRESHOLD} for {source_id} — discarding.")
            db.delete(doc)
            db.commit()
            return BillResult(OUTCOME_NO_MATCH, source_id, api_requests)
        print(f"AI score {doc.relevance_score} for {source_id} — keeping.")
    except Exception as e:
        print(f"Warning: AI scoring failed for {source_id}: {e}. Keeping bill.")

    return BillResult(outcome, source_id, api_requests, doc)


def run_historical_backfill(
    db: Session, 
    congress: int, 
    max_bills: Optional[int] = None,
    resume_log_id: Optional[uuid.UUID] = None
) -> SyncLog:
    """
    Executes a historical backfill for the specified congress, checking bills,
    retrieving details for matched animal bills, and upserting records.
    Filters out INACTIVE bills early in the pipeline.
    Tracks and logs progress every 100 bills to standard output and sync_logs.
    Supports resuming from page-level and bill-level checkpoints.
    """
    import time
    import signal
    import sys
    import threading

    # 1. Create or load the SyncLog record
    if resume_log_id:
        sync_log = db.query(SyncLog).filter(SyncLog.id == resume_log_id).first()
        if not sync_log:
            raise ValueError(f"SyncLog with ID {resume_log_id} not found.")
        sync_log.status = "running"
        sync_log.end_time = None
        db.commit()
    else:
        log_id = uuid.uuid4()
        sync_log = SyncLog(
            id=log_id,
            sync_type=f"historical_backfill_congress_{congress}",
            status="running",
            congress=congress,
            records_processed=0,
            total_bills_discovered=0,
            last_processed_bill=None,
            last_processed_page=0,
            active_bills_stored=0,
            inactive_bills_skipped=0,
            api_requests_made=0,
            started_at=datetime.now(),
            start_time=datetime.now()
        )
        db.add(sync_log)
        db.commit()

    # 2. Get active animal subjects
    active_subjects = db.query(AnimalSubject).filter(AnimalSubject.active == True).all()
    active_subject_names = {s.subject_name for s in active_subjects}

    # Initialize counters from checkpoint or start fresh
    records_processed = sync_log.records_processed
    active_bills_stored = sync_log.active_bills_stored
    inactive_bills_skipped = sync_log.inactive_bills_skipped
    api_request_count = sync_log.api_requests_made
    total_bills_discovered = sync_log.total_bills_discovered
    
    offset = sync_log.last_processed_page
    limit = 100
    
    resume_mode = False
    resume_bill_id = None
    resume_offset = 0
    
    if resume_log_id and sync_log.last_processed_bill:
        resume_mode = True
        resume_bill_id = sync_log.last_processed_bill
        resume_offset = offset
        print(f"Resuming from checkpoint: Page Offset {offset}, Last Bill {resume_bill_id}")

    total_bills_analyzed = 0
    last_processed_bill = sync_log.last_processed_bill
    
    sync_start_time = time.time()
    client = CongressAPIClient()

    # Register signal handlers for clean interruption/cancellation
    def handle_sig(signum, frame):
        print(f"\nReceived signal {signum}. Marking job status...")
        try:
            # Re-fetch/update log in database
            db.rollback()
            log_to_update = db.query(SyncLog).filter(SyncLog.id == sync_log.id).first()
            if log_to_update:
                log_to_update.status = "cancelled" if signum == signal.SIGINT else "interrupted"
                log_to_update.end_time = datetime.now()
                log_to_update.last_processed_bill = last_processed_bill
                log_to_update.last_processed_page = offset
                log_to_update.records_processed = records_processed
                log_to_update.active_bills_stored = active_bills_stored
                log_to_update.inactive_bills_skipped = inactive_bills_skipped
                log_to_update.api_requests_made = api_request_count
                db.commit()
                print(f"Sync checkpoint saved: offset={offset}, last_processed_bill={last_processed_bill}")
        except Exception as db_err:
            print(f"Error saving interruption checkpoint to DB: {db_err}")
        sys.exit(128 + signum)

    in_main_thread = threading.current_thread() is threading.main_thread()
    if in_main_thread:
        old_sigterm = signal.signal(signal.SIGTERM, handle_sig)
        old_sigint = signal.signal(signal.SIGINT, handle_sig)
    
    try:
        has_more = True
        
        while has_more:
            print(f"Fetching bills page: offset={offset}, limit={limit}...")
            response = client.fetch_bills(congress=congress, offset=offset, limit=limit)
            api_request_count += 1
            
            # Record total bills discovered on first page fetch
            if total_bills_discovered == 0:
                total_bills_discovered = response.get("pagination", {}).get("count", 0)
                print(f"Total bills discovered for Congress {congress}: {total_bills_discovered}")
                # Save total bills discovered immediately to DB
                sync_log.total_bills_discovered = total_bills_discovered
                db.commit()
            
            bills_list = response.get("bills", [])
            
            if not bills_list:
                break
                
            for list_bill in bills_list:
                bill_number = list_bill.get("number") or list_bill.get("billNumber")
                bill_type = list_bill.get("type") or list_bill.get("billType")
                
                if not bill_number or not bill_type:
                    continue
                
                bill_type_upper = bill_type.upper()
                source_id = f"{congress}-{bill_type_upper}-{bill_number}"
                
                # Check bill-level resume mode
                if resume_mode and offset == resume_offset:
                    if source_id == resume_bill_id:
                        resume_mode = False
                        print(f"Found last processed bill {source_id}. Resuming normal processing.")
                    else:
                        print(f"Skipping already processed bill {source_id} (resume skip mode).")
                    continue

                if max_bills is not None and max_bills > 0 and total_bills_analyzed >= max_bills:
                    has_more = False
                    break
                    
                total_bills_analyzed += 1
                records_processed += 1
                last_processed_bill = source_id
                
                # Periodically log progress and save checkpoint every 100 bills
                if total_bills_analyzed % 100 == 0:
                    elapsed = time.time() - sync_start_time
                    time_per_bill = elapsed / total_bills_analyzed if total_bills_analyzed > 0 else 0
                    remaining = max(0, total_bills_discovered - records_processed)
                    est_remaining_sec = remaining * time_per_bill
                    est_remaining_min = est_remaining_sec / 60.0
                    
                    progress_msg = (
                        f"Progress: {records_processed}/{total_bills_discovered} analyzed. "
                        f"Matches stored: {active_bills_stored}. Inactive skipped: {inactive_bills_skipped}. "
                        f"API requests: {api_request_count}. Est remaining: {est_remaining_min:.1f}m."
                    )
                    print(f"\n[PROGRESS REPORT] {progress_msg}\n")
                    
                    # Update progress in DB sync_logs
                    sync_log.records_processed = records_processed
                    sync_log.active_bills_stored = active_bills_stored
                    sync_log.inactive_bills_skipped = inactive_bills_skipped
                    sync_log.api_requests_made = api_request_count
                    sync_log.last_processed_bill = source_id
                    sync_log.last_processed_page = offset
                    sync_log.error_message = progress_msg
                    db.commit()
                
                # Delegate the per-bill pipeline to the shared helper so the
                # backfill and daily sync stay in lockstep.
                result = process_bill(
                    db=db,
                    client=client,
                    list_bill=list_bill,
                    congress=congress,
                    active_subject_names=active_subject_names,
                )
                if result is None:
                    continue

                api_request_count += result.api_requests
                if result.outcome == OUTCOME_INACTIVE:
                    inactive_bills_skipped += 1
                elif result.stored:
                    active_bills_stored += 1
            
            if len(bills_list) < limit:
                has_more = False
            else:
                offset += limit
                
        # 3. Successful sync logging
        sync_log.status = "completed"
        sync_log.records_processed = records_processed
        sync_log.active_bills_stored = active_bills_stored
        sync_log.inactive_bills_skipped = inactive_bills_skipped
        sync_log.api_requests_made = api_request_count
        sync_log.last_processed_bill = last_processed_bill
        sync_log.last_processed_page = offset
        sync_log.error_message = f"Sync completed successfully. {records_processed} documents analyzed."
        sync_log.end_time = datetime.now()
        db.commit()
        
        # Output telemetry to stdout for validation
        print("\n" + "=" * 60)
        print("FILTERED SYNC EXECUTION SUMMARY")
        print("=" * 60)
        print(f"Total Bills Discovered:  {total_bills_discovered}")
        print(f"Total Bills Analyzed:    {records_processed}")
        print(f"Active Bills Stored:     {active_bills_stored}")
        print(f"Inactive Bills Skipped:  {inactive_bills_skipped}")
        print(f"API Requests Made:       {api_request_count}")
        print("=" * 60)
        
    except KeyboardInterrupt as e:
        db.rollback()
        sync_log.status = "cancelled"
        sync_log.records_processed = records_processed
        sync_log.active_bills_stored = active_bills_stored
        sync_log.inactive_bills_skipped = inactive_bills_skipped
        sync_log.api_requests_made = api_request_count
        sync_log.last_processed_bill = last_processed_bill
        sync_log.last_processed_page = offset
        sync_log.error_message = "Sync cancelled by user (KeyboardInterrupt)."
        sync_log.end_time = datetime.now()
        db.commit()
        print("\nSync cancelled by user.")
        raise e
    except Exception as e:
        db.rollback()
        sync_log.status = "failed"
        sync_log.records_processed = records_processed
        sync_log.active_bills_stored = active_bills_stored
        sync_log.inactive_bills_skipped = inactive_bills_skipped
        sync_log.api_requests_made = api_request_count
        sync_log.last_processed_bill = last_processed_bill
        sync_log.last_processed_page = offset
        sync_log.error_message = str(e)
        sync_log.end_time = datetime.now()
        db.commit()
        raise e
    finally:
        if in_main_thread:
            signal.signal(signal.SIGTERM, old_sigterm)
            signal.signal(signal.SIGINT, old_sigint)
        client.close()
        
    return sync_log

