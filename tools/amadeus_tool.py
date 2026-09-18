import os
import time
import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

AMADEUS_API_KEY = os.getenv("AMADEUS_API_KEY")
AMADEUS_API_SECRET = os.getenv("AMADEUS_API_SECRET")

TOKEN_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
OFFERS_URL = "https://test.api.amadeus.com/v2/shopping/flight-offers"

_token_cache = {"access_token": None, "expires_at": 0}


def get_access_token():
    if not AMADEUS_API_KEY or not AMADEUS_API_SECRET:
        return None

    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": AMADEUS_API_KEY,
                "client_secret": AMADEUS_API_SECRET,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        _token_cache["access_token"] = data["access_token"]
        # Refresh a little early to avoid edge-of-expiry failures.
        _token_cache["expires_at"] = time.time() + data.get("expires_in", 1800) - 60

        return _token_cache["access_token"]

    except requests.exceptions.RequestException:
        return None


def get_flight_offers(dep_iata: str, arr_iata: str, date: str = None, limit: int = 3):
    """
    Returns a short formatted string of sample fare offers, or None if
    Amadeus isn't configured or the lookup fails for any reason.

    Note: this hits the Amadeus test/sandbox environment, so prices are
    illustrative sample data, not bookable real-world fares.
    """

    token = get_access_token()

    if not token:
        return None

    if not date:
        date = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()

    try:
        response = requests.get(
            OFFERS_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "originLocationCode": dep_iata,
                "destinationLocationCode": arr_iata,
                "departureDate": date,
                "adults": 1,
                "max": limit,
            },
            timeout=20,
        )
        response.raise_for_status()
        offers = response.json().get("data", [])

        if not offers:
            return None

        lines = [f"Sample fare estimates for {dep_iata} -> {arr_iata} on {date} (Amadeus sandbox data, not bookable):"]

        for offer in offers[:limit]:
            price = offer.get("price", {})
            amount = price.get("total")
            currency = price.get("currency")

            carrier = None
            itineraries = offer.get("itineraries", [])
            if itineraries and itineraries[0].get("segments"):
                carrier = itineraries[0]["segments"][0].get("carrierCode")

            lines.append(f"- {carrier or 'Unknown carrier'}: {amount} {currency}")

        return "\n".join(lines)

    except requests.exceptions.RequestException:
        return None
    except (KeyError, ValueError, IndexError):
        return None
