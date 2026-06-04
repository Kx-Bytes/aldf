import sys
import os
from collections import Counter

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.models import LegislativeDocument

def classify_action(action_text: str) -> str:
    """
    Classifies the status of a bill based on its latest action text.
    """
    text_lower = action_text.lower()
    
    # Inactive classifications
    if "became public law" in text_lower or "presented to president" in text_lower and "signed" in text_lower or "public law" in text_lower:
        return "Became Law"
    if "vetoed" in text_lower:
        return "Vetoed"
    if "failed" in text_lower or "rejected" in text_lower:
        return "Failed"
    if "withdrawn" in text_lower:
        return "Withdrawn"
    
    # Active classifications
    if "presented to president" in text_lower:
        return "Presented to President"
    if "conference" in text_lower:
        return "Conference"
    if "passed senate" in text_lower or "passed the senate" in text_lower or "agreed to in senate" in text_lower:
        return "Passed Senate"
    if "passed house" in text_lower or "passed the house" in text_lower or "agreed to in house" in text_lower:
        return "Passed House"
    if "reported by" in text_lower or "placed on calendar" in text_lower or "placed on senate legislative calendar" in text_lower:
        return "Reported by Committee"
    if "referred to" in text_lower or "subcommittee" in text_lower:
        return "Referred to Committee"
    if "introduced" in text_lower:
        return "Introduced"
        
    # Default to Referred to Committee if it was referred but has other actions
    return "Referred to Committee"

def main():
    db = SessionLocal()
    try:
        docs = db.query(LegislativeDocument).all()
        total_bills = len(docs)
        print(f"Analyzing {total_bills} documents...")
        
        status_counts = Counter()
        classification_counts = Counter()
        
        active_statuses = {
            "Introduced",
            "Referred to Committee",
            "Reported by Committee",
            "Passed House",
            "Passed Senate",
            "Conference",
            "Presented to President"
        }
        
        inactive_statuses = {
            "Became Law",
            "Vetoed",
            "Failed",
            "Withdrawn",
            "Dead"
        }
        
        samples = []
        
        for doc in docs:
            action_text = doc.last_action_text or ""
            status = classify_action(action_text)
            
            classification = "ACTIVE" if status in active_statuses else "INACTIVE"
            
            status_counts[status] += 1
            classification_counts[classification] += 1
            
            samples.append({
                "source_id": doc.source_id,
                "title": doc.title,
                "action_text": action_text,
                "status": status,
                "classification": classification
            })
            
        print("\n" + "=" * 60)
        print("STATUS BREAKDOWN")
        print("=" * 60)
        for stat in sorted(active_statuses | inactive_statuses):
            count = status_counts.get(stat, 0)
            print(f"* {stat}: {count}")
            
        print("\n" + "=" * 60)
        print("SUMMARY STATS")
        print("=" * 60)
        active_count = classification_counts.get("ACTIVE", 0)
        inactive_count = classification_counts.get("INACTIVE", 0)
        active_pct = (active_count / total_bills) * 100 if total_bills else 0
        inactive_pct = (inactive_count / total_bills) * 100 if total_bills else 0
        
        print(f"Total Bills Stored: {total_bills}")
        print(f"Active Bills Count: {active_count}")
        print(f"Inactive Bills Count: {inactive_count}")
        print(f"Active Percentage: {active_pct:.1f}%")
        print(f"Inactive Percentage: {inactive_pct:.1f}%")
        
        print("\n" + "=" * 60)
        print("10 SAMPLE RECORDS")
        print("=" * 60)
        for s in samples[:10]:
            print(f"Bill Number:             {s['source_id']}")
            print(f"Title:                   {s['title'][:70]}...")
            print(f"Current Status:          {s['status']}")
            print(f"Latest Action:           {s['action_text']}")
            print(f"Classification:          {s['classification']}")
            print("-" * 60)
            
    finally:
        db.close()

if __name__ == "__main__":
    main()
