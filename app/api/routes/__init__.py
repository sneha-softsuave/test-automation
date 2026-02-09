from fastapi import APIRouter
from app.api.routes import health, excel, test_cases, scraper, websocket, deep_agent, agent_chat, load_test

router = APIRouter()

# Include all route modules
router.include_router(health.router, tags=["Health"])
router.include_router(excel.router, tags=["Excel"])
router.include_router(test_cases.router, tags=["Test Cases"])
router.include_router(scraper.router, tags=["Scraper"])
router.include_router(websocket.router, tags=["WebSocket"])
router.include_router(deep_agent.router, tags=["Deep Agent"])
router.include_router(agent_chat.router, tags=["Agent Chat"])
router.include_router(load_test.router, tags=["Load Test"])
