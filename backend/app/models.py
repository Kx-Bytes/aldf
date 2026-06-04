import uuid
from datetime import datetime, date
from typing import List, Optional
from sqlalchemy import String, Integer, Boolean, DateTime, Date, ForeignKey, Table, Column, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB, UUID

from .database import Base

# Junction table for many-to-many relationship
document_subjects = Table(
    "document_subjects",
    Base.metadata,
    Column(
        "document_id", 
        UUID(as_uuid=True), 
        ForeignKey("legislative_documents.id", ondelete="CASCADE"), 
        primary_key=True
    ),
    Column(
        "subject_id", 
        Integer, 
        ForeignKey("subjects.id", ondelete="CASCADE"), 
        primary_key=True
    ),
)

class LegislativeDocument(Base):
    __tablename__ = "legislative_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), default="congress.gov")
    source_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    congress: Mapped[int] = mapped_column(Integer)
    bill_type: Mapped[str] = mapped_column(String(20), index=True)
    bill_number: Mapped[str] = mapped_column(String(20))
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    introduced_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    origin_chamber: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    policy_area: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    last_action_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    last_action_text: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    update_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    update_date_incl_text: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    source_hash: Mapped[str] = mapped_column(String(64))  # SHA-256
    api_raw: Mapped[dict] = mapped_column(JSONB)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    # Official CRS summary text fetched from the Congress.gov /summaries endpoint (HTML stripped).
    official_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # AI processing pipeline output (PRD sections 8.1 scoring and 8.2 impact summary).
    relevance_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)        # 0-100
    relevance_topics: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)        # list[str]
    relevance_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # source_hash the AI output was generated from; lets us regenerate only on content change.
    ai_source_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Many-to-many relationship to Subject
    subjects: Mapped[List["Subject"]] = relationship(
        "Subject",
        secondary=document_subjects,
        back_populates="documents"
    )

    # One-to-many relationship to BillAction
    actions: Mapped[List["BillAction"]] = relationship(
        "BillAction",
        back_populates="document",
        cascade="all, delete-orphan"
    )

class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)

    # Back-reference
    documents: Mapped[List[LegislativeDocument]] = relationship(
        "LegislativeDocument",
        secondary=document_subjects,
        back_populates="subjects"
    )

class AnimalSubject(Base):
    __tablename__ = "animal_subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sync_type: Mapped[str] = mapped_column(String(50))  # e.g., 'historical_backfill'
    status: Mapped[str] = mapped_column(String(20))  # e.g., 'running', 'completed', 'failed', 'cancelled', 'interrupted'
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    start_time: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    # Progress tracking columns
    congress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_bills_discovered: Mapped[int] = mapped_column(Integer, default=0)
    last_processed_bill: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_processed_page: Mapped[int] = mapped_column(Integer, default=0)
    active_bills_stored: Mapped[int] = mapped_column(Integer, default=0)
    inactive_bills_skipped: Mapped[int] = mapped_column(Integer, default=0)
    api_requests_made: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expanded_topics: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)  # persisted expansion cache
    frequency: Mapped[str] = mapped_column(String(20), default="daily")  # 'daily' | 'weekly'
    scope: Mapped[str] = mapped_column(String(20), default="federal")    # 'federal' | 'priority_states' | 'all_states'
    min_relevance_score: Mapped[int] = mapped_column(Integer, default=70)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class BillAction(Base):
    __tablename__ = "bill_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        ForeignKey("legislative_documents.id", ondelete="CASCADE"), 
        index=True, 
        nullable=False
    )
    action_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    action_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    text: Mapped[str] = mapped_column(String, nullable=False)
    action_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source_system_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_system_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relationship back to LegislativeDocument
    document: Mapped["LegislativeDocument"] = relationship("LegislativeDocument", back_populates="actions")

