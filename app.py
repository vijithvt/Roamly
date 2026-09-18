import json
from pathlib import Path
import traceback
import uvicorn

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from backend import run_travel_agent, run_travel_agent_stream, list_trips, get_trip

# This is to allow nested event loops for async calls in FastAPI
import nest_asyncio
nest_asyncio.apply()


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Roamly",
    description="LangGraph Multi-Agent Travel Planner with FastAPI Frontend",
    version="1.0.0"
)


app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static"
)


templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)



class TravelRequest(BaseModel):
    message: str
    thread_id: str | None = None
    start_date: str | None = None
    end_date: str | None = None



@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )


@app.post("/api/travel")
async def travel_planner(request_data: TravelRequest):
    try:
        user_message = request_data.message.strip()

        if not user_message:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Message cannot be empty."
                }
            )

        result = run_travel_agent(
            user_input=user_message,
            thread_id=request_data.thread_id,
            start_date=request_data.start_date,
            end_date=request_data.end_date
        )

        return JSONResponse(
            content={
                "success": True,
                "thread_id": result["thread_id"],
                "destination": result.get("destination", ""),
                "answer": result["answer"],
                "flight_results": result["flight_results"],
                "bus_results": result["bus_results"],
                "hotel_results": result["hotel_results"],
                "booking_results": result["booking_results"],
                "package_results": result["package_results"],
                "itinerary": result["itinerary"],
                "llm_calls": result["llm_calls"],
            }
        )

    except Exception as e:
        print("ERROR:", e)
        traceback.print_exc()

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )



@app.get("/api/travel/stream")
async def travel_planner_stream(message: str, thread_id: str | None = None, start_date: str | None = None, end_date: str | None = None):
    user_message = message.strip()

    def event_generator():
        if not user_message:
            yield f"data: {json.dumps({'stage': 'error', 'message': 'Message cannot be empty.'})}\n\n"
            return

        for event in run_travel_agent_stream(user_input=user_message, thread_id=thread_id, start_date=start_date, end_date=end_date):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/trips")
async def trips_list():
    try:
        rows = list_trips()
        return JSONResponse(content=jsonable_encoder({"success": True, "trips": rows}))
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/trips/{trip_id}")
async def trip_detail(trip_id: int):
    try:
        row = get_trip(trip_id)

        if not row:
            return JSONResponse(status_code=404, content={"success": False, "error": "Trip not found."})

        return JSONResponse(content=jsonable_encoder({"success": True, "trip": row}))
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "message": "AI Travel Planner API is running"
    }


@app.get("/favicon.ico")
async def favicon():
    return JSONResponse(content={})



if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )