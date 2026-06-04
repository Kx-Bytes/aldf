import sys
import os
from collections import Counter

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.models import LegislativeDocument, Subject, document_subjects

def main():
    db = SessionLocal()
    try:
        # 1. Fetch all documents
        docs = db.query(LegislativeDocument).order_by(LegislativeDocument.source_id).all()
        print(f"Total documents fetched: {len(docs)}")
        
        # 2. Print all stored bills
        print("\n" + "=" * 80)
        print("STORED ACTIVE BILLS (45)")
        print("=" * 80)
        print(f"{'Source ID':<15} | {'Policy Area':<35} | {'Title'}")
        print("-" * 80)
        for doc in docs:
            title_truncated = doc.title[:80] + ("..." if len(doc.title) > 80 else "")
            print(f"{doc.source_id:<15} | {str(doc.policy_area):<35} | {title_truncated}")
            
        # 3. Subject distribution (Top 20)
        print("\n" + "=" * 80)
        print("TOP 20 SUBJECT DISTRIBUTION")
        print("=" * 80)
        # Query subject counts through relationship or join
        subject_counts = (
            db.query(Subject.name, func.count(LegislativeDocument.id).label("bill_count"))
            .join(LegislativeDocument.subjects)
            .group_by(Subject.name)
            .order_by(func.count(LegislativeDocument.id).desc())
            .limit(20)
            .all()
        )
        for idx, (name, count) in enumerate(subject_counts, 1):
            print(f"{idx:2d}. {name:<50} : {count} bills")
            
        # 4. Policy area distribution
        print("\n" + "=" * 80)
        print("POLICY AREA DISTRIBUTION")
        print("=" * 80)
        policy_counts = (
            db.query(LegislativeDocument.policy_area, func.count(LegislativeDocument.id))
            .group_by(LegislativeDocument.policy_area)
            .order_by(func.count(LegislativeDocument.id).desc())
            .all()
        )
        for pa, count in policy_counts:
            print(f"* {str(pa):<50} : {count} bills")
            
        # 5. Bill type distribution
        print("\n" + "=" * 80)
        print("BILL TYPE DISTRIBUTION")
        print("=" * 80)
        type_counts = (
            db.query(LegislativeDocument.bill_type, func.count(LegislativeDocument.id))
            .group_by(LegislativeDocument.bill_type)
            .order_by(func.count(LegislativeDocument.id).desc())
            .all()
        )
        # List of interest: HR, HRES, HJRES, S, SRES, SJRES
        types_map = {t: count for t, count in type_counts}
        for bt in ["HR", "HRES", "HJRES", "S", "SRES", "SJRES"]:
            print(f"* {bt:<10} : {types_map.get(bt, 0)} bills")
            
    finally:
        db.close()

if __name__ == "__main__":
    from sqlalchemy import func
    main()
