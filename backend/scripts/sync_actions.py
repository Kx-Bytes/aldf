#!/usr/bin/env python3
import sys
import os
import time
import argparse
from datetime import datetime
from typing import List, Set, Dict, Any, Tuple

# Add parent directory to path so we can import from app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.models import LegislativeDocument, BillAction
from app.services.congress_api import CongressAPIClient
from app.services.sync import parse_date

def sync_bill_actions(db, client: CongressAPIClient, limit: int = None, target_bill: str = None):
    print("=" * 60)
    print("Bill Actions Sync Script")
    print("=" * 60)

    # Query bills
    query = db.query(LegislativeDocument)
    if target_bill:
        query = query.filter(LegislativeDocument.source_id == target_bill)
        print(f"Filtering for specific bill: {target_bill}")
    
    # Order by source_id to process systematically
    bills = query.order_by(LegislativeDocument.source_id).all()
    
    if limit:
        bills = bills[:limit]
        print(f"Limiting to first {limit} bills.")
    
    total_bills = len(bills)
    print(f"Found {total_bills} bills to process.")
    print("=" * 60)

    total_actions_inserted = 0
    total_duplicates_skipped = 0
    start_time = time.time()

    for idx, doc in enumerate(bills):
        print(f"[{idx + 1}/{total_bills}] Fetching actions for {doc.source_id}...")
        
        # API parameters
        congress = doc.congress
        bill_type = doc.bill_type
        bill_number = doc.bill_number

        offset = 0
        fetch_limit = 100
        all_actions = []
        
        # Fetch actions with pagination
        try:
            while True:
                res = client.fetch_bill_actions(
                    congress=congress,
                    bill_type=bill_type,
                    bill_number=bill_number,
                    offset=offset,
                    limit=fetch_limit
                )
                actions = res.get("actions", [])
                all_actions.extend(actions)
                if len(actions) < fetch_limit:
                    break
                offset += fetch_limit
        except Exception as e:
            print(f"  Error fetching actions for {doc.source_id}: {e}")
            continue

        print(f"  Retrieved {len(all_actions)} raw actions from API.")

        # Deduplicate actions by (actionDate, text)
        seen: Set[Tuple[Any, str]] = set()
        deduplicated = []
        
        for action in all_actions:
            action_date_str = action.get("actionDate")
            action_date = parse_date(action_date_str)
            text = action.get("text")
            
            if not action_date or not text:
                print(f"  Warning: Skipping action with missing date ({action_date_str}) or text ({text})")
                continue
            
            text_normalized = text.strip()
            key = (action_date, text_normalized)
            
            if key in seen:
                total_duplicates_skipped += 1
                continue
                
            seen.add(key)
            deduplicated.append((action, action_date, text_normalized))

        print(f"  Deduplicated: {len(deduplicated)} actions to store (skipped {len(all_actions) - len(deduplicated)} duplicates).")

        # Delete any existing actions for this document to make the sync idempotent
        db.query(BillAction).filter(BillAction.document_id == doc.id).delete()

        # Insert new actions
        for action_data, action_date, text_norm in deduplicated:
            source_system = action_data.get("sourceSystem") or {}
            db_action = BillAction(
                document_id=doc.id,
                action_code=action_data.get("actionCode"),
                action_date=action_date,
                text=text_norm,
                action_type=action_data.get("type"),
                source_system_code=source_system.get("code") if source_system else None,
                source_system_name=source_system.get("name") if source_system else None
            )
            db.add(db_action)
            total_actions_inserted += 1

        # Commit every 20 bills
        if (idx + 1) % 20 == 0:
            db.commit()
            print(f"  [BATCH] Committed changes for the last 20 bills.")

    # Final commit for remaining bills
    db.commit()
    elapsed = time.time() - start_time
    
    print("\n" + "=" * 60)
    print("SYNC ACTIONS COMPLETE")
    print("=" * 60)
    print(f"Total Bills Processed:   {total_bills}")
    print(f"Total Actions Inserted:  {total_actions_inserted}")
    print(f"Total Duplicates Skipped: {total_duplicates_skipped}")
    print(f"Elapsed Time:            {elapsed:.1f}s ({elapsed/60.0:.2f}m)")
    print("=" * 60)

def main():
    parser = argparse.ArgumentParser(description="Fetch and sync bill actions from Congress.gov")
    parser.options = []
    parser.add_argument("--limit", type=int, help="Limit the number of bills to process")
    parser.add_argument("--bill", type=str, help="Process actions for a specific bill source ID (e.g. 119-HR-210)")
    args = parser.parse_args()

    db = SessionLocal()
    client = CongressAPIClient()
    try:
        sync_bill_actions(db, client, limit=args.limit, target_bill=args.bill)
    finally:
        client.close()
        db.close()

if __name__ == "__main__":
    main()
