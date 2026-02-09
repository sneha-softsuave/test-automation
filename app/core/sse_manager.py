"""
Server-Sent Events (SSE) Manager for real-time execution updates.
SSE works over regular HTTP and is more reliable than WebSocket on Windows.
"""
from typing import Dict, List, Any
import asyncio
import json


class SSEManager:
    """Manages SSE connections for real-time updates."""

    def __init__(self):
        self.queues: Dict[str, List[asyncio.Queue]] = {}

    def create_queue(self, session_id: str) -> asyncio.Queue:
        """Create a new queue for a session."""
        queue = asyncio.Queue()
        if session_id not in self.queues:
            self.queues[session_id] = []
        self.queues[session_id].append(queue)
        print(f"SSE: Created queue for session {session_id}")
        return queue

    def remove_queue(self, session_id: str, queue: asyncio.Queue):
        """Remove a queue from a session."""
        if session_id in self.queues:
            if queue in self.queues[session_id]:
                self.queues[session_id].remove(queue)
            if not self.queues[session_id]:
                del self.queues[session_id]
        print(f"SSE: Removed queue for session {session_id}")

    async def broadcast(self, session_id: str, message: dict):
        """Broadcast a message to all queues in a session."""
        if session_id not in self.queues:
            return

        for queue in self.queues[session_id]:
            try:
                await queue.put(message)
            except Exception as e:
                print(f"SSE broadcast error: {e}")

    async def broadcast_to_session(self, session_id: str, event_type: str, data: Any):
        """Broadcast an event with type and data to a session."""
        message = {
            "type": event_type,
            "data": data
        }
        await self.broadcast(session_id, message)

    def broadcast_sync(self, session_id: str, message: dict):
        """Synchronous broadcast for use in subprocess."""
        # This will be called from the execution process
        # We'll use a different mechanism for this
        pass


# Global SSE manager instance
sse_manager = SSEManager()


# Queue for cross-process communication
import queue
execution_updates: Dict[str, queue.Queue] = {}


def get_update_queue(session_id: str) -> queue.Queue:
    """Get or create update queue for a session."""
    if session_id not in execution_updates:
        execution_updates[session_id] = queue.Queue()
    return execution_updates[session_id]


def cleanup_update_queue(session_id: str):
    """Clean up update queue for a session."""
    if session_id in execution_updates:
        del execution_updates[session_id]
