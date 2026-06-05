from __future__ import annotations
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
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
         
    query = db.query(LegislativeDocument)
    
    if keyword:
        query = query.filter(
            or_(
                LegislativeDocument.title.ilike(f"%{keyword}%"),
                LegislativeDocument.last_action_text.ilike(f"%{keyword}%")
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

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "prompt_expansion": prompt_expansion,
        "results": formatted_results
    }


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
    except Exception as e:
        print(f"AI backfill failed: {e}")
    finally:
        db.close()


@app.post("/search/live")
def live_search(
    body: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Search Congress.gov live for bills updated on a specific date matching a prompt."""
    prompt = (body.get("prompt") or "").strip()
    search_date = (body.get("date") or "").strip()
    user_email = (body.get("user_email") or "").strip() or None

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    if not search_date:
        raise HTTPException(status_code=400, detail="date is required")

    try:
        from datetime import date as date_type, timedelta
        parsed_date = date_type.fromisoformat(search_date)
        next_date = parsed_date + timedelta(days=1)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be in YYYY-MM-DD format")

    from_dt = f"{parsed_date.isoformat()}T00:00:00Z"
    to_dt = f"{next_date.isoformat()}T00:00:00Z"

    # Expand prompt once (cached if user_email provided)
    from .services.ai_processing import expand_prompt_to_topics, score_against_prompt
    from .services.matching import match_bill, is_action_active
    expansion = expand_prompt_to_topics(prompt, db=db, user_email=user_email)
    topics = expansion.get("topics", [])
    keywords = expansion.get("keywords", [])

    # Load active animal subjects for matching
    from .models import AnimalSubject
    active_subject_names = {s.subject_name for s in db.query(AnimalSubject).filter(AnimalSubject.active == True).all()}

    client = CongressAPIClient()
    results = []
    offset = 0
    limit = 200

    try:
        while True:
            response = client.fetch_bills(119, offset=offset, limit=limit, from_date_time=from_dt, to_date_time=to_dt)
            bills = response.get("bills", [])
            if not bills:
                break

            for bill in bills:
                bill_number = bill.get("number") or bill.get("billNumber")
                bill_type = (bill.get("type") or bill.get("billType", "")).upper()
                if not bill_number or not bill_type:
                    continue

                # Skip inactive bills
                latest_action = bill.get("latestAction", {}) or {}
                if not is_action_active(latest_action.get("text")):
                    continue

                # Fetch subjects for animal matching
                try:
                    subjects_data = client.fetch_bill_subjects(119, bill_type, bill_number)
                    subjects_obj = subjects_data.get("subjects", {})
                    policy_area = (subjects_obj.get("policyArea") or {}).get("name")
                    subject_names = [s.get("name") for s in subjects_obj.get("legislativeSubjects", []) if s.get("name")]
                except Exception:
                    continue

                is_matched, _ = match_bill(policy_area, subject_names, active_subject_names)
                if not is_matched:
                    continue

                # Build a lightweight doc-like object for scoring
                class _Doc:
                    pass
                doc = _Doc()
                doc.title = bill.get("title") or ""
                doc.policy_area = policy_area or ""
                doc.ai_summary = ""
                doc.relevance_score = 0
                doc.relevance_topics = []
                doc.subjects = [type('S', (), {'name': n})() for n in subject_names]

                prompt_score = score_against_prompt(doc, topics, keywords)

                results.append({
                    "source_id": f"119-{bill_type}-{bill_number}",
                    "title": bill.get("title"),
                    "bill_type": bill_type,
                    "bill_number": bill_number,
                    "origin_chamber": bill.get("originChamber"),
                    "policy_area": policy_area,
                    "last_action_date": latest_action.get("actionDate"),
                    "last_action_text": latest_action.get("text"),
                    "update_date": bill.get("updateDate"),
                    "subjects": subject_names,
                    "prompt_score": prompt_score,
                    "source_url": bill.get("url"),
                    "current_stage": get_current_stage(latest_action.get("text")),
                })

            if len(bills) < limit:
                break
            offset += limit
    finally:
        client.close()

    results.sort(key=lambda r: r["prompt_score"], reverse=True)

    return {
        "date": search_date,
        "prompt_expansion": expansion,
        "total": len(results),
        "results": results,
    }


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

    db.commit()
    db.refresh(profile)
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
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


@app.get("/subjects")
def list_subjects(db: Session = Depends(get_db)):
    """
    Lists subjects with the count of matched bills.
    """
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
    
    return [
        {"name": name, "document_count": count}
        for name, count in results
    ]


@app.get("/stats/overview")
def get_stats_overview(db: Session = Depends(get_db)):
    """
    Retrieve overview statistics for the active bills database.
    """
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
    
    return {
        "total_active_bills": total_active_bills,
        "unique_subjects": unique_subjects,
        "date_range": {
            "min_date": min_date.isoformat() if min_date else None,
            "max_date": max_date.isoformat() if max_date else None
        },
        "bills_by_bill_type": {bt: count for bt, count in bill_types}
    }


@app.get("/stats/policy-areas")
def get_stats_policy_areas(db: Session = Depends(get_db)):
    """
    Retrieve document count grouped by policy area.
    """
    results = db.query(
        LegislativeDocument.policy_area,
        func.count(LegislativeDocument.id)
    ).group_by(LegislativeDocument.policy_area).all()
    
    return {pa: count for pa, count in results if pa}


@app.get("/stats/subjects")
def get_stats_subjects(db: Session = Depends(get_db)):
    """
    Retrieve document count grouped by subject.
    """
    results = db.query(
        Subject.name,
        func.count(LegislativeDocument.id)
    ).join(LegislativeDocument.subjects).group_by(Subject.name).all()
    
    return {name: count for name, count in results}


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

# Serve static files and index.html
import os
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def read_index():
    return FileResponse(os.path.join(static_dir, "index.html"))
