import sys
import os
import json

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.models import LegislativeDocument, Subject, AnimalSubject, SyncLog, document_subjects

def main():
    db = SessionLocal()
    try:
        # Fetch HR-281
        doc = db.query(LegislativeDocument).filter(LegislativeDocument.source_id == '119-HR-281').first()
        if not doc:
            print("HR-281 not found in database. Checking first stored bill...")
            doc = db.query(LegislativeDocument).first()
            
        if not doc:
            print("No documents stored.")
            return

        print("=== LEGISLATIVE DOCUMENT COLUMNS ===")
        for col in doc.__table__.columns.keys():
            val = getattr(doc, col)
            print(f"{col}: {val} ({type(val).__name__})")
            
        print("\n=== ASSOCIATED SUBJECTS ===")
        for s in doc.subjects:
            print(f"Subject: id={s.id}, name={s.name}")
            
        print("\n=== JUNCTION RECORDS (document_subjects) ===")
        # Query document_subjects raw values
        conn = db.connection()
        res = conn.execute(document_subjects.select().where(document_subjects.c.document_id == doc.id)).fetchall()
        for doc_id, subj_id in res:
            print(f"Junction: document_id={doc_id}, subject_id={subj_id}")
            
        print("\n=== ANIMAL SUBJECT MATCHES ===")
        # Query active animal subjects matching the bill's subjects
        subject_names = [s.name for s in doc.subjects]
        animal_matches = db.query(AnimalSubject).filter(
            AnimalSubject.subject_name.in_(subject_names),
            AnimalSubject.active == True
        ).all()
        for am in animal_matches:
            print(f"AnimalSubject: id={am.id}, name={am.subject_name}, active={am.active}, created_at={am.created_at}")

        print("\n=== SYNC LOGS ===")
        # Get latest sync log
        logs = db.query(SyncLog).order_by(SyncLog.start_time.desc()).limit(1).all()
        for l in logs:
            for col in l.__table__.columns.keys():
                val = getattr(l, col)
                print(f"SyncLog {col}: {val}")

        print("\n=== RAW API JSON STRUCTURE (FIRST 1200 CHARS) ===")
        raw_json_str = json.dumps(doc.api_raw, indent=2)
        print(raw_json_str[:1200] + "\n... [truncated]")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()
