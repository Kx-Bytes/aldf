import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import LegislativeDocument, UserProfile
from .congress_api import CongressAPIClient
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Approved relevance topics the model may tag a bill with. Kept aligned with the
# matching subjects so AI output stays within the project's animal/environment scope.
RELEVANCE_TOPICS = [
    "Animal welfare",
    "Wildlife conservation",
    "Endangered species",
    "Livestock and agriculture",
    "Aquatic life and fisheries",
    "Veterinary and animal health",
    "Hunting and trapping",
    "Animal cruelty and crimes",
    "Service and companion animals",
    "Habitat and land use",
    "Environmental protection",
    "Food safety and labeling",
    "Trafficking and smuggling",
]

SYSTEM_PROMPT = (
    "You are an analyst for an animal-welfare and environmental legislative tracking "
    "system. You score how relevant a U.S. congressional bill is to animal protection, "
    "wildlife, and related environmental concerns, and you write a concise plain-language "
    "impact summary for advocacy staff. Be factual and grounded only in the provided text. "
    "Always respond with a single JSON object and nothing else."
)

# Caps to keep prompt size (and cost) bounded on bills with very long summaries.
MAX_SUMMARY_CHARS = 8000
MAX_ACTION_CHARS = 2000


def _strip_html(text: Optional[str]) -> Optional[str]:
    """Remove HTML tags and collapse whitespace from a summary blob."""
    if not text:
        return text
    no_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", no_tags).strip()


def _build_user_prompt(document: LegislativeDocument) -> str:
    """Assemble the per-bill prompt from the fields we already have on the document."""
    summary = _strip_html(document.official_summary) or "(no official summary available)"
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[:MAX_SUMMARY_CHARS] + " ...[truncated]"

    last_action = (document.last_action_text or "")[:MAX_ACTION_CHARS]
    subjects = [s.name for s in document.subjects] if document.subjects else []

    parts = [
        f"Bill: {document.source_id}",
        f"Title: {document.title or '(untitled)'}",
        f"Policy area: {document.policy_area or '(none)'}",
        f"Congress.gov subjects: {', '.join(subjects) if subjects else '(none)'}",
        f"Latest action: {last_action or '(none)'}",
        "",
        "Official summary:",
        summary,
        "",
        "Allowed relevance topics (choose only from this list):",
        ", ".join(RELEVANCE_TOPICS),
        "",
        "Respond with a JSON object with exactly these keys:",
        '  "relevance_score": integer 0-100 (how relevant to animal welfare / wildlife / '
        "related environmental concerns; 0 = unrelated, 100 = central focus),",
        '  "relevance_topics": array of strings drawn ONLY from the allowed topics list above,',
        '  "relevance_rationale": one or two sentences justifying the score,',
        '  "ai_summary": a 2-4 sentence plain-language impact summary for advocacy staff.',
    ]
    return "\n".join(parts)


def _call_llm(user_prompt: str) -> Dict[str, Any]:
    """Call the OpenRouter chat-completions endpoint and return parsed JSON output."""
    url = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        # Optional attribution headers recommended by OpenRouter.
        "X-Title": "AnimalLegislationTracker",
    }
    payload = {
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]
    return _parse_llm_json(content)


