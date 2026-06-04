# Congress.gov Historical Backfill Module

This module is the core historical ingestion engine for the **Animal Legislation Tracking System**. It interfaces with the Congress.gov API v3, filters for animal-related legislation, and stores them in a local PostgreSQL database.

---

## Active-Status Classification Rules

To prevent storing inactive, dead, or completed legislation, the system evaluates the `latestAction.text` field returned by the Congress.gov API and filters for **ACTIVE** bills only.

### 1. Classification Definitions
* **ACTIVE**: Bills currently progressing through the legislative pipeline (e.g. newly introduced, under committee review, debated on the floor, or awaiting presidential signature).
* **INACTIVE**: Bills that have reached a final, terminal state (e.g. enacted into law, vetoed, rejected/failed, or formally withdrawn).

### 2. Status Mapping Table

| Status Group | Matching Keyphrase Patterns (Case-Insensitive) | Classification |
| :--- | :--- | :--- |
| **Became Law** | `"became public law"`, `"became private law"`, `"public law no"` | **INACTIVE** (Skip/Delete) |
| **Vetoed** | `"vetoed"`, `"veto"` | **INACTIVE** (Skip/Delete) |
| **Failed** | `"failed"`, `"rejected"`, `"tabled"`, `"indefinitely postponed"` | **INACTIVE** (Skip/Delete) |
| **Withdrawn** | `"withdrawn"` | **INACTIVE** (Skip/Delete) |
| **Dead** | `"dead"`, `"died"` | **INACTIVE** (Skip/Delete) |
| **Introduced** | (Default state when bill is newly introduced) | **ACTIVE** (Ingest) |
| **In Committee** | `"referred to"`, `"subcommittee"` | **ACTIVE** (Ingest) |
| **Reported** | `"reported by"`, `"placed on calendar"` | **ACTIVE** (Ingest) |
| **Passed House** | `"passed house"`, `"agreed to in house"` | **ACTIVE** (Ingest) |
| **Passed Senate** | `"passed senate"`, `"agreed to in senate"` | **ACTIVE** (Ingest) |
| **Presented** | `"presented to president"` | **ACTIVE** (Ingest) |

If a bill's latest action text matches any of the **INACTIVE** keywords, it is skipped early in the ingestion process. If a bill was previously active and stored in the database, but updates show it has transitioned to an inactive state, it is automatically removed from the database during incremental syncs.

---

## Subject Matching Logic

The matching logic validates if a bill is animal-related by checking:
1. **Policy Area:** If `policyArea.name` is exactly `"Animals"`.
2. **Legislative Subjects:** If any subject name under `legislativeSubjects` matches one of the pre-approved animal subjects (e.g., `"Animal and plant health"`, `"Wildlife conservation and habitat protection"`, `"Livestock"`, etc.).

If either condition is met, the bill matches and is ingested. Otherwise, it is skipped.

---

## Database Schema

The database uses PostgreSQL with the following tables (managed via SQLAlchemy and Alembic):

### 1. `animal_subjects`
Holds the list of active animal subjects/keywords used for matching.
* `id` (Integer, Primary Key)
* `subject_name` (String(255), Unique, Indexed)
* `active` (Boolean, default True)
* `created_at` (DateTime, default `now()`)

### 2. `subjects`
Holds all distinct subjects retrieved from matching bills.
* `id` (Integer, Primary Key)
* `name` (String(255), Unique, Indexed)

### 3. `legislative_documents`
Holds matched, active animal legislation documents and their metadata.
* `id` (UUID, Primary Key)
* `source` (String(50), default "congress.gov")
* `source_id` (String(100), Unique, Indexed) - e.g., `119-HR-8873`
* `source_url` (String(500))
* `congress` (Integer, Indexed)
* `bill_type` (String(20), Indexed) - e.g., `HR`, `S`, `SRES`
* `bill_number` (String(20))
* `title` (String)
* `introduced_date` (Date)
* `origin_chamber` (String(50))
* `policy_area` (String(100), Indexed)
* `last_action_date` (Date, Indexed)
* `last_action_text` (String)
* `update_date` (DateTime)
* `update_date_incl_text` (DateTime)
* `source_hash` (String(64)) - SHA-256 hash of normalized payload to detect modifications
* `api_raw` (JSONB) - The raw JSON response from Congress.gov
* `ingested_at` (DateTime, default `now()`)
* `updated_at` (DateTime, default `now()`, onupdate `now()`)

### 4. `document_subjects`
Junction table for the many-to-many relationship between `legislative_documents` and `subjects`.
* `document_id` (UUID, ForeignKey to `legislative_documents.id`, cascade delete)
* `subject_id` (Integer, ForeignKey to `subjects.id`, cascade delete)

