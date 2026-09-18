import os 
import certifi
from dotenv import load_dotenv

load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from typing import TypedDict, Annotated
import operator
import re
import uuid
import asyncio
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
import time
import groq
from langchain_groq import ChatGroq
# from tools.tavily_tool import tavily_search
# from tools.flight_tool import search_flights
from tools.flight_tool import guess_destination_city, parse_route, AIRPORTS
from tools.amadeus_tool import get_flight_offers
from tools.links_tool import build_google_maps_link, build_booking_link, build_bus_link, build_flight_link
from mcp_client import tavily_mcp_search, aviation_mcp_call, extract_destination, forecast_mcp_search, weather_mcp_search


def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Please add your Render PostgreSQL External Database URL to .env"
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url


GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing. Please add it to your .env file.")


# =========================
# LLM
# =========================

llm = ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=GROQ_API_KEY
)


def invoke_llm(messages, retries: int = 3):
    """
    Calls the LLM with retry/backoff for transient rate limits.

    Groq's on-demand tier shares a small per-minute token budget across
    the several LLM calls this pipeline makes for a single trip request,
    so a 429 here is expected under load, not exceptional.
    """

    delay = 2

    for attempt in range(retries):
        try:
            return llm.invoke(messages)
        except groq.RateLimitError:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
        except groq.APIStatusError as e:
            if e.status_code == 413:
                # Retrying the same payload against the same model won't
                # help - the caller should fall back instead.
                raise
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2


MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)")


def ensure_links_present(text: str, *sources: str) -> str:
    """
    Groq will sometimes drop or reword markdown links when it reformats
    the raw agent data into the final answer, even when told not to.
    This guarantees every booking/search link we generated deterministically
    still reaches the user by appending any that didn't make it into the
    LLM's output verbatim.
    """

    missing = []
    seen_urls = set()

    for source in sources:
        for label, url in MARKDOWN_LINK_RE.findall(str(source or "")):
            if url in text or url in seen_urls:
                continue
            seen_urls.add(url)
            missing.append(f"- [{label}]({url})")

    if not missing:
        return text

    return f"{text.rstrip()}\n\n## Booking Links\n" + "\n".join(missing)


# =========================
# State
# =========================

class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str
    start_date: str
    end_date: str
    destination: str
    flight_results: str
    bus_results: str
    hotel_results: str
    booking_results: str
    package_results: str
    itinerary: str
    llm_calls: int
    weather_results: str


def resolve_destination(query: str) -> str:
    """
    Best-effort destination name for display purposes (e.g. a hero image
    lookup on the frontend) - cheap regex guess first, LLM as fallback.
    """

    try:
        return guess_destination_city(query) or extract_destination(query) or ""
    except Exception:
        return ""


# =========================
# Flight Agent
# =========================

# def flight_agent(state: TravelState):
#     query = state["user_query"]
#     flight_data = search_flights(query)

#     return {
#         "flight_results": flight_data,
#         "messages": [
#             AIMessage(content="Flight results fetched.")
#         ],
#         "llm_calls": state.get("llm_calls", 0) + 1
#     }




# Flight Tool Router Prompt
FLIGHT_AGENT_PROMPT = """
You are a travel flight expert.

User Query:
{query}

Travel Dates:
{travel_dates}

Airport Information:
{airport_data}

Airline Information:
{airline_data}

{fare_data}

Generate:

1. Likely departure airport
2. Likely arrival airport
3. Airlines serving this route
4. Typical flight duration
5. Estimated airfare range
6. Peak season pricing warning
7. Booking advice

Return concise travel guidance.
"""




