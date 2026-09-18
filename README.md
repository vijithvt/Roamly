#  Roamly — A Multi-Agent Travel Planner with MCP

An open-source AI travel planner that turns a natural-language trip request into a practical travel plan with flight suggestions, hotel ideas, weather details, and a day-by-day itinerary. The project uses a multi-agent workflow built with LangGraph, LangChain, FastAPI, and MCP tooling.

## Why this project?

Planning a trip usually means jumping between multiple websites, tools, and spreadsheets. This project brings that flow into one experience by combining:

- a flight-search agent,
- a bus-search agent,
- a hotel-research agent,
- a ticket-booking agent,
- a travel-package agent,
- a weather agent,
- an itinerary-planning agent, and
- a final response agent,

all coordinated through a LangGraph workflow with MCP-based tool integrations.

## Features

- ✈️ Flight research using AviationStack, with optional sample fare estimates via Amadeus
- 🏨 Hotel suggestions using Tavily search
- 🌤 Weather lookup via a custom MCP tool
- 🧠 Multi-agent orchestration with LangGraph and MCP
- 📝 Structured travel itinerary generation
- 🌐 FastAPI backend with a simple web interface
- 📡 Live per-agent progress in the UI (Server-Sent Events)
- 🗂 Trip history, stored in PostgreSQL and browsable from the UI
- 📄 PDF export and 📅 Add-to-Calendar (.ics) for any generated plan
- 💾 Conversation state persistence using PostgreSQL
- ⚡ LLM-powered responses with Groq

## Tech Stack

- Python 3.10+
- FastAPI
- Jinja2 + HTML/CSS/JavaScript frontend
- LangGraph
- LangChain
- Groq LLMs
- PostgreSQL
- Tavily API
- AviationStack API
- MCP via `langchain-mcp-adapters` and `mcp`

## State and MCP Integration

This project integrates MCP in several places:

- `Tavily` search uses a remote MCP endpoint at `https://mcp.tavily.com/mcp/`
- `AviationStack` uses a local stdio MCP command: `uvx aviationstack-mcp`
- `Weather` is implemented with a custom local MCP server in `custom_weather_mcp_server.py`

The MCP client is defined in `mcp_client.py`, which exposes async helper functions for:

- `tavily_mcp_search`
- `aviation_mcp_call`
- `weather_mcp_search`
- `forecast_mcp_search`
- `extract_destination`

The main travel workflow in `backend.py` calls these helpers from the flight, hotel, and weather agents.

## Project Structure

```text
.
├── app.py                      # FastAPI app entry point
├── backend.py                  # LangGraph travel workflow
├── mcp_client.py               # MCP client and tool integration
├── custom_weather_mcp_server.py# Local weather MCP server
├── requirements.txt            # Python dependencies
├── static/                     # Static frontend assets
├── templates/                  # HTML templates
└── tools/                      # Flight and web search integrations
```

## Prerequisites

Before running the project locally, make sure you have:

- Python 3.10 or newer installed
- PostgreSQL running and accessible
- API keys for:
  - Groq
  - Tavily
  - AviationStack
  - OpenWeather
  - Amadeus (optional, free self-service sandbox — for sample flight fares; see below)
- `uvx` available for local `aviationstack-mcp` usage (or adjust `mcp_client.py` accordingly)

## Environment Variables

Create a `.env` file in the project root with the following variables:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/travel_db
GROQ_API_KEY=your_groq_api_key
AVIATIONSTACK_API_KEY=your_aviationstack_api_key
TAVILY_API_KEY=your_tavily_api_key
OPENWEATHER_API_KEY=your_openweather_api_key
DEFAULT_ORIGIN_IATA=DAC

# Optional - enables sample fare estimates in the flight section.
# Free sandbox keys: https://developers.amadeus.com/self-service
AMADEUS_API_KEY=your_amadeus_api_key
AMADEUS_API_SECRET=your_amadeus_api_secret
```

Note on Amadeus: the free self-service tier only gives access to the *test/sandbox* environment, so fares returned are illustrative sample data, not real bookable prices. Leave these two variables unset and the flight agent falls back to its existing LLM-estimated pricing, unchanged.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Running the App

Start the FastAPI server:

```bash
python app.py
```

Then open your browser at:

```text
http://127.0.0.1:8000/
```

## Running with Docker

You can run the whole stack (app + PostgreSQL) with Docker Compose instead of installing Python and Postgres locally.

1. Copy `.env.example` to `.env` and fill in your API keys:

   ```bash
   cp .env.example .env
   ```

   Leave `DATABASE_URL` pointing at the bundled `db` service — it's already wired up in `docker-compose.yml`.

2. Build and start the containers:

   ```bash
   docker compose up --build
   ```

3. Open the app at:

   ```text
   http://127.0.0.1:8080/
   ```

   (Port 8080 on the host maps to port 8000 in the container; change the left-hand side in `docker-compose.yml` under `app.ports` if it conflicts with something else on your machine — same for `db.ports` and 5433 if you already have Postgres running locally.)

To stop everything:

```bash
docker compose down
```

To rebuild after changing dependencies or code:

```bash
docker compose up --build
```

## Using MCP Tools

The app uses MCP behind the scenes, so there is no separate frontend change required after the environment is set up.

If you need to customize the weather MCP server command, edit `mcp_client.py` and update the `weather` tool path to your local Python environment.

## API Endpoints

- GET /health - Health check
- POST /api/travel - Submit a travel request (single JSON response)
- GET /api/travel/stream?message=...&thread_id=... - Same, but streams per-agent progress via Server-Sent Events (used by the web UI)
- GET /api/trips - List saved trip history (id, query, timestamp)
- GET /api/trips/{id} - Full detail for one saved trip

Example request:

```bash
curl -X POST http://127.0.0.1:8000/api/travel \
  -H "Content-Type: application/json" \
  -d '{"message":"Plan a 3-day trip to Tokyo with a budget of $1200"}'
```

Every successful trip (from either endpoint) is saved to the `trips` table in PostgreSQL automatically; the web UI's "History" button reads it back through `/api/trips`.

## How the Workflow Works

1. The user submits a travel request.
2. The flight agent uses MCP-backed AviationStack data.
3. The hotel agent uses a remote Tavily MCP search.
4. The weather agent calls the custom weather MCP server.
5. The itinerary agent creates a practical travel plan.
6. The final response is returned through the web API.

## Contributing

Contributions are welcome. If you want to improve the app, add new travel features, or fix issues:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Open a pull request

## Acknowledgments

This project is built with the help of modern LLM tooling, MCP integrations, and travel APIs. It is intended as a practical example of combining LangGraph agents with real-world applications.
