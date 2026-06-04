import sys
import os
import random

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.models import LegislativeDocument, AnimalSubject
from app.services.matching import is_action_active

def main():
    db = SessionLocal()
    try:
        # 1. Check duplicate source_ids
        total_docs = db.query(LegislativeDocument).count()
        unique_source_ids = db.query(LegislativeDocument.source_id).distinct().count()
        has_duplicates = total_docs != unique_source_ids
        
        print("=" * 60)
        print("DUPLICATE SOURCE_ID CHECK")
        print("=" * 60)
        print(f"Total Stored Documents:    {total_docs}")
        print(f"Unique source_id Count:    {unique_source_ids}")
        print(f"Duplicate source_ids Found: {has_duplicates}")
        print("=" * 60)
        
        if total_docs == 0:
            print("Database is empty.")
            return

        # 2. Query all active animal subject names
        active_subjects = db.query(AnimalSubject).filter(AnimalSubject.active == True).all()
        active_subject_names = {s.subject_name for s in active_subjects}

        # 3. Fetch 10 random documents
        docs = db.query(LegislativeDocument).all()
        # Random sample of 10 or total docs if less than 10
        random_sample = random.sample(docs, min(10, len(docs)))
        
        print("\n" + "=" * 60)
        print("10 RANDOM BILLS VALIDATION")
        print("=" * 60)
        
        for idx, doc in enumerate(random_sample, 1):
            action_text = doc.last_action_text or ""
            is_active = is_action_active(action_text)
            
            # Find which of the bill's subjects matched our active list
            subjects = [s.name for s in doc.subjects]
            matched_subjects = [s for s in subjects if s in active_subject_names]
            if doc.policy_area == "Animals" and not matched_subjects:
                matched_subjects.append("Policy Area: Animals")
                
            print(f"Sample #{idx}:")
            print(f"  Bill Number:    {doc.source_id}")
            print(f"  Title:          {doc.title[:75]}...")
            print(f"  Latest Action:  {action_text}")
            print(f"  Matched Subs:   {matched_subjects}")
            print(f"  Active Status:  {is_active} (Classified: {'ACTIVE' if is_active else 'INACTIVE'})")
            print("-" * 60)
            
    finally:
        db.close()

if __name__ == "__main__":
    main()
