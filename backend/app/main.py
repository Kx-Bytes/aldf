from __future__ import annotations
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import or_, func
from typing import Dict, Any, List, Optional
import csv
import os
from apscheduler.schedulers.background import BackgroundScheduler
from .services.daily_sync import process_daily_sync
from .database import SessionLocal
import io
import json
from datetime import date

from .database import get_db
from .models import LegislativeDocument, SyncLog, Base, Subject, UserProfile
from .services.sync import seed_animal_subjects, run_historical_backfill
from .services.matching import get_current_stage
from .services.ai_processing import process_bill_ai, expand_prompt_to_topics, score_against_prompt
from .services.congress_api import CongressAPIClient

app = FastAPI(
    title="Animal Legislation Tracking System - Congress.gov Backfill Module",
    version="1.0.0"
)

@app.on_event("startup")
def startup_event():
    from datetime import datetime
    db = next(get_db())
    try:
        seeded = seed_animal_subjects(db)
        print(f"Startup: Seeded {seeded} new animal subjects.")
        # Mark any sync logs stuck in 'running' as 'interrupted' (server restarted mid-run)
        stuck = db.query(SyncLog).filter(SyncLog.status == "running").all()
        for log in stuck:
            log.status = "interrupted"
            log.end_time = datetime.now()
            log.error_message = "Server restarted while sync was in progress."
        if stuck:
            db.commit()
            print(f"Startup: Marked {len(stuck)} interrupted sync log(s).")
    finally:
        db.close()
    # Start APScheduler for daily sync at midnight UTC
    import pytz
    scheduler = BackgroundScheduler(timezone=pytz.utc)
    scheduler.add_job(process_daily_sync, "cron", hour=0, minute=0)
    scheduler.start()


def extract_sponsor_info(api_raw: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Helper to dynamically extract sponsor details from raw api_raw response."""
    if not api_raw:
        return None, None, None
    
    # Check single sponsor field first
    sponsor_data = api_raw.get("sponsor")
    if not sponsor_data and api_raw.get("sponsors"):
        sponsors_list = api_raw.get("sponsors")
        if sponsors_list:
            sponsor_data = sponsors_list[0]
            
    if not sponsor_data:
        return None, None, None
        
    sponsor_name = sponsor_data.get("fullName") or f"{sponsor_data.get('firstName', '')} {sponsor_data.get('lastName', '')}".strip() or None
    sponsor_party = sponsor_data.get("party")
    sponsor_state = sponsor_data.get("state")
    return sponsor_name, sponsor_party, sponsor_state

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint verifying connection to PostgreSQL database.
    """
    try:
        # Check database connection
        db.execute(Base.metadata.tables["animal_subjects"].select().limit(1))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}

def _bg_backfill(congress: int, max_bills: Optional[int]):
    """Worker function for running backfill in background."""
    db = next(get_db())
    try:
        print(f"Starting background historical backfill for Congress {congress}...")
        run_historical_backfill(db, congress, max_bills)
        print(f"Background historical backfill for Congress {congress} finished.")
        try:
            from .services.cache import clear_cache
            clear_cache()
        except Exception as e:
            print(f"Failed to clear cache after backfill: {e}")
    except Exception as e:
        print(f"Background backfill for Congress {congress} failed: {e}")
    finally:
        db.close()