### 5. `sync_logs`
Tracks sync logs and telemetry for incremental/historical sync runs.
* `id` (UUID, Primary Key)
* `sync_type` (String(50))
* `status` (String(20)) - `running`, `completed`, `failed`, `cancelled`, `interrupted`
* `records_processed` (Integer)
* `total_bills_discovered` (Integer)
* `last_processed_bill` (String(100))
* `last_processed_page` (Integer)
* `active_bills_stored` (Integer)
* `inactive_bills_skipped` (Integer)
* `api_requests_made` (Integer)
* `started_at` (DateTime)
* `end_time` (DateTime, nullable)
* `error_message` (String, nullable)

---

## Resume/Checkpoint System

The sync ingestion pipeline is designed to be highly resilient against failures (e.g. rate limit bans, network timeouts, process terminations):
* **Checkpoint Database Tracking:** Every 100 bills processed, the ingestion pipeline commits progress telemetry to the `sync_logs` table, storing `last_processed_bill` and `last_processed_page`.
* **Automatic Resume:** On startup, the CLI script automatically checks for any unfinished sync job. If found, it fetches the page corresponding to `last_processed_page` and skips bills until it reaches `last_processed_bill`, resuming processing from the next bill.
* **Graceful Interruption:** Custom signal handlers intercept `SIGINT` (Ctrl+C) and `SIGTERM` signals, letting the program commit the current bill and page progress to the DB, saving the checkpoint cleanly before exiting.

---

## API Endpoints

All endpoints are hosted at `http://localhost:8000`.

### 1. Documents API

#### Get Recent Documents
* **URL:** `GET /documents`
* **Description:** Retrieves the 50 most recently ingested documents.
* **Response:** Array of documents including `subjects` and derived `current_stage`.

#### Search and Filter Documents
* **URL:** `GET /documents/search`
* **Query Parameters:**
  * `keyword` (String, optional) - Case-insensitive match on title or last action text.
  * `subject` (String, optional) - Filters bills containing this subject.
  * `policy_area` (String, optional) - Filters by policy area.
  * `bill_type` (String, optional) - Filters by bill type (e.g., `HR`, `S`).
  * `congress` (Integer, optional) - Filters by Congress number.
  * `sort_by` (String, optional) - `introduced_date`, `last_action_date`, `source_id`, `ingested_at` (default: `introduced_date`).
  * `order` (String, optional) - `asc` or `desc` (default: `desc`).
  * `limit` (Integer, default 20)
  * `offset` (Integer, default 0)
* **Response:** Paginated object with `total`, `limit`, `offset`, and `results` array.

#### Get Document Details
* **URL:** `GET /documents/{source_id}`
* **Description:** Retrieves comprehensive metadata, subjects, raw `api_raw` payload, and source hash for a specific bill.

---

### 2. Subjects API

#### Get Subjects
* **URL:** `GET /subjects`
* **Description:** Retrieves a list of subjects along with the count of matched bills for each subject, ordered by document count descending.

---

### 3. Statistics APIs

#### Overview Statistics
* **URL:** `GET /stats/overview`
* **Description:** Returns total active bills, unique subjects count, date ranges, and breakdown by bill types.

#### Policy Area Statistics
* **URL:** `GET /stats/policy-areas`
* **Description:** Returns count of bills grouped by policy area.

#### Subject Statistics
* **URL:** `GET /stats/subjects`
* **Description:** Returns count of bills grouped by subject.

---

### 4. Export APIs

#### Export to CSV
* **URL:** `GET /export/csv`
* **Description:** Downloads the entire matching dataset as a CSV file.
* **Format:** Columns are comma-separated. The `subjects` column is pipe-separated (e.g. `Livestock|Ecology`).

#### Export to JSON
* **URL:** `GET /export/json`
* **Query Parameters:**
  * `include_raw` (Boolean, default `false`) - If `true`, includes the huge `api_raw` payload.
* **Description:** Streams a JSON array file download containing all matched legislation.

---

## Execution Guide

### 1. Database Setup
Spin up the database using Docker Compose:
```bash
docker compose up -d
```

### 2. Apply Migrations
Apply Alembic migrations to create the schemas and database indexes:
```bash
PYTHONPATH=backend .venv/bin/alembic upgrade head
```

### 3. Run Ingestion (CLI)
You can run the sync service directly via terminal to backfill bills.
```bash
# E.g. Backfill the 119th Congress, analyzing up to 400 bills
PYTHONPATH=backend .venv/bin/python3 backend/scripts/run_sync.py 119 400
```

### 4. Start API Server (FastAPI)
Run the FastAPI development server:
```bash
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
