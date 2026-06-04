import time
import httpx
from typing import Dict, Any, Optional
from ..config import settings

class CongressAPIClient:
    """
    Client for interacting with the Congress.gov API v3.
    """
    def __init__(self):
        self.base_url = "https://api.congress.gov/v3"
        self.api_key = settings.CONGRESS_API_KEY
        
        # User-Agent is explicitly set to prevent Cloudflare/API gateway blocks
        self.client = httpx.Client(
            headers={"User-Agent": "AnimalLegislationTracker/1.0"},
            timeout=60.0
        )

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        req_params = params.copy() if params else {}
        req_params["api_key"] = self.api_key
        req_params["format"] = "json"

        max_retries = 4
        backoff = 2.0
        
        for attempt in range(max_retries):
            try:
                response = self.client.get(url, params=req_params)
                
                # Check for rate limiting
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        print(f"Rate limited (429) on {path}. Retrying in {backoff:.1f}s...")
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                
                response.raise_for_status()
                return response.json()
                
            except httpx.HTTPStatusError as e:
                # Retry on rate limiting or 5xx server errors
                if (e.response.status_code == 429 or e.response.status_code >= 500) and attempt < max_retries - 1:
                    print(f"HTTP error {e.response.status_code} on {path}. Retrying in {backoff:.1f}s...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise e
            except httpx.RequestError as e:
                # Retry on transient connection issues
                if attempt < max_retries - 1:
                    print(f"Request error {e} on {path}. Retrying in {backoff:.1f}s...")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise e
                
        raise Exception(f"Failed to fetch {url} after {max_retries} attempts.")

    def fetch_bills(self, congress: int, offset: int = 0, limit: int = 20, from_date_time: Optional[str] = None, to_date_time: Optional[str] = None) -> Dict[str, Any]:
        """
        GET /bill/{congress}
        Retrieves a paginated list of bills for the specified congress.
        Optionally filtered by fromDateTime/toDateTime (ISO 8601 UTC strings).
        """
        params: Dict[str, Any] = {"offset": offset, "limit": limit}
        if from_date_time:
            params["fromDateTime"] = from_date_time
        if to_date_time:
            params["toDateTime"] = to_date_time
        return self._request(f"bill/{congress}", params=params)

    def fetch_bill_subjects(self, congress: int, bill_type: str, bill_number: str) -> Dict[str, Any]:
        """
        GET /bill/{congress}/{billType}/{billNumber}/subjects
        Retrieves legislative subjects and the policy area for a specific bill.
        """
        return self._request(f"bill/{congress}/{bill_type.lower()}/{bill_number}/subjects")

    def fetch_bill_details(self, congress: int, bill_type: str, bill_number: str) -> Dict[str, Any]:
        """
        GET /bill/{congress}/{billType}/{billNumber}
        Retrieves full detailed information for a specific bill.
        """
        return self._request(f"bill/{congress}/{bill_type.lower()}/{bill_number}")

    def fetch_bill_summaries(self, congress: int, bill_type: str, bill_number: str) -> Dict[str, Any]:
        """
        GET /bill/{congress}/{billType}/{billNumber}/summaries
        Retrieves CRS summary text for a specific bill.
        """
        return self._request(f"bill/{congress}/{bill_type.lower()}/{bill_number}/summaries")

    def fetch_bill_actions(self, congress: int, bill_type: str, bill_number: str, offset: int = 0, limit: int = 100) -> Dict[str, Any]:
        """
        GET /bill/{congress}/{billType}/{billNumber}/actions
        Retrieves action history for a specific bill.
        """
        params = {"offset": offset, "limit": limit}
        return self._request(f"bill/{congress}/{bill_type.lower()}/{bill_number}/actions", params=params)

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
