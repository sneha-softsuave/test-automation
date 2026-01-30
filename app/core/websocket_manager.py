"""
WebSocket Connection Manager for real-time execution updates.
"""
from typing import Dict, List, Optional
from fastapi import WebSocket
import asyncio
import json


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            if session_id not in self.active_connections:
                self.active_connections[session_id] = []
            self.active_connections[session_id].append(websocket)
        print(f"WebSocket connected: {session_id}")

    async def disconnect(self, websocket: WebSocket, session_id: str):
        """Remove a WebSocket connection."""
        async with self._lock:
            if session_id in self.active_connections:
                if websocket in self.active_connections[session_id]:
                    self.active_connections[session_id].remove(websocket)
                if not self.active_connections[session_id]:
                    del self.active_connections[session_id]
        print(f"WebSocket disconnected: {session_id}")

    async def broadcast(self, session_id: str, message: dict):
        """Broadcast a message to all connections in a session."""
        if session_id not in self.active_connections:
            return

        message_json = json.dumps(message)
        disconnected = []

        for connection in self.active_connections[session_id]:
            try:
                await connection.send_text(message_json)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected clients
        for conn in disconnected:
            await self.disconnect(conn, session_id)

    async def send_step_update(
        self,
        session_id: str,
        test_id: str,
        step_num: int,
        status: str,
        message: str,
        details: Optional[dict] = None
    ):
        """Send a step execution update."""
        await self.broadcast(session_id, {
            "type": "step_update",
            "test_id": test_id,
            "step": step_num,
            "status": status,
            "message": message,
            "details": details or {}
        })

    async def send_test_update(
        self,
        session_id: str,
        test_id: str,
        status: str,
        message: str
    ):
        """Send a test case status update."""
        await self.broadcast(session_id, {
            "type": "test_update",
            "test_id": test_id,
            "status": status,
            "message": message
        })

    async def send_execution_start(
        self,
        session_id: str,
        total_tests: int,
        total_steps: int
    ):
        """Send execution start notification."""
        await self.broadcast(session_id, {
            "type": "execution_start",
            "total_tests": total_tests,
            "total_steps": total_steps
        })

    async def send_execution_complete(
        self,
        session_id: str,
        passed: int,
        failed: int,
        total: int
    ):
        """Send execution complete notification."""
        await self.broadcast(session_id, {
            "type": "execution_complete",
            "passed": passed,
            "failed": failed,
            "total": total
        })

    async def send_log(
        self,
        session_id: str,
        level: str,
        message: str
    ):
        """Send a log message."""
        await self.broadcast(session_id, {
            "type": "log",
            "level": level,
            "message": message
        })


# Global connection manager instance
manager = ConnectionManager()
