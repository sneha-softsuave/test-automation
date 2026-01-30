from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from app.api.routes import router
from app.core.config import settings
from app.core.sse_manager import sse_manager, get_update_queue, cleanup_update_queue
import json
import asyncio


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

# Add CORS middleware for HTTP requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


# SSE endpoint for real-time updates (replaces WebSocket)
@app.get("/api/v1/sse/{session_id}")
async def sse_endpoint(session_id: str):
    """
    Server-Sent Events endpoint for real-time execution updates.
    More reliable than WebSocket on Windows.
    """
    print(f"📡 SSE connection request from: {session_id}", flush=True)

    async def event_generator():
        queue = sse_manager.create_queue(session_id)
        try:
            # Send connection confirmation
            yield f"data: {json.dumps({'type': 'connected', 'session_id': session_id})}\n\n"
            print(f"✅ SSE connected: {session_id}", flush=True)

            while True:
                try:
                    # Wait for message with timeout (for keepalive)
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            print(f"📡 SSE disconnected: {session_id}", flush=True)
        finally:
            sse_manager.remove_queue(session_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/")
async def root():
    return {
        "message": "Test Automation Agent API",
        "version": settings.APP_VERSION
    }



