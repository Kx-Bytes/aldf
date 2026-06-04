#!/usr/bin/env python3
import sys
import os
from typing import Optional

# Add parent directory to path so we can import from app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.services.sync import seed_animal_subjects, run_historical_backfill

def main():
    congress = 119
    max_bills: Optional[int] = 50  # Limit to 50 bills by default for test runs to avoid API rate limiting
    
    if len(sys.argv) > 1:
        try:
            congress = int(sys.argv[1])
        except ValueError:
            print("Usage: python3 run_sync.py [congress_number] [max_bills_limit]")
            sys.exit(1)
            
    if len(sys.argv) > 2:
        try:
            max_bills = int(sys.argv[2])
            if max_bills <= 0:
                max_bills = None
        except ValueError:
            pass

    print("=" * 60)
    print(f"Historical Backfill Module: Congress {congress}")
    print(f"Max Bills to Analyze: {max_bills if max_bills else 'Unlimited'}")
    print("=" * 60)

    db = SessionLocal()
    resume_log_id = None
    try:
        # Step 1: Seed animal subjects
        print("Seeding animal subjects...")
        seeded = seed_animal_subjects(db)
        print(f"Seeding completed. Added {seeded} new subjects.")
        
        # Step 2: Check for unfinished sync
        from app.models import SyncLog
        unfinished_log = db.query(SyncLog).filter(
            SyncLog.congress == congress,
            SyncLog.status.in_(["running", "failed", "cancelled", "interrupted"])
        ).order_by(SyncLog.updated_at.desc()).first()
        
        if unfinished_log:
            print("\nPrevious sync found:")
            print(f"Congress: {unfinished_log.congress}")
            print(f"Last Bill: {unfinished_log.last_processed_bill or 'None'}")
            print(f"Progress: {unfinished_log.records_processed} / {unfinished_log.total_bills_discovered}")
            # If the DB says running but it's starting run_sync now, it was interrupted
            display_status = "interrupted" if unfinished_log.status == "running" else unfinished_log.status
            print(f"Status: {display_status}")
            
            resume = True
            if sys.stdin.isatty():
                try:
                    response = input("\nResume? [Y/n]: ").strip().lower()
                    if response == 'n':
                        resume = False
                except (KeyboardInterrupt, EOFError):
                    print("\nAborted.")
                    sys.exit(1)
            else:
                print("\nNon-interactive shell detected. Defaulting to Resume.")
                
            if resume:
                resume_log_id = unfinished_log.id
                # Update status of unfinished log in case it was 'running' to let us start clean
                if unfinished_log.status == "running":
                    unfinished_log.status = "interrupted"
                    db.commit()
                print(f"Resuming sync log: {resume_log_id}")
            else:
                # Mark previous as interrupted so it doesn't get picked up again
                if unfinished_log.status == "running":
                    unfinished_log.status = "interrupted"
                    db.commit()
                print("Starting new backfill from the beginning.")
        
        # Step 3: Run historical backfill
        print(f"Running backfill for Congress {congress}...")
        log = run_historical_backfill(
            db, 
            congress=congress, 
            max_bills=max_bills, 
            resume_log_id=resume_log_id
        )
        
        print("\n" + "=" * 60)
        print("SYNC COMPLETED SUCCESSFULLY")
        print("=" * 60)
        print(f"Sync Log ID:        {log.id}")
        print(f"Sync Type:          {log.sync_type}")
        print(f"Status:             {log.status}")
        print(f"Records Processed:  {log.records_processed}")
        print(f"Start Time:         {log.start_time}")
        print(f"End Time:           {log.end_time}")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nSync Failed: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