@app.post("/sync/backfill/{congress}")
def trigger_backfill(
    congress: int,
    background_tasks: BackgroundTasks,
    limit_bills: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Triggers historical sync for a given Congress in a background task.
    """
    if congress < 1 or congress > 200:
        raise HTTPException(status_code=400, detail="Invalid congress number")

    # Add backfill to background tasks
    background_tasks.add_task(_bg_backfill, congress, limit_bills)
    
    return {
        "message": f"Historical backfill for Congress {congress} started in background.",
        "limit_bills": limit_bills
    }

@app.get("/sync/logs", response_model=List[Dict[str, Any]])
def get_sync_logs(db: Session = Depends(get_db)):
    """
    Retrieves the most recent sync logs.
    """
    logs = db.query(SyncLog).order_by(SyncLog.start_time.desc()).limit(20).all()
    return [
        {
            "id": str(log.id),
            "sync_type": log.sync_type,
            "status": log.status,
            "records_processed": log.records_processed,
            "start_time": log.start_time.isoformat(),
            "end_time": log.end_time.isoformat() if log.end_time else None,
            "error_message": log.error_message
        }
        for log in logs
    ]

@app.get("/documents", response_model=List[Dict[str, Any]])
def get_documents(db: Session = Depends(get_db)):
    """
    Retrieves the most recently ingested animal legislative documents.
    """
    docs = db.query(LegislativeDocument).order_by(LegislativeDocument.ingested_at.desc()).limit(50).all()
    return [
        {
            "id": str(doc.id),
            "source_id": doc.source_id,
            "title": doc.title,
            "congress": doc.congress,
            "bill_type": doc.bill_type,
            "bill_number": doc.bill_number,
            "introduced_date": doc.introduced_date.isoformat() if doc.introduced_date else None,
            "policy_area": doc.policy_area,
            "current_stage": get_current_stage(doc.last_action_text),
            "last_action_text": doc.last_action_text,
            "ingested_at": doc.ingested_at.isoformat(),
            "subjects": [s.name for s in doc.subjects]
        }
        for doc in docs
    ]


@app.get("/documents/search")
def search_documents(
    keyword: Optional[str] = None,
    subject: Optional[str] = None,
    policy_area: Optional[str] = None,
    bill_type: Optional[str] = None,
    congress: Optional[int] = None,
    from_action_date: Optional[date] = None,
    to_action_date: Optional[date] = None,
    sort_by: str = "introduced_date",
    order: str = "desc",
    limit: int = 20,
    offset: int = 0,
    user_prompt: Optional[str] = None,
    user_email: Optional[str] = None,
    min_score: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Search and filter ingested legislative documents.
    """
    allowed_sort_fields = {
        "introduced_date": LegislativeDocument.introduced_date,
        "last_action_date": LegislativeDocument.last_action_date,
        "source_id": LegislativeDocument.source_id,
        "ingested_at": LegislativeDocument.ingested_at
    }
    
    if sort_by not in allowed_sort_fields:
        raise HTTPException(status_code=400, detail=f"Invalid sort field: {sort_by}")

    # Cache lookup
    from .services.cache import get_cache, set_cache, make_search_key
    params = {
        "keyword": keyword, "subject": subject, "policy_area": policy_area,
        "bill_type": bill_type, "congress": congress, 
        "from_action_date": from_action_date.isoformat() if from_action_date else None,
        "to_action_date": to_action_date.isoformat() if to_action_date else None, 
        "sort_by": sort_by, "order": order, "limit": limit, "offset": offset, 
        "user_prompt": user_prompt, "user_email": user_email, "min_score": min_score
    }
    cache_key = make_search_key(params)
    cached_res = get_cache(cache_key)
    if cached_res is not None:
        return cached_res
         
    query = db.query(LegislativeDocument)
    
    if keyword:
        query = query.filter(
            or_(
                LegislativeDocument.title.ilike(f"%{keyword}%"),
                LegislativeDocument.last_action_text.ilike(f"%{keyword}%"),
                LegislativeDocument.source_id.ilike(f"%{keyword}%")
            )
        )
    if subject:
        query = query.join(LegislativeDocument.subjects).filter(Subject.name.ilike(subject))
    if policy_area:
        query = query.filter(LegislativeDocument.policy_area.ilike(policy_area))
    if bill_type:
        query = query.filter(LegislativeDocument.bill_type.ilike(bill_type))
    if congress is not None:
        query = query.filter(LegislativeDocument.congress == congress)
    if from_action_date:
        query = query.filter(LegislativeDocument.last_action_date >= from_action_date)
    if to_action_date:
        query = query.filter(LegislativeDocument.last_action_date <= to_action_date)
         
    total = query.distinct().count()

    # Expand user prompt once, then use for scoring + filtering
    prompt_expansion = None
    expanded_topics = []
    expanded_keywords = []
    if user_prompt and user_prompt.strip():
        prompt_expansion = expand_prompt_to_topics(user_prompt.strip(), db=db, user_email=user_email)
        expanded_topics = prompt_expansion.get("topics", [])
        expanded_keywords = prompt_expansion.get("keywords", [])

    sort_col = allowed_sort_fields[sort_by]
    if order.lower() == "asc":
        query = query.order_by(sort_col.asc(), LegislativeDocument.id)
    else:
        query = query.order_by(sort_col.desc(), LegislativeDocument.id)

    # Fetch a larger pool when prompt filtering is active so we have enough after scoring
    fetch_limit = limit * 5 if prompt_expansion else limit
    results = query.distinct().offset(offset).limit(fetch_limit).all()

    formatted_results = []
    for doc in results:
        sp_name, sp_party, sp_state = extract_sponsor_info(doc.api_raw)
        prompt_score = score_against_prompt(doc, expanded_topics, expanded_keywords) if prompt_expansion else doc.relevance_score

        # Apply min_score filter using prompt_score when a prompt is active, else relevance_score
        effective_score = prompt_score if prompt_expansion else (doc.relevance_score or 0)
        if min_score is not None and effective_score < min_score:
            continue

        formatted_results.append({
            "id": str(doc.id),
            "source_id": doc.source_id,
            "title": doc.title,
            "congress": doc.congress,
            "bill_type": doc.bill_type,
            "bill_number": doc.bill_number,
            "introduced_date": doc.introduced_date.isoformat() if doc.introduced_date else None,
            "origin_chamber": doc.origin_chamber,
            "policy_area": doc.policy_area,
            "current_stage": get_current_stage(doc.last_action_text),
            "last_action_date": doc.last_action_date.isoformat() if doc.last_action_date else None,
            "last_action_text": doc.last_action_text,
            "update_date": doc.update_date.isoformat() if doc.update_date else None,
            "update_date_incl_text": doc.update_date_incl_text.isoformat() if doc.update_date_incl_text else None,
            "sponsor_name": sp_name,
            "sponsor_party": sp_party,
            "sponsor_state": sp_state,
            "source_url": doc.source_url,
            "ingested_at": doc.ingested_at.isoformat(),
            "updated_at": doc.updated_at.isoformat(),
            "subjects": [s.name for s in doc.subjects],
            "relevance_score": doc.relevance_score,
            "prompt_score": prompt_score,
            "relevance_topics": doc.relevance_topics,
            "ai_summary": doc.ai_summary,
        })

    # Re-sort by prompt_score desc when a prompt is active, then truncate to limit
    if prompt_expansion:
        formatted_results.sort(key=lambda r: r["prompt_score"], reverse=True)
    formatted_results = formatted_results[:limit]

    res = {
        "total": total,
        "limit": limit,
        "offset": offset,
        "prompt_expansion": prompt_expansion,
        "results": formatted_results
    }
    try:
        set_cache(cache_key, res, expire=300)
    except Exception as e:
        pass
    return res


@app.get("/documents/{source_id}/actions")
def get_document_actions(source_id: str, db: Session = Depends(get_db)):
    """Fetch the full action history for a bill live from Congress.gov and refresh the DB cache."""
    doc = db.query(LegislativeDocument).filter(LegislativeDocument.source_id == source_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        client = CongressAPIClient()
        result = client.fetch_bill_actions(doc.congress, doc.bill_type, doc.bill_number)
        actions = result.get("actions", [])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch actions from Congress.gov: {e}")
    # Persist the freshest action back to the DB so the card stays current
    if actions:
        latest = actions[0]
        action_date_str = latest.get("actionDate")
        action_text = latest.get("text")
        try:
            new_date = date.fromisoformat(action_date_str) if action_date_str else None
        except ValueError:
            new_date = None
        if new_date and action_text and (new_date != doc.last_action_date or action_text != doc.last_action_text):
            doc.last_action_date = new_date
            doc.last_action_text = action_text
            db.commit()
    return {"actions": actions}


@app.get("/documents/{source_id}")
def get_document_details(source_id: str, db: Session = Depends(get_db)):
    """
    Retrieve comprehensive details for a specific legislative document.
    """
    doc = db.query(LegislativeDocument).filter(LegislativeDocument.source_id == source_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    sp_name, sp_party, sp_state = extract_sponsor_info(doc.api_raw)
    return {
        "id": str(doc.id),
        "source_id": doc.source_id,
        "title": doc.title,
        "congress": doc.congress,
        "bill_type": doc.bill_type,
        "bill_number": doc.bill_number,
        "introduced_date": doc.introduced_date.isoformat() if doc.introduced_date else None,
        "origin_chamber": doc.origin_chamber,
        "policy_area": doc.policy_area,
        "current_stage": get_current_stage(doc.last_action_text),
        "last_action_date": doc.last_action_date.isoformat() if doc.last_action_date else None,
        "last_action_text": doc.last_action_text,
        "update_date": doc.update_date.isoformat() if doc.update_date else None,
        "update_date_incl_text": doc.update_date_incl_text.isoformat() if doc.update_date_incl_text else None,
        "sponsor_name": sp_name,
        "sponsor_party": sp_party,
        "sponsor_state": sp_state,
        "source_url": doc.source_url,
        "ingested_at": doc.ingested_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
        "source_hash": doc.source_hash,
        "subjects": [s.name for s in doc.subjects],
        "official_summary": doc.official_summary,
        "relevance_score": doc.relevance_score,
        "relevance_topics": doc.relevance_topics,
        "relevance_rationale": doc.relevance_rationale,
        "ai_summary": doc.ai_summary,
        "ai_generated_at": doc.ai_generated_at.isoformat() if doc.ai_generated_at else None,
        "api_raw": doc.api_raw
    }


@app.post("/ai/process/{source_id}")
def run_ai_for_bill(source_id: str, db: Session = Depends(get_db)):
    """Trigger AI scoring and summary generation for a single bill."""
    doc = db.query(LegislativeDocument).filter(LegislativeDocument.source_id == source_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    process_bill_ai(doc, db=db)
    try:
        from .services.cache import clear_cache
        clear_cache()
    except Exception as e:
        pass
    return {
        "source_id": doc.source_id,
        "relevance_score": doc.relevance_score,
        "relevance_topics": doc.relevance_topics,
        "relevance_rationale": doc.relevance_rationale,
        "ai_summary": doc.ai_summary,
        "ai_generated_at": doc.ai_generated_at.isoformat() if doc.ai_generated_at else None,
    }


def _bg_ai_backfill(force: bool):
    """Background worker: run AI pipeline on all bills missing AI output (or all if force=True)."""
    db = SessionLocal()
    try:
        query = db.query(LegislativeDocument)
        if not force:
            query = query.filter(LegislativeDocument.ai_generated_at == None)
        docs = query.all()
        total = len(docs)
        print(f"AI backfill: processing {total} bills (force={force}).")
        for i, doc in enumerate(docs, 1):
            process_bill_ai(doc, db=db)
            if i % 10 == 0:
                print(f"AI backfill progress: {i}/{total}")
        print(f"AI backfill complete: {total} bills processed.")
        try:
            from .services.cache import clear_cache
            clear_cache()
        except Exception as e:
            pass
    except Exception as e:
        print(f"AI backfill failed: {e}")
    finally:
        db.close()


@app.post("/search/live")
def live_search(
    body: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Search stored bill_actions by date and score results against a prompt."""
    from .models import BillAction
    from .services.ai_processing import expand_prompt_to_topics, score_against_prompt
    from datetime import date as date_type

    prompt = (body.get("prompt") or "").strip()
    search_date = (body.get("date") or "").strip() or None
    user_email = (body.get("user_email") or "").strip() or None

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    parsed_date = None
    if search_date:
        try:
            parsed_date = date_type.fromisoformat(search_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be in YYYY-MM-DD format")

    # Cache lookup
    from .services.cache import get_cache, set_cache, make_live_search_key
    cache_key = make_live_search_key({"prompt": prompt, "date": search_date, "user_email": user_email})
    cached_res = get_cache(cache_key)
    if cached_res is not None:
        return cached_res

    # Expand prompt (cached if user_email provided)
    expansion = expand_prompt_to_topics(prompt, db=db, user_email=user_email)
    topics = expansion.get("topics", [])
    keywords = expansion.get("keywords", [])

    from sqlalchemy import or_, cast, func, text as sa_text
    from sqlalchemy.dialects.postgresql import JSONB, ARRAY as PG_ARRAY
    from sqlalchemy.types import Text

    # Build a SQL pre-filter so we only load bills that plausibly match the prompt.
    # This avoids scoring every bill in Python — only the candidate set reaches Python.
    candidate_filters = []

    # Any stored relevance_topic overlaps with expanded topics (JSONB ?| operator)
    # The ?| operator requires text[] on the right side, not JSONB
    if topics:
        candidate_filters.append(
            LegislativeDocument.relevance_topics.cast(JSONB).op("?|")(
                cast(topics, PG_ARRAY(Text))
            )
        )

    # Title or policy_area contains any keyword (case-insensitive)
    for kw in keywords:
        candidate_filters.append(LegislativeDocument.title.ilike(f"%{kw}%"))
        candidate_filters.append(LegislativeDocument.policy_area.ilike(f"%{kw}%"))

    if parsed_date:
        # Date provided: restrict to bills with an action on that day, then apply
        # topic/keyword pre-filter on the joined documents.
        action_subq = (
            db.query(BillAction.document_id, BillAction.action_date, BillAction.text)
            .filter(BillAction.action_date == parsed_date)
            .distinct(BillAction.document_id)
            .subquery()
        )
        base_q = (
            db.query(LegislativeDocument, action_subq.c.action_date, action_subq.c.text)
            .join(action_subq, LegislativeDocument.id == action_subq.c.document_id)
            .options(selectinload(LegislativeDocument.subjects))
        )
        # Still apply topic/keyword filter when we have signals; otherwise return all
        # bills active on that date (user may be exploring).
        if candidate_filters:
            base_q = base_q.filter(or_(*candidate_filters))
        rows = base_q.all()
        docs_to_score = [
            (doc, action_date.isoformat(), action_text)
            for doc, action_date, action_text in rows
        ]
    else:
        # No date: pre-filter by topic/keyword match in SQL — never loads the full table.
        if not candidate_filters:
            # Prompt captured no topics or keywords; return nothing rather than full scan.
            return {"date": None, "prompt_expansion": expansion, "total": 0, "results": []}
        docs = (
            db.query(LegislativeDocument)
            .options(selectinload(LegislativeDocument.subjects))
            .filter(or_(*candidate_filters))
            .all()
        )
        docs_to_score = [
            (doc, doc.last_action_date.isoformat() if doc.last_action_date else None, doc.last_action_text)
            for doc in docs
        ]

    results = []
    for doc, action_date, action_text in docs_to_score:
        prompt_score = score_against_prompt(doc, topics, keywords)
        if prompt_score == 0:
            continue
        sp_name, sp_party, sp_state = extract_sponsor_info(doc.api_raw)
        results.append({
            "source_id": doc.source_id,
            "title": doc.title,
            "bill_type": doc.bill_type,
            "bill_number": doc.bill_number,
            "origin_chamber": doc.origin_chamber,
            "policy_area": doc.policy_area,
            "action_date": action_date,
            "action_text": action_text,
            "last_action_date": doc.last_action_date.isoformat() if doc.last_action_date else None,
            "last_action_text": doc.last_action_text,
            "subjects": [s.name for s in doc.subjects],
            "prompt_score": prompt_score,
            "relevance_score": doc.relevance_score,
            "ai_summary": doc.ai_summary,
            "source_url": doc.source_url,
            "current_stage": get_current_stage(doc.last_action_text),
            "sponsor_name": sp_name,
            "sponsor_party": sp_party,
            "sponsor_state": sp_state,
        })

    results.sort(key=lambda r: r["prompt_score"], reverse=True)

    res = {
        "date": search_date,
        "prompt_expansion": expansion,
        "total": len(results),
        "results": results,
    }
    try:
        set_cache(cache_key, res, expire=300)
    except Exception as e:
        pass
    return res


@app.post("/sync/backfill-actions")
def backfill_actions(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Backfill bill_actions for all existing stored bills."""
    def _run():
        from .models import BillAction
        from .services.sync import parse_date
        session = SessionLocal()
        client = CongressAPIClient()
        try:
            docs = session.query(LegislativeDocument).all()
            print(f"Backfilling actions for {len(docs)} bills...")
            for doc in docs:
                try:
                    data = client.fetch_bill_actions(doc.congress, doc.bill_type, doc.bill_number)
                    actions = data.get("actions", [])
                    session.query(BillAction).filter(BillAction.document_id == doc.id).delete()
                    for act in actions:
                        action_date = parse_date(act.get("actionDate"))
                        text = (act.get("text") or "").strip()
                        if not action_date or not text:
                            continue
                        source_system = act.get("sourceSystem") or {}
                        session.add(BillAction(
                            document_id=doc.id,
                            action_code=act.get("actionCode"),
                            action_date=action_date,
                            text=text,
                            action_type=act.get("type"),
                            source_system_code=source_system.get("code"),
                            source_system_name=source_system.get("name"),
                        ))
                    session.commit()
                except Exception as e:
                    session.rollback()
                    print(f"Failed actions for {doc.source_id}: {e}")
            print("Action backfill complete.")
        finally:
            client.close()
            session.close()
    background_tasks.add_task(_run)
    return {"message": "Action backfill started in background."}


@app.post("/sync/daily")
def trigger_daily_sync(background_tasks: BackgroundTasks):
    """Trigger the daily incremental sync manually (used by external cron on free hosting)."""
    background_tasks.add_task(process_daily_sync)
    return {"message": "Daily sync started in background."}


@app.post("/ai/backfill")
def trigger_ai_backfill(background_tasks: BackgroundTasks, force: bool = False):
    """Trigger AI processing for all stored bills that are missing AI output.
    Set force=true to regenerate even for bills that already have AI output.
    """
    background_tasks.add_task(_bg_ai_backfill, force)
    return {"message": "AI backfill started in background.", "force": force}


def _bg_purge_non_animal(threshold: int):
    """Background worker: delete bills whose AI relevance_score is below threshold.

    Bills with no AI output yet are scored first via process_bill_ai() so we
    don't blindly keep or delete un-scored records.
    """
    from .services.ai_processing import process_bill_ai as _process_ai
    db = SessionLocal()
    try:
        docs = db.query(LegislativeDocument).all()
        total = len(docs)
        deleted = 0
        scored = 0
        print(f"Purge: evaluating {total} bills against threshold={threshold}.")
        for doc in docs:
            # Run AI if not yet scored so we have a real score to judge
            if doc.relevance_score is None:
                _process_ai(doc, db=db)
                scored += 1
            # Skip deletion if AI scoring still failed — don't drop unscored bills
            if doc.relevance_score is None:
                print(f"Purge: skipping {doc.source_id} — AI scoring failed, keeping to be safe.")
                continue
            score = doc.relevance_score
            if score < threshold:
                print(f"Purge: deleting {doc.source_id} (score={score}).")
                db.delete(doc)
                db.commit()
                deleted += 1
        print(f"Purge complete: {deleted} bills deleted, {scored} newly scored, {total - deleted} kept.")
        try:
            from .services.cache import clear_cache
            clear_cache()
        except Exception as e:
            pass
    except Exception as e:
        db.rollback()
        print(f"Purge failed: {e}")
    finally:
        db.close()


@app.post("/admin/clear-all-data")
def clear_all_data(db: Session = Depends(get_db)):
    """Delete all bills, subjects, actions, and sync logs. Use before a clean backfill."""
    from .models import BillAction
    db.query(BillAction).delete()
    db.query(LegislativeDocument).delete()
    db.query(Subject).delete()
    db.query(SyncLog).delete()
    db.commit()
    try:
        from .services.cache import clear_cache
        clear_cache()
    except Exception as e:
        pass
    return {"message": "All data cleared. Ready for a fresh backfill."}


@app.post("/admin/purge-non-animal")
def purge_non_animal(background_tasks: BackgroundTasks, threshold: int = 30):
    """Delete all stored bills whose animal relevance_score is below `threshold` (default 30).

    Bills that haven't been AI-scored yet are scored first before the decision is made.
    Runs in the background — check server logs for progress.
    """
    background_tasks.add_task(_bg_purge_non_animal, threshold)
    return {
        "message": "Purge started in background.",
        "threshold": threshold,
        "note": "Bills with relevance_score < threshold will be permanently deleted. Check server logs for progress.",
    }


@app.post("/users", response_model=Dict[str, Any])
def create_user(body: Dict[str, Any], db: Session = Depends(get_db)):
    """Create or update a user profile with tracking preferences."""
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    profile = db.query(UserProfile).filter(UserProfile.email == email).first()
    prompt = body.get("prompt")

    if profile:
        # If prompt changed, clear the cached expansion so it gets re-expanded
        if prompt is not None and prompt != profile.prompt:
            profile.expanded_topics = None
        profile.prompt = prompt if prompt is not None else profile.prompt
        profile.frequency = body.get("frequency", profile.frequency)
        profile.scope = body.get("scope", profile.scope)
        profile.min_relevance_score = body.get("min_relevance_score", profile.min_relevance_score)
    else:
        profile = UserProfile(
            email=email,
            prompt=prompt,
            frequency=body.get("frequency", "daily"),
            scope=body.get("scope", "federal"),
            min_relevance_score=body.get("min_relevance_score", 70),
        )
        db.add(profile)

    db.commit()
    db.refresh(profile)
    try:
        from .services.cache import clear_cache
        clear_cache()
    except Exception as e:
        pass
    return _format_profile(profile)


@app.get("/users/{email}", response_model=Dict[str, Any])
def get_user(email: str, db: Session = Depends(get_db)):
    """Fetch a user's tracking preferences."""
    profile = db.query(UserProfile).filter(UserProfile.email == email.lower()).first()
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return _format_profile(profile)


@app.put("/users/{email}", response_model=Dict[str, Any])
def update_user(email: str, body: Dict[str, Any], db: Session = Depends(get_db)):
    """Update a user's tracking preferences."""
    profile = db.query(UserProfile).filter(UserProfile.email == email.lower()).first()
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")

    prompt = body.get("prompt")
    if prompt is not None and prompt != profile.prompt:
        profile.expanded_topics = None  # invalidate cache on prompt change
    if prompt is not None:
        profile.prompt = prompt
    if "frequency" in body:
        profile.frequency = body["frequency"]
    if "scope" in body:
        profile.scope = body["scope"]
    if "min_relevance_score" in body:
        profile.min_relevance_score = body["min_relevance_score"]
    if "review_bills" in body:
        profile.review_bills = body["review_bills"]

    db.commit()
    db.refresh(profile)
    try:
        from .services.cache import clear_cache
        clear_cache()
    except Exception as e:
        pass
    return _format_profile(profile)


def _format_profile(profile: UserProfile) -> Dict[str, Any]:
    return {
        "id": str(profile.id),
        "email": profile.email,
        "prompt": profile.prompt,
        "expanded_topics": profile.expanded_topics,
        "frequency": profile.frequency,
        "scope": profile.scope,
        "min_relevance_score": profile.min_relevance_score,
        "review_bills": profile.review_bills or [],
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


@app.get("/users/{email}/review-bills")
def get_review_bills(email: str, db: Session = Depends(get_db)):
    """Return full bill details for all bills the user has manually added to their review list."""
    profile = db.query(UserProfile).filter(UserProfile.email == email.lower()).first()
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")

    source_ids = profile.review_bills or []
    if not source_ids:
        return {"results": [], "total": 0}

    docs = (
        db.query(LegislativeDocument)
        .options(selectinload(LegislativeDocument.subjects))
        .filter(LegislativeDocument.source_id.in_(source_ids))
        .all()
    )
    results = []
    for doc in docs:
        sp_name, sp_party, sp_state = extract_sponsor_info(doc.api_raw)
        results.append({
            "id": str(doc.id),
            "source_id": doc.source_id,
            "title": doc.title,
            "congress": doc.congress,
            "bill_type": doc.bill_type,
            "bill_number": doc.bill_number,
            "introduced_date": doc.introduced_date.isoformat() if doc.introduced_date else None,
            "origin_chamber": doc.origin_chamber,
            "policy_area": doc.policy_area,
            "current_stage": get_current_stage(doc.last_action_text),
            "last_action_date": doc.last_action_date.isoformat() if doc.last_action_date else None,
            "last_action_text": doc.last_action_text,
            "sponsor_name": sp_name,
            "sponsor_party": sp_party,
            "sponsor_state": sp_state,
            "subjects": [s.name for s in doc.subjects],
            "relevance_score": doc.relevance_score,
            "relevance_topics": doc.relevance_topics,
            "ai_summary": doc.ai_summary,
        })
    return {"results": results, "total": len(results)}


@app.get("/subjects")
def list_subjects(db: Session = Depends(get_db)):
    """
    Lists subjects with the count of matched bills.
    """
    from .services.cache import get_cache, set_cache
    cache_key = "aldf:cache:subjects"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached
    results = db.query(
        Subject.name,
        func.count(LegislativeDocument.id).label("document_count")
    ).join(
        LegislativeDocument.subjects
    ).group_by(
        Subject.name
    ).order_by(
        func.count(LegislativeDocument.id).desc(),
        Subject.name
    ).all()
    
    res = [
        {"name": name, "document_count": count}
        for name, count in results
    ]
    try:
        set_cache(cache_key, res, expire=300)
    except Exception as e:
        pass
    return res


@app.get("/stats/overview")
def get_stats_overview(db: Session = Depends(get_db)):
    """
    Retrieve overview statistics for the active bills database.
    """
    from .services.cache import get_cache, set_cache
    cache_key = "aldf:cache:stats:overview"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached
    total_active_bills = db.query(LegislativeDocument).count()
    
    unique_subjects = db.query(Subject).join(LegislativeDocument.subjects).distinct().count()
    
    min_date, max_date = db.query(
        func.min(LegislativeDocument.introduced_date),
        func.max(LegislativeDocument.introduced_date)
    ).first()
    
    bill_types = db.query(
        LegislativeDocument.bill_type,
        func.count(LegislativeDocument.id)
    ).group_by(LegislativeDocument.bill_type).all()
    
    res = {
        "total_active_bills": total_active_bills,
        "unique_subjects": unique_subjects,
        "date_range": {
            "min_date": min_date.isoformat() if min_date else None,
            "max_date": max_date.isoformat() if max_date else None
        },
        "bills_by_bill_type": {bt: count for bt, count in bill_types}
    }
    try:
        set_cache(cache_key, res, expire=300)
    except Exception as e:
        pass
    return res


@app.get("/stats/policy-areas")
def get_stats_policy_areas(db: Session = Depends(get_db)):
    """
    Retrieve document count grouped by policy area.
    """
    from .services.cache import get_cache, set_cache
    cache_key = "aldf:cache:stats:policy-areas"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached
    results = db.query(
        LegislativeDocument.policy_area,
        func.count(LegislativeDocument.id)
    ).group_by(LegislativeDocument.policy_area).all()
    
    res = {pa: count for pa, count in results if pa}
    try:
        set_cache(cache_key, res, expire=300)
    except Exception as e:
        pass
    return res


@app.get("/stats/subjects")
def get_stats_subjects(db: Session = Depends(get_db)):
    """
    Retrieve document count grouped by subject.
    """
    from .services.cache import get_cache, set_cache
    cache_key = "aldf:cache:stats:subjects"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached
    results = db.query(
        Subject.name,
        func.count(LegislativeDocument.id)
    ).join(LegislativeDocument.subjects).group_by(Subject.name).all()
    
    res = {name: count for name, count in results}
    try:
        set_cache(cache_key, res, expire=300)
    except Exception as e:
        pass
    return res


@app.get("/export/csv")
def export_csv(db: Session = Depends(get_db)):
    """
    Export the matching documents dataset as a CSV file.
    """
    def generate():
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow([
            "id", "source_id", "title", "congress", "bill_type", "bill_number",
            "introduced_date", "origin_chamber", "policy_area", "current_stage",
            "last_action_date", "last_action_text", "update_date", "update_date_incl_text",
            "sponsor_name", "sponsor_party", "sponsor_state", "source_url", "ingested_at", "subjects"
        ])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        
        docs = db.query(LegislativeDocument).order_by(LegislativeDocument.introduced_date.desc()).all()
        for doc in docs:
            subjects_str = "|".join([s.name for s in doc.subjects])
            current_stage = get_current_stage(doc.last_action_text)
            sp_name, sp_party, sp_state = extract_sponsor_info(doc.api_raw)
            writer.writerow([
                str(doc.id),
                doc.source_id,
                doc.title or "",
                doc.congress,
                doc.bill_type,
                doc.bill_number,
                doc.introduced_date.isoformat() if doc.introduced_date else "",
                doc.origin_chamber or "",
                doc.policy_area or "",
                current_stage,
                doc.last_action_date.isoformat() if doc.last_action_date else "",
                doc.last_action_text or "",
                doc.update_date.isoformat() if doc.update_date else "",
                doc.update_date_incl_text.isoformat() if doc.update_date_incl_text else "",
                sp_name or "",
                sp_party or "",
                sp_state or "",
                doc.source_url or "",
                doc.ingested_at.isoformat() if doc.ingested_at else "",
                subjects_str
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=animal_legislation_export.csv"}
    )


@app.get("/export/json")
def export_json(include_raw: bool = False, db: Session = Depends(get_db)):
    """
    Export the matching documents dataset as a JSON file.
    """
    def generate():
        docs = db.query(LegislativeDocument).order_by(LegislativeDocument.introduced_date.desc()).all()
        yield "["
        for i, doc in enumerate(docs):
            sp_name, sp_party, sp_state = extract_sponsor_info(doc.api_raw)
            doc_dict = {
                "id": str(doc.id),
                "source_id": doc.source_id,
                "title": doc.title,
                "congress": doc.congress,
                "bill_type": doc.bill_type,
                "bill_number": doc.bill_number,
                "introduced_date": doc.introduced_date.isoformat() if doc.introduced_date else None,
                "origin_chamber": doc.origin_chamber,
                "policy_area": doc.policy_area,
                "current_stage": get_current_stage(doc.last_action_text),
                "last_action_date": doc.last_action_date.isoformat() if doc.last_action_date else None,
                "last_action_text": doc.last_action_text,
                "update_date": doc.update_date.isoformat() if doc.update_date else None,
                "update_date_incl_text": doc.update_date_incl_text.isoformat() if doc.update_date_incl_text else None,
                "sponsor_name": sp_name,
                "sponsor_party": sp_party,
                "sponsor_state": sp_state,
                "source_url": doc.source_url,
                "ingested_at": doc.ingested_at.isoformat(),
                "updated_at": doc.updated_at.isoformat(),
                "source_hash": doc.source_hash,
                "subjects": [s.name for s in doc.subjects]
            }
            if include_raw:
                doc_dict["api_raw"] = doc.api_raw
                
            json_str = json.dumps(doc_dict)
            if i > 0:
                yield "," + json_str
            else:
                yield json_str
        yield "]"

    return StreamingResponse(
        generate(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=animal_legislation_export.json"}
    )

# ── Auth Endpoints ────────────────────────────────────────────────────────────

@app.post("/auth/signup")
async def auth_signup(body: Dict[str, Any], db: Session = Depends(get_db)):
    """Register a new user. Sends a verification email before granting access."""
    from .services.auth import hash_password, generate_verification_token
    from .services.email_service import send_verification_email

    email = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "").strip()

    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="password must be at least 6 characters")

    existing = db.query(UserProfile).filter(UserProfile.email == email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    token = generate_verification_token()
    profile = UserProfile(
        email=email,
        password_hash=hash_password(password),
        is_verified=False,
        verification_token=token,
    )
    db.add(profile)
    db.commit()

    try:
        await send_verification_email(email, token)
    except Exception as e:
        print(f"[auth/signup] Email send failed: {e}")
        # Don't block signup if email fails — user can request a resend later

    return {"message": "Account created. Please check your email to verify your account."}


@app.get("/auth/verify/{token}")
def auth_verify(token: str, db: Session = Depends(get_db)):
    """Verify a user's email address via the token link sent in the signup email."""
    from fastapi.responses import RedirectResponse
    from .config import settings as cfg

    profile = db.query(UserProfile).filter(UserProfile.verification_token == token).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Invalid or expired verification token")

    profile.is_verified = True
    profile.verification_token = None
    db.commit()

    # Redirect to the frontend login page with a success flag
    return RedirectResponse(url=f"{cfg.FRONTEND_URL}?verified=true")


@app.post("/auth/login")
def auth_login(body: Dict[str, Any], db: Session = Depends(get_db)):
    """Authenticate a verified user. Returns a JWT access token."""
    from .services.auth import verify_password, create_access_token

    email = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "").strip()

    if not email or not password:
        raise HTTPException(status_code=400, detail="email and password are required")

    profile = db.query(UserProfile).filter(UserProfile.email == email).first()

    if not profile or not profile.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(password, profile.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not profile.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in")

    token = create_access_token({"sub": profile.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "email": profile.email,
    }


@app.get("/auth/me")
def auth_me(db: Session = Depends(get_db), authorization: Optional[str] = None):
    """Return the currently authenticated user's profile."""
    raise HTTPException(status_code=501, detail="Use /auth/me with Authorization header")


@app.post("/auth/resend-verification")
async def auth_resend_verification(body: Dict[str, Any], db: Session = Depends(get_db)):
    """Resend the verification email if the user hasn't verified yet."""
    from .services.auth import generate_verification_token
    from .services.email_service import send_verification_email

    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    profile = db.query(UserProfile).filter(UserProfile.email == email).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No account found with this email")
    if profile.is_verified:
        return {"message": "This account is already verified. Please log in."}

    token = generate_verification_token()
    profile.verification_token = token
    db.commit()

    await send_verification_email(email, token)
    return {"message": "Verification email resent. Please check your inbox."}


# Serve React build (frontend/dist) as static files
frontend_dist_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")
frontend_assets_dir = os.path.join(frontend_dist_dir, "assets")

if os.path.exists(frontend_assets_dir):
    app.mount("/assets", StaticFiles(directory=frontend_assets_dir), name="assets")

@app.get("/favicon.svg")
def read_favicon():
    return FileResponse(os.path.join(frontend_dist_dir, "favicon.svg"))

@app.get("/icons.svg")
def read_icons():
    return FileResponse(os.path.join(frontend_dist_dir, "icons.svg"))

@app.get("/")
def read_index():
    return FileResponse(os.path.join(frontend_dist_dir, "index.html"))

@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    return FileResponse(os.path.join(frontend_dist_dir, "index.html"))
