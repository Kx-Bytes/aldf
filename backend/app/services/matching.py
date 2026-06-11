from __future__ import annotations
from typing import List, Set, Tuple, Optional, Dict

# Congress.gov policy areas that automatically qualify a bill for ingestion.
ALDF_POLICY_AREAS: Set[str] = {"Animals", "Agriculture and Food"}

# ALDF focus-area taxonomy applied to Congress.gov legislative subject names.
SUBJECT_CATEGORIES: Dict[str, List[str]] = {
    "Animals Used in Research": [
        "Animal and plant health",
        "Environmental assessment, monitoring, research",
        "Veterinary medicine and animal diseases",
        "Infectious and parasitic diseases",
        "Environmental health",
        "World health",
    ],
    "Farmed Animals": [
        "Livestock",
        "Agricultural practices and innovations",
        "Agricultural research",
        "Aquaculture",
        "Meat",
        "Seafood",
        "Food supply, safety, and labeling",
        "Pest management",
    ],
    "Wildlife": [
        "Birds",
        "Fishes",
        "Insects",
        "Mammals",
        "Reptiles",
        "Aquatic ecology",
        "Ecology",
        "Endangered and threatened species",
        "Forests, forestry, trees",
        "Hunting and fishing",
        "Land use and conservation",
        "Lakes and rivers",
        "Marine and coastal resources, fisheries",
        "Marine pollution",
        "Outdoor recreation",
        "Watersheds",
        "Wetlands",
        "Wilderness and natural areas, wildlife refuges, wild rivers, habitats",
        "Wildlife conservation and habitat protection",
    ],
    "Companion & Captive Animals": [
        "Animal protection and human-animal relationships",
        "Crimes against animals and natural resources",
        "Service animals",
    ],
    "Legal & Policy Issues": [
        "Human trafficking",
        "Smuggling and trafficking",
    ],
}

# Reverse lookup built once at import time: subject name → category label.
_SUBJECT_TO_CATEGORY: Dict[str, str] = {
    subject: category
    for category, subjects in SUBJECT_CATEGORIES.items()
    for subject in subjects
}


def get_subject_category(subject_name: str) -> Optional[str]:
    """Return the ALDF category for a subject name, or None if unmapped."""
    return _SUBJECT_TO_CATEGORY.get(subject_name)


def match_bill(
    policy_area: Optional[str],
    legislative_subjects: List[str],
    active_animal_subjects: Set[str]
) -> Tuple[bool, List[str]]:
    """
    Checks if a bill is animal-related.
    
    A bill matches if:
    1. policy_area == "Animals"
    OR
    2. Any subject name in legislative_subjects matches an active record in active_animal_subjects.
    
    Returns a tuple of (is_matched, matching_subjects).
    """
    matching_subjects = []
    is_matched = False

    # Rule 1: Policy area is one of the ALDF-tracked areas (Animals, Agriculture and Food).
    if policy_area in ALDF_POLICY_AREAS:
        is_matched = True

    # Rule-2: At least one legislative subject matches our active list
    for subject in legislative_subjects:
        if subject in active_animal_subjects:
            matching_subjects.append(subject)
            is_matched = True

    return is_matched, matching_subjects


def is_action_active(action_text: Optional[str]) -> bool:
    """
    Checks if a bill's latest action indicates it is still ACTIVE.
    
    A bill is INACTIVE if the action text contains patterns corresponding to:
    - Became Law (e.g. "became public law", "public law no")
    - Vetoed (e.g. "vetoed", "veto")
    - Failed (e.g. "failed", "rejected", "tabled", "indefinitely postponed")
    - Withdrawn (e.g. "withdrawn")
    - Dead (e.g. "dead", "died")
    
    Otherwise, it is considered ACTIVE.
    """
    if not action_text:
        return True  # If no action recorded, assume active (e.g. newly introduced)
        
    text_lower = action_text.lower()
    
    # Inactive status indicator patterns
    inactive_keywords = [
        "became public law",
        "became private law",
        "public law no",
        "vetoed",
        "veto",
        "failed",
        "rejected",
        "tabled",
        "indefinitely postponed",
        "withdrawn",
        "dead",
        "died"
    ]
    
    for kw in inactive_keywords:
        if kw in text_lower:
            return False
            
    return True


def get_current_stage(last_action_text: Optional[str]) -> str:
    """
    Derives the progress stage of a bill based on its last action text.
    
    Stages:
    - Became Law
    - Vetoed
    - Failed/Dead
    - Presented to President
    - Resolving Differences
    - Passed Chamber
    - Committee Action
    - Referred to Committee
    - Introduced
    """
    if not last_action_text:
        return "Introduced"
    text_lower = last_action_text.lower()
    
    # Inactive/terminal states
    if any(kw in text_lower for kw in ["became public law", "became private law", "public law no", "signed by president"]):
        return "Became Law"
    if any(kw in text_lower for kw in ["vetoed", "veto"]):
        return "Vetoed"
    if any(kw in text_lower for kw in ["failed", "rejected", "tabled", "indefinitely postponed", "withdrawn", "dead", "died"]):
        return "Failed/Dead"
        
    # Active states
    if "presented to president" in text_lower:
        return "Presented to President"
    if "conference" in text_lower or "resolving differences" in text_lower:
        return "Resolving Differences"
    if "passed" in text_lower or "agreed to" in text_lower:
        return "Passed Chamber"
    if any(kw in text_lower for kw in ["reported by", "reported from", "committee consideration", "ordered to be reported", "hearings held"]):
        return "Committee Action"
    if "referred to" in text_lower or "read twice" in text_lower:
        return "Referred to Committee"
        
    return "Introduced"


