"""
The Agency — FastAPI backend

Run with: uvicorn main:app --host 0.0.0.0 --port 8000
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from routers.content_team import router as content_router
from routers.social_team import router as social_router
from routers.assistant import router as assistant_router
from routers.seo_audit import router as seo_audit_router
from routers.agency import router as agency_router
from routers.video_team import router as video_router
from routers.on_page_opt import router as on_page_opt_router
from routers.setup import router as setup_router

app = FastAPI(title="The Agency")

# ---------------------------------------------------------------------------
# Static files + root
# ---------------------------------------------------------------------------

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(static_dir / "index.html"))


# ---------------------------------------------------------------------------
# Director summary — powers the home dashboard
# ---------------------------------------------------------------------------

@app.get("/api/director/summary")
async def director_summary():
    from state import redis_client, get_activity_log

    # Scan all team session keys and aggregate counts
    keys = [k async for k in redis_client.scan_iter("session:*")]
    raw_values = await redis_client.mget(keys) if keys else []
    sessions = [json.loads(v) for v in raw_values if v]

    content_saved = sum(
        len(s.get("saved_articles", []))
        for s in sessions
        if s.get("team") == "content"
    )
    social_saved = sum(
        len(s.get("saved_posts", []))
        for s in sessions
        if s.get("team") == "social"
    )
    audits_done = sum(
        1
        for s in sessions
        if s.get("team") == "seo_audit" and s.get("stage") == "done"
    )
    video_saved = sum(
        len(s.get("saved_briefs", []))
        for s in sessions
        if s.get("team") == "video"
    )
    opt_done = sum(
        1
        for s in sessions
        if s.get("team") == "on_page_opt" and s.get("stage") == "done"
    )

    activity = await get_activity_log(limit=10)

    return JSONResponse({
        "content_saved": content_saved,
        "social_saved": social_saved,
        "audits_done": audits_done,
        "video_saved": video_saved,
        "opt_done": opt_done,
        "activity": activity,
    })


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(content_router, prefix="/api/content")
app.include_router(social_router, prefix="/api/social")
app.include_router(assistant_router, prefix="/api/assistant")
app.include_router(seo_audit_router, prefix="/api/seo-audit")
app.include_router(agency_router, prefix="/api/agency")
app.include_router(video_router, prefix="/api/video")
app.include_router(on_page_opt_router, prefix="/api/on-page-opt")
app.include_router(setup_router, prefix="/api/setup")