def _parse_llm_json(content: str) -> Dict[str, Any]:
    """Parse the model's JSON reply, tolerating ```json fences or surrounding prose."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Fall back to extracting the first {...} block.
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _normalize_output(raw: Dict[str, Any]) -> Tuple[int, List[str], str, str]:
    """Coerce and validate the model output into the columns we store."""
    try:
        score = int(round(float(raw.get("relevance_score", 0))))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))

    topics_raw = raw.get("relevance_topics") or []
    if isinstance(topics_raw, str):
        topics_raw = [topics_raw]
    allowed = set(RELEVANCE_TOPICS)
    topics = [t for t in topics_raw if isinstance(t, str) and t in allowed]

    rationale = str(raw.get("relevance_rationale") or "").strip()
    summary = str(raw.get("ai_summary") or "").strip()

    return score, topics, rationale, summary


# ---------------------------------------------------------------------------
# Prompt expansion & personalized scoring
# ---------------------------------------------------------------------------

def expand_prompt_to_topics(user_prompt: str, db: Optional[Session] = None, user_email: Optional[str] = None) -> Dict[str, Any]:
    """Map a free-text user prompt to a structured set of RELEVANCE_TOPICS and keywords.

    Checks UserProfile.expanded_topics first (persistent cache). Falls back to a single
    LLM call if not cached. Result is stored back on the UserProfile when db + email given.

    Returns dict with keys:
        topics   – list of matched RELEVANCE_TOPICS strings
        keywords – list of lowercase freetext keywords for title/summary matching
    """
    if not user_prompt or not user_prompt.strip():
        return {"topics": [], "keywords": []}

    # Check persistent cache on UserProfile
    if db and user_email:
        profile = db.query(UserProfile).filter(UserProfile.email == user_email).first()
        if profile and profile.expanded_topics and profile.prompt == user_prompt:
            return profile.expanded_topics

    url = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "AnimalLegislationTracker",
    }
    expansion_prompt = (
        f"A user wants to track: \"{user_prompt.strip()}\"\n\n"
        f"Map this to the most relevant topics from this exact list:\n"
        f"{', '.join(RELEVANCE_TOPICS)}\n\n"
        f"Also extract 3-6 specific lowercase keywords from the user's request that would appear in bill titles or summaries.\n\n"
        f"Respond with a JSON object with exactly these keys:\n"
        f'  "topics": array of strings chosen ONLY from the list above,\n'
        f'  "keywords": array of lowercase keyword strings'
    )
    payload = {
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You map user tracking preferences to structured topic lists. Always respond with a single JSON object and nothing else."},
            {"role": "user", "content": expansion_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            raw = _parse_llm_json(response.json()["choices"][0]["message"]["content"])
        allowed = set(RELEVANCE_TOPICS)
        result = {
            "topics": [t for t in (raw.get("topics") or []) if isinstance(t, str) and t in allowed],
            "keywords": [k.lower().strip() for k in (raw.get("keywords") or []) if isinstance(k, str)],
        }
    except Exception as e:
        logger.warning(f"Prompt expansion failed, falling back to keyword-only: {e}")
        result = {"topics": [], "keywords": [w.lower() for w in user_prompt.strip().split() if len(w) > 3]}

    # Persist to UserProfile cache
    if db and user_email:
        profile = db.query(UserProfile).filter(UserProfile.email == user_email).first()
        if profile:
            profile.expanded_topics = result
            db.commit()

    return result


def score_against_prompt(doc: LegislativeDocument, topics: List[str], keywords: List[str]) -> int:
    """Score a document against expanded prompt topics and keywords.

    Weighted scoring:
      relevance_topics match  → 40 pts each, capped at 80
      subjects match          → 20 pts each, capped at 40
      policy_area match       → 15 pts flat
      title keyword match     → 5 pts each, capped at 15
      ai_summary keyword match→ 3 pts each, capped at 6
    Max raw = 156, normalized to 0-100.
    """
    if not topics and not keywords:
        return doc.relevance_score or 0

    score = 0
    topic_set = set(topics)
    doc_topics = set(doc.relevance_topics or [])
    doc_subjects = {s.name.lower() for s in doc.subjects} if doc.subjects else set()
    title_lower = (doc.title or "").lower()
    summary_lower = (doc.ai_summary or "").lower()
    policy_lower = (doc.policy_area or "").lower()

    # Topic hits
    topic_hits = len(topic_set & doc_topics)
    score += min(topic_hits * 40, 80)

    # Subject hits (keywords against subject names)
    subject_hits = sum(1 for kw in keywords if any(kw in subj for subj in doc_subjects))
    score += min(subject_hits * 20, 40)

    # Policy area hit
    if any(kw in policy_lower for kw in keywords) or policy_lower in {t.lower() for t in topics}:
        score += 15

    # Title keyword hits
    title_hits = sum(1 for kw in keywords if kw in title_lower)
    score += min(title_hits * 5, 15)

    # Summary keyword hits
    summary_hits = sum(1 for kw in keywords if kw in summary_lower)
    score += min(summary_hits * 3, 6)

    return min(round(score / 156 * 100), 100)


def process_bill_ai(document: LegislativeDocument, db: Optional[Session] = None) -> None:
    """Run the AI relevance-scoring and impact-summary pipeline on a document.

    Sends the bill's title, policy area, subjects, latest action, and official summary
    to the configured LLM (via OpenRouter) and stores the structured result on the
    document (``relevance_score``, ``relevance_topics``, ``relevance_rationale``,
    ``ai_summary``, ``ai_generated_at``, ``ai_source_hash``).

    Skips work when AI output already exists for the current ``source_hash`` so the
    pipeline only regenerates when the underlying bill content changed. Persists via
    ``db.commit()`` when a session is provided. Failures are logged and swallowed so a
    single bad bill never breaks the surrounding sync.
    """
    source_id = getattr(document, "source_id", "unknown")
    try:
        # Always fetch official summary if missing but available from Congress.gov.
        # Do this before the skip check so we persist the summary even on skips,
        # and so the AI gets it when the bill was synced before summary-fetching was added.
        summary_just_fetched = False
        if not document.official_summary:
            api_raw = document.api_raw or {}
            summaries_meta = api_raw.get("summaries") or {}
            if summaries_meta.get("count", 0):
                try:
                    client = CongressAPIClient()
                    data = client.fetch_bill_summaries(document.congress, document.bill_type, document.bill_number)
                    client.close()
                    summaries_list = data.get("summaries", [])
                    if summaries_list:
                        raw_text = summaries_list[-1].get("text") or ""
                        fetched = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_text)).strip() or None
                        if fetched:
                            document.official_summary = fetched
                            summary_just_fetched = True
                            logger.info(f"Fetched missing official_summary for {source_id}.")
                except Exception as fetch_err:
                    logger.warning(f"Could not fetch summary for {source_id}: {fetch_err}")

        # Skip AI only when hash is current AND we didn't just obtain a new summary
        # (a newly fetched summary means the previous AI run lacked this context).
        already_current = (
            document.ai_source_hash
            and document.ai_source_hash == document.source_hash
            and document.ai_generated_at is not None
        )
        if already_current and not summary_just_fetched:
            if summary_just_fetched and db is not None:
                db.commit()  # persist the summary even if AI is skipped
            logger.info(f"AI output for {source_id} is current (hash unchanged); skipping.")
            return

        logger.info(f"Running AI pipeline for {source_id} using model {settings.LLM_MODEL}.")
        user_prompt = _build_user_prompt(document)
        raw = _call_llm(user_prompt)
        score, topics, rationale, summary = _normalize_output(raw)

        document.relevance_score = score
        document.relevance_topics = topics
        document.relevance_rationale = rationale
        document.ai_summary = summary
        document.ai_generated_at = datetime.now()
        document.ai_source_hash = document.source_hash

        if db is not None:
            db.commit()

        logger.info(f"AI pipeline complete for {source_id}: score={score}, topics={topics}.")
    except Exception as e:
        if db is not None:
            db.rollback()
        logger.exception(f"Failed to process bill {source_id} with AI: {e}")
