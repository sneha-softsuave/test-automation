#!/usr/bin/env python
"""
Backend Server Entry Point

This script starts the FastAPI backend server with uvicorn.

Usage:
    python run.py                  # Standard run
    ./venv/bin/python run.py       # With venv explicitly

The server will:
- Load all API routes and services
- Initialize 6 AI agents (ConfigParser, DataGenerator, LocustGenerator, Executor, Analyzer, Reporter)
- Enable hot-reload in DEBUG mode
- Exclude generated files from reload watching
- Listen on 0.0.0.0:9000 by default
"""
import sys
import asyncio

# Fix Windows asyncio subprocess issue - must be done before any async code runs
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    print(f"🚀 Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"📡 Server: http://{settings.HOST}:{settings.PORT}")
    print(f"📚 API Docs: http://{settings.HOST}:{settings.PORT}/docs")
    print(f"🔧 Debug Mode: {settings.DEBUG}")
    print(f"🤖 Default LLM: {settings.DEFAULT_LLM_PROVIDER}")
    print("\n" + "="*60 + "\n")

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        reload_excludes=[
            "generated_locustfiles/*",
            "load_test_results/*",
            "uploads/*",
            "projects/*",
            "*.log"
        ]
    )
