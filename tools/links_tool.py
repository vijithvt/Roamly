from urllib.parse import quote_plus


def build_google_maps_link(place: str) -> str:
    """
    Universal Google Maps search link - no API key required.
    """

    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(place)}"


def build_flight_link(origin: str, destination: str, date: str = None) -> str:
    """
    Universal Google Flights search link - no API key required.
    date is expected as YYYY-MM-DD, if provided.
    """

    query = f"Flights from {origin} to {destination}" if origin else f"Flights to {destination}"

    if date:
        query += f" on {date}"

    return f"https://www.google.com/travel/flights?q={quote_plus(query)}"


def build_bus_link(origin: str, destination: str, date: str = None) -> str:
    """
    Universal redBus search link - no API key required.
    date is expected as YYYY-MM-DD, if provided.
    """

    link = f"https://www.redbus.in/search?fromCityName={quote_plus(origin)}&toCityName={quote_plus(destination)}"

    if date:
        link += f"&onward={date}"

    return link


def build_booking_link(destination: str, checkin: str = None, checkout: str = None) -> str:
    """
    Universal Booking.com search link - no API key required.
    checkin/checkout are expected as YYYY-MM-DD strings, if provided.
    """

    link = f"https://www.booking.com/searchresults.html?ss={quote_plus(destination)}"

    if checkin:
        link += f"&checkin={checkin}"

    if checkout:
        link += f"&checkout={checkout}"

    return link