# Flight Agent
def flight_agent(state: TravelState):
    print("\nINSIDE FLIGHT AGENT\n")

    query = state["user_query"]
    start_date = state.get("start_date")
    end_date = state.get("end_date")

    travel_dates = (
        f"Departure: {start_date}, Return: {end_date}"
        if start_date
        else "Not specified by the user."
    )

    try:

        airports = asyncio.run(
            aviation_mcp_call(
                "list_airports"
            )
        )

        airlines = asyncio.run(
            aviation_mcp_call(
                "list_airlines"
            )
        )


        print("\nAIRPORTS:", airports)
        print("\nAIRLINES:", airlines)

        fare_data = ""
        dep_iata, arr_iata = parse_route(query)

        if dep_iata and arr_iata:
            fare_estimate = get_flight_offers(dep_iata, arr_iata, date=start_date)
            if fare_estimate:
                fare_data = f"Live Fare Estimate:\n{fare_estimate}"

        prompt = FLIGHT_AGENT_PROMPT.format(
            query=query,
            travel_dates=travel_dates,
            airport_data=str(airports)[:3000],
            airline_data=str(airlines)[:3000],
            fare_data=fare_data
        )

        response = invoke_llm([
            SystemMessage(
                content="You are an expert travel flight planner."
            ),
            HumanMessage(content=prompt)
        ])

        flight_data = response.content

    except Exception as e:

        flight_data = f"Flight information unavailable: {str(e)}"

    return {
        "flight_results": flight_data,
        "messages": [
            AIMessage(
                content="Flight recommendations generated"
            )
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }





# =========================
# Bus Agent
# =========================

def bus_agent(state: TravelState):
    user_query = state["user_query"]
    query = f"Bus routes, operators, and ticket booking for {user_query}"
    bus_results = asyncio.run(tavily_mcp_search(query))

    destination = state.get("destination") or resolve_destination(user_query)

    dep_iata, _ = parse_route(user_query)
    origin_city = (AIRPORTS.get(dep_iata) or {}).get("city", "") if dep_iata else ""

    bus_link = build_bus_link(origin_city, destination, date=state.get("start_date"))
    maps_link = build_google_maps_link(f"bus station in {destination}")

    bus_results = (
        f"{bus_results}\n\n"
        f"Useful links:\n"
        f"- [Search buses to {destination} on RedBus]({bus_link})\n"
        f"- [View bus stations in {destination} on Google Maps]({maps_link})"
    )

    return {
        "bus_results": bus_results,
        "messages": [
            AIMessage(content="Bus information fetched.")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }




# =========================
# Hotel Agent
# =========================

def hotel_agent(state: TravelState):
    user_query = state["user_query"]
    query = f"Best hotels for {user_query}"
    # hotel_results = tavily_search(query)
    hotel_results = asyncio.run(tavily_mcp_search(query))

    destination = state.get("destination") or resolve_destination(user_query)

    booking_link = build_booking_link(
        destination,
        checkin=state.get("start_date"),
        checkout=state.get("end_date"),
    )
    maps_link = build_google_maps_link(f"hotels in {destination}")

    hotel_results = (
        f"{hotel_results}\n\n"
        f"Useful links:\n"
        f"- [Book hotels in {destination} on Booking.com]({booking_link})\n"
        f"- [View hotels in {destination} on Google Maps]({maps_link})"
    )

    return {
        "hotel_results": hotel_results,
        "messages": [
            AIMessage(content="Hotel information fetched.")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }




# =========================
# Booking Agent
# =========================

def booking_agent(state: TravelState):
    """
    Consolidates the flight/bus/hotel booking links generated by the
    upstream agents into a single ready-to-use booking section - no
    extra search/LLM call, just deterministic link building.
    """

    user_query = state["user_query"]
    destination = state.get("destination") or resolve_destination(user_query)
    start_date = state.get("start_date")
    end_date = state.get("end_date")

    dep_iata, _ = parse_route(user_query)
    origin_city = (AIRPORTS.get(dep_iata) or {}).get("city", "") if dep_iata else ""

    flight_link = build_flight_link(origin_city, destination, date=start_date)
    bus_link = build_bus_link(origin_city, destination, date=start_date)
    hotel_link = build_booking_link(destination, checkin=start_date, checkout=end_date)

    booking_results = (
        f"- [Book flights to {destination} on Google Flights]({flight_link})\n"
        f"- [Book buses to {destination} on RedBus]({bus_link})\n"
        f"- [Book hotels in {destination} on Booking.com]({hotel_link})"
    )

    return {
        "booking_results": booking_results,
        "messages": [
            AIMessage(content="Booking links compiled.")
        ]
    }




# =========================
# Package Agent
# =========================

PACKAGE_AGENT_PROMPT = """
You are a travel package consultant.

User Query:
{query}

Travel Dates:
{travel_dates}

Flight Information:
{flight_data}

Bus Information:
{bus_data}

Hotel Information:
{hotel_data}

Based on the above, put together 3 named travel packages: Budget, Standard, and Premium.

For each package include:
1. What's included (flight/bus class or carrier tier, hotel tier, any extras)
2. An estimated total cost range for the whole trip
3. Who the package is best suited for

Keep it concise, with a clear heading for each package.
"""


def package_agent(state: TravelState):
    query = state["user_query"]
    start_date = state.get("start_date")
    end_date = state.get("end_date")

    travel_dates = (
        f"Departure: {start_date}, Return: {end_date}"
        if start_date
        else "Not specified by the user."
    )

    prompt = PACKAGE_AGENT_PROMPT.format(
        query=query,
        travel_dates=travel_dates,
        flight_data=str(state["flight_results"])[:2000],
        bus_data=str(state["bus_results"])[:1500],
        hotel_data=str(state["hotel_results"])[:2000],
    )

    try:
        response = invoke_llm([
            SystemMessage(content="You are an expert travel package consultant."),
            HumanMessage(content=prompt)
        ])
        package_results = response.content

    except (groq.RateLimitError, groq.APIStatusError):
        package_results = (
            "Package summary is temporarily unavailable "
            "(the AI provider rejected the request). "
            "The flight, bus, and hotel details above are still valid "
            "- please try again in a minute for tiered package options."
        )

    return {
        "package_results": package_results,
        "messages": [
            AIMessage(content="Travel packages generated.")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }




# =========================
# Weather Agent
# =========================

def weather_agent(state: TravelState):

    query = state["user_query"]

    # Try the cheap regex-based guess first so we don't spend an extra
    # LLM call just to pull a city name out of the query.
    city = guess_destination_city(query)

    if not city:
        city = extract_destination(query)

    try:
        weather_data = asyncio.run(
            weather_mcp_search(city)
        )

        forecast_data = asyncio.run(
            forecast_mcp_search(city)
        )

        weather_results = f"""
        Current Weather:
        {weather_data}

        Forecast:
        {forecast_data}
        """

    except Exception as e:
        weather_results = f"Weather information unavailable: {str(e)}"

    return {
        "weather_results": weather_results,
        "messages": [
            AIMessage(
                content="Weather information fetched"
            )
        ]
    }




# =========================
# Itinerary Agent
# =========================

def itinerary_agent(state: TravelState):
    start_date = state.get("start_date")
    end_date = state.get("end_date")

    travel_dates = (
        f"Departure: {start_date}, Return: {end_date}"
        if start_date
        else "Not specified by the user."
    )

    prompt = f"""
Create a complete travel itinerary.

User Query:
{state['user_query']}

Travel Dates:
{travel_dates}

Flight Results:
{str(state['flight_results'])[:3000]}

Bus Results:
{str(state['bus_results'])[:2000]}

Hotel Results:
{str(state['hotel_results'])[:3000]}

Weather Results:
{str(state['weather_results'])[:2000]}

Make the itinerary practical, budget-aware, and easy to follow.
If travel dates are given, label each day with its actual calendar date (Day 1 - {start_date if start_date else "..."}, etc).
Any Markdown links (e.g. [text](url)) present in the Hotel Results must be copied into the output exactly as-is, unmodified.
"""

    try:
        response = invoke_llm([
            SystemMessage(content="You are an expert travel planner."),
            HumanMessage(content=prompt)
        ])
        itinerary = response.content
        message = response

    except (groq.RateLimitError, groq.APIStatusError):
        itinerary = (
            "Itinerary generation is temporarily unavailable "
            "(the AI provider rejected the request). "
            "The flight, hotel, and weather details above are still valid "
            "— please try again in a minute for the full itinerary."
        )
        message = AIMessage(content=itinerary)

    return {
        "itinerary": itinerary,
        "messages": [message],
        "llm_calls": state.get("llm_calls", 0) + 1
    }



# =========================
# Final Response Agent
# =========================

def final_agent(state: TravelState):
    start_date = state.get("start_date")
    end_date = state.get("end_date")

    travel_dates = (
        f"Departure: {start_date}, Return: {end_date}"
        if start_date
        else "Not specified by the user."
    )

    final_prompt = f"""
Generate the final travel response for the user.

User Request:
{state['user_query']}

Travel Dates:
{travel_dates}

Flights:
{str(state['flight_results'])[:2000]}

Buses:
{str(state['bus_results'])[:1500]}

Hotels:
{str(state['hotel_results'])[:2000]}

Weather:
{str(state['weather_results'])[:1500]}

Itinerary:
{str(state['itinerary'])[:4000]}

Booking Links:
{str(state['booking_results'])[:1000]}

Travel Packages:
{str(state['package_results'])[:2500]}

Format the final answer beautifully using these sections:

1. Trip Summary
2. Flight Information
3. Bus Information
4. Hotel Suggestions
5. Weather Information
6. Day-by-Day Itinerary
7. Estimated Budget
8. Travel Packages
9. Booking Links
10. Final Recommendations


Important:
- Be clear and practical.
- If travel dates were given, state them clearly in the Trip Summary.
- Mention that live flight API may not provide ticket prices if pricing is unavailable.
- If bus travel is not practical for this route (e.g. overseas/international trip), say so briefly in Bus Information instead of omitting the section.
- Never invent a specific fare, fee, or price that isn't present in the data above. If the data doesn't give a concrete number, describe it as a rough estimate or say it varies by operator/season and point the reader to the booking link - do not state a single exact figure as fact.
- Include weather-based travel advice.
- The Travel Packages section must present the Budget/Standard/Premium packages from the Travel Packages data above, each with what's included and its estimated cost range.
- Any Markdown links (e.g. [text](url)) present in the Bus Information, Hotel Suggestions, or Booking Links must be copied into their respective sections exactly as-is, unmodified - do not remove or reword them.
- The Booking Links section must reproduce every link from the Booking Links data above exactly as-is, as a bullet list.
- Keep the response useful for real travel planning.
"""

    try:
        response = invoke_llm([
            SystemMessage(content="You are a professional AI travel booking assistant."),
            HumanMessage(content=final_prompt)
        ])
        final_text = response.content

    except (groq.RateLimitError, groq.APIStatusError):
        final_text = f"""
Trip Summary
We hit a temporary issue with the AI provider while formatting the final summary, but here's everything gathered so far:

Flight Information
{str(state['flight_results'])[:2000]}

Bus Information
{str(state['bus_results'])[:1500]}

Hotel Suggestions
{str(state['hotel_results'])[:2000]}

Weather Information
{str(state['weather_results'])[:1500]}

Day-by-Day Itinerary
{str(state['itinerary'])[:4000]}

Travel Packages
{str(state['package_results'])[:2500]}

Booking Links
{str(state['booking_results'])[:1000]}

Please try again in a minute for a polished final response.
"""

    final_text = ensure_links_present(
        final_text,
        state.get("booking_results"),
        state.get("bus_results"),
        state.get("hotel_results"),
    )

    return {
        "messages": [AIMessage(content=final_text)],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


# =========================
# Build Graph
# =========================

graph = StateGraph(TravelState)

graph.add_node("flight_agent", flight_agent)
graph.add_node("bus_agent", bus_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("booking_agent", booking_agent)
graph.add_node("package_agent", package_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("final_agent", final_agent)

graph.add_edge(START, "flight_agent")
graph.add_edge("flight_agent", "bus_agent")
graph.add_edge("bus_agent", "hotel_agent")
graph.add_edge("hotel_agent", "booking_agent")
graph.add_edge("booking_agent", "package_agent")
graph.add_edge("package_agent", "weather_agent")
graph.add_edge("weather_agent", "itinerary_agent")
graph.add_edge("itinerary_agent", "final_agent")
graph.add_edge("final_agent", END)


# =========================
# PostgreSQL Checkpointer
# =========================
DATABASE_URL = get_database_url()

_conn = psycopg.connect(
    DATABASE_URL,
    autocommit=True,
    row_factory=dict_row
)

checkpointer = PostgresSaver(_conn)
checkpointer.setup()

travel_graph = graph.compile(checkpointer=checkpointer)


# =========================
# Trip History
# =========================
# Separate small pool from the checkpointer's dedicated connection above,
# used only for the trips table (history list/detail).

trips_pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, kwargs={"row_factory": dict_row})

with trips_pool.connection() as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            id SERIAL PRIMARY KEY,
            thread_id TEXT NOT NULL,
            user_query TEXT NOT NULL,
            answer TEXT,
            flight_results TEXT,
            bus_results TEXT,
            hotel_results TEXT,
            booking_results TEXT,
            package_results TEXT,
            weather_results TEXT,
            itinerary TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute("ALTER TABLE trips ADD COLUMN IF NOT EXISTS bus_results TEXT")
    conn.execute("ALTER TABLE trips ADD COLUMN IF NOT EXISTS booking_results TEXT")
    conn.execute("ALTER TABLE trips ADD COLUMN IF NOT EXISTS package_results TEXT")


def save_trip(result: dict):
    """
    Best-effort trip history save. Never raises - a history save
    failure should not fail the underlying trip response.
    """

    try:
        with trips_pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO trips
                    (thread_id, user_query, answer, flight_results, bus_results, hotel_results, booking_results, package_results, weather_results, itinerary)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(result.get("thread_id") or ""),
                    str(result.get("user_query") or ""),
                    str(result.get("answer") or ""),
                    str(result.get("flight_results") or ""),
                    str(result.get("bus_results") or ""),
                    str(result.get("hotel_results") or ""),
                    str(result.get("booking_results") or ""),
                    str(result.get("package_results") or ""),
                    str(result.get("weather_results") or ""),
                    str(result.get("itinerary") or ""),
                )
            )
    except Exception as e:
        print("Could not save trip history:", e)


def list_trips(limit: int = 50):
    with trips_pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT id, thread_id, user_query, created_at
            FROM trips
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,)
        ).fetchall()

    return rows


def get_trip(trip_id: int):
    with trips_pool.connection() as conn:
        row = conn.execute(
            "SELECT * FROM trips WHERE id = %s",
            (trip_id,)
        ).fetchone()

    return row



# =========================
# Function for FastAPI
# =========================

def run_travel_agent(user_input: str, thread_id: str | None = None, start_date: str | None = None, end_date: str | None = None):
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    result = travel_graph.invoke(
        {
            "messages": [
                HumanMessage(content=user_input)
            ],
            "user_query": user_input,
            "start_date": start_date or "",
            "end_date": end_date or "",
            "destination": resolve_destination(user_input),
            "flight_results": "",
            "bus_results": "",
            "hotel_results": "",
            "booking_results": "",
            "package_results": "",
            "weather_results": "",
            "itinerary": "",
            "llm_calls": 0
        },
        config=config
    )

    final_answer = result["messages"][-1].content

    trip_result = {
        "thread_id": thread_id,
        "user_query": user_input,
        "destination": result.get("destination", ""),
        "answer": final_answer,
        "flight_results": result.get("flight_results", ""),
        "bus_results": result.get("bus_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "booking_results": result.get("booking_results", ""),
        "package_results": result.get("package_results", ""),
        "weather_results": result.get("weather_results", ""),
        "itinerary": result.get("itinerary", ""),
        "llm_calls": result.get("llm_calls", 0),
    }

    save_trip(trip_result)

    return trip_result


# =========================
# Streaming version for the SSE endpoint
# =========================

STAGE_LABELS = {
    "flight_agent": "Flights",
    "bus_agent": "Buses",
    "hotel_agent": "Hotels",
    "booking_agent": "Booking",
    "package_agent": "Packages",
    "weather_agent": "Weather",
    "itinerary_agent": "Itinerary",
    "final_agent": "Final summary",
}


def run_travel_agent_stream(user_input: str, thread_id: str | None = None, start_date: str | None = None, end_date: str | None = None):
    """
    Yields one dict per completed agent step, then a final
    {"stage": "complete", ...trip_result} once the graph finishes.
    """

    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    state = {
        "messages": [
            HumanMessage(content=user_input)
        ],
        "user_query": user_input,
        "start_date": start_date or "",
        "end_date": end_date or "",
        "destination": resolve_destination(user_input),
        "flight_results": "",
        "bus_results": "",
        "hotel_results": "",
        "booking_results": "",
        "package_results": "",
        "weather_results": "",
        "itinerary": "",
        "llm_calls": 0
    }

    try:
        final_state = None

        for update in travel_graph.stream(state, config=config, stream_mode="updates"):
            for node_name, node_output in update.items():
                final_state = node_output
                yield {
                    "stage": node_name,
                    "label": STAGE_LABELS.get(node_name, node_name),
                    "status": "done"
                }

        answer = final_state["messages"][-1].content if final_state else ""

        # Re-fetch the accumulated state via the checkpointer so the
        # complete event has every field, not just the last node's delta.
        snapshot = travel_graph.get_state(config).values

        trip_result = {
            "thread_id": thread_id,
            "user_query": user_input,
            "destination": snapshot.get("destination", ""),
            "answer": answer,
            "flight_results": snapshot.get("flight_results", ""),
            "bus_results": snapshot.get("bus_results", ""),
            "hotel_results": snapshot.get("hotel_results", ""),
            "booking_results": snapshot.get("booking_results", ""),
            "package_results": snapshot.get("package_results", ""),
            "weather_results": snapshot.get("weather_results", ""),
            "itinerary": snapshot.get("itinerary", ""),
            "llm_calls": snapshot.get("llm_calls", 0),
        }

        save_trip(trip_result)

        yield {"stage": "complete", **trip_result}

    except Exception as e:
        yield {"stage": "error", "message": str(e)}