from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from app.api.routes import router
from app.core.config import settings
from app.core.sse_manager import sse_manager, get_update_queue, cleanup_update_queue
import json
import asyncio
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

print("\n" + "="*80)
print(f"🚀 Initializing {settings.APP_NAME} v{settings.APP_VERSION}")
print("="*80)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

logger.info(f"✓ FastAPI application created")
logger.info(f"✓ Debug mode: {settings.DEBUG}")
logger.info(f"✓ Default LLM provider: {settings.DEFAULT_LLM_PROVIDER}")

# Add CORS middleware for HTTP requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("✓ CORS middleware configured (allow all origins)")

app.include_router(router, prefix="/api/v1")
logger.info("✓ API routes registered at /api/v1")

@app.on_event("startup")
async def startup_event():
    """Log startup information"""
    logger.info("="*80)
    logger.info("🎉 APPLICATION STARTED SUCCESSFULLY")
    logger.info("="*80)
    logger.info(f"📡 Server running on: http://{settings.HOST}:{settings.PORT}")
    logger.info(f"📚 API Documentation: http://{settings.HOST}:{settings.PORT}/docs")
    logger.info(f"📊 Health Check: http://{settings.HOST}:{settings.PORT}/api/v1/health")
    logger.info("="*80)
    logger.info("🤖 AI Agents Status:")
    logger.info("   • ConfigParserAgent - Ready")
    logger.info("   • DataGeneratorAgent - Ready")
    logger.info("   • LocustGeneratorAgent - Ready")
    logger.info("   • ExecutorAgent - Ready")
    logger.info("   • AnalyzerAgent - Ready")
    logger.info("   • ReporterAgent - Ready")
    logger.info("="*80 + "\n")


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



