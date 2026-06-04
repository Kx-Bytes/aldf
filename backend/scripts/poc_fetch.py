#!/usr/bin/env python3
import os
import sys
import time
from typing import List, Dict, Any, Set

# Approved Subject List from requirements
APPROVED_SUBJECTS: Set[str] = {
    "Animal and plant health",
    "Animal protection and human-animal relationships",
    "Aquaculture",
    "Aquatic ecology",
    "Birds",
    "Crimes against animals and natural resources",
    "Fishes",
    "Insects",
    "Livestock",
    "Mammals",
    "Reptiles",
    "Service animals",
    "Veterinary medicine and animal diseases",
    "Wildlife conservation and habitat protection",
    "Ecology",
    "Endangered and threatened species",
    "Environmental assessment, monitoring, research",
    "Forests, forestry, trees",
    "Land use and conservation",
    "Lakes and rivers",
    "Marine and coastal resources, fisheries",
    "Marine pollution",
    "Watersheds",
    "Wetlands",
    "Wilderness and natural areas, wildlife refuges, wild rivers, habitats",
    "Agricultural practices and innovations",
    "Agricultural research",
    "Hunting and fishing",
    "Outdoor recreation",
    "Pest management",
    "Food supply, safety, and labeling",
    "Meat",
    "Seafood",
    "Environmental health",
    "Infectious and parasitic diseases",
    "World health",
    "Human trafficking",
    "Smuggling and trafficking"
}

def main():
    print("=" * 60)
    print("Congress.gov API Proof of Concept (POC) Fetcher")
    print("=" * 60)

    # 1. Load CONGRESS_API_KEY from environment variables
    api_key = os.environ.get("CONGRESS_API_KEY")
    if not api_key:
        print("Error: CONGRESS_API_KEY environment variable is not set.", file=sys.stderr)
        print("Please set it in your environment. Example:", file=sys.stderr)
        print("  export CONGRESS_API_KEY=\"your_api_key\"", file=sys.stderr)
        sys.exit(1)

    print(f"API Key loaded: {api_key[:4]}...{api_key[-4:] if len(api_key) > 8 else ''}")

    # Try importing httpx (tech stack requirement).
    # If not present, we will import urllib to perform the requests fallback
    # so that the POC can run even before pip installs.
    use_httpx = False
    try:
        import httpx
        use_httpx = True
        print("Using HTTPX client library.")
    except ImportError:
        import urllib.request
        import json
        print("HTTPX library not installed. Falling back to urllib for POC script.")

    base_url = "https://api.congress.gov/v3"
    congress = 119
    limit = 10

    # Helper function to perform GET requests
    def get_json(url: str, params: Dict[str, Any]) -> tuple[Dict[str, Any], float]:
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{url}?{query_string}"
        
        start_time = time.perf_counter()
        
        if use_httpx:
            response = httpx.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()
        else:
            req = urllib.request.Request(
                full_url, 
                headers={"Accept": "application/json"}
            )
            with urllib.request.urlopen(req) as response:
                raw_data = response.read().decode('utf-8')
                data = json.loads(raw_data)
                
        elapsed = time.perf_counter() - start_time
        return data, elapsed

    # 2. Fetch only 10 bills from Congress.gov (119th Congress)
    bills_url = f"{base_url}/bill/{congress}"
    print(f"\nFetching {limit} bills from Congress {congress}...")
    
    try:
        bills_data, elapsed_time = get_json(bills_url, {"api_key": api_key, "format": "json", "limit": limit})
        print(f"Fetch bills list successful. Response time: {elapsed_time:.3f}s")
    except Exception as e:
        print(f"Failed to fetch bills list from Congress.gov: {e}", file=sys.stderr)
        sys.exit(1)

    bills = bills_data.get("bills", [])
    if not bills:
        print("No bills returned in the API response.")
        sys.exit(0)

    print(f"Retrieved {len(bills)} bills. Starting analysis...\n")

    results = []

    # Iterate through bills and fetch details/subjects
    for idx, bill in enumerate(bills, 1):
        bill_number = bill.get("number") or bill.get("billNumber")
        # Extract billType (some list endpoints return billType or type)
        bill_type = bill.get("type") or bill.get("billType")
        title = bill.get("title")
        
        if not bill_number or not bill_type:
            print(f"Skipping bill {idx}: Missing identifier metadata.")
            continue

        # Convert bill type to lowercase for url path compatibility
        bill_type_lower = bill_type.lower()
        subjects_url = f"{base_url}/bill/{congress}/{bill_type_lower}/{bill_number}/subjects"

        print(f"[{idx}/10] Fetching subjects for Bill: {congress}-{bill_type}-{bill_number}...")
        
        try:
            subjects_data, sub_elapsed = get_json(subjects_url, {"api_key": api_key, "format": "json"})
            total_elapsed = elapsed_time + sub_elapsed # baseline list time + individual detail time
        except Exception as e:
            print(f"  Failed to fetch subjects for bill {congress}-{bill_type}-{bill_number}: {e}")
            continue

        # Extract policy area and legislative subjects
        subjects_obj = subjects_data.get("subjects", {})
        policy_area_obj = subjects_obj.get("policyArea", {})
        policy_area_name = policy_area_obj.get("name") if policy_area_obj else None
        
        legislative_subjects = subjects_obj.get("legislativeSubjects", [])
        subject_names = [sub.get("name") for sub in legislative_subjects if sub.get("name")]
        
        # Run animal matching logic
        matching_subjects = []
        is_matched = False
        
        # Rule 1: Policy Area == Animals
        if policy_area_name == "Animals":
            is_matched = True
            
        # Rule 2: Legislative subjects overlap with approved animal subjects list
        for name in subject_names:
            if name in APPROVED_SUBJECTS:
                matching_subjects.append(name)
                is_matched = True

        results.append({
            "bill_number": bill_number,
            "bill_type": bill_type,
            "congress": congress,
            "title": title,
            "policy_area": policy_area_name or "None",
            "subject_count": len(subject_names),
            "subject_names": subject_names,
            "matching_subjects": matching_subjects,
            "match_status": "MATCHED" if is_matched else "NO_MATCH",
            "api_response_time_sec": sub_elapsed
        })

    # Display results in terminal
    print("\n" + "=" * 60)
    print("POC EXECUTION RESULTS")
    print("=" * 60)
    
    matched_count = 0
    for res in results:
        print(f"Bill Number:             {res['congress']}-{res['bill_type']}-{res['bill_number']}")
        print(f"Title:                   {res['title']}")
        print(f"Policy Area:             {res['policy_area']}")
        print(f"Subject Count:           {res['subject_count']}")
        print(f"Subject Names:           {', '.join(res['subject_names'][:5])}" + ("..." if len(res['subject_names']) > 5 else ""))
        print(f"Matching Animal Subjects: {', '.join(res['matching_subjects']) if res['matching_subjects'] else 'None'}")
        print(f"Match Status:            {res['match_status']}")
        print(f"API Response Time:       {res['api_response_time_sec']:.3f} seconds")
        print("-" * 60)
        if res['match_status'] == "MATCHED":
            matched_count += 1
            
    print(f"\nSummary: Analyzed {len(results)} bills. Matches found: {matched_count}.")
    print("=" * 60)
    print("POC Success Criteria: PASS" if len(results) == limit else "POC Success Criteria: FAIL")
    print("=" * 60)

if __name__ == "__main__":
    main()
