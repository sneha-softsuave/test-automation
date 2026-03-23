"""
Async non-blocking LLM call logger.
log_async() schedules the write via asyncio.create_task() — zero blocking.
In-memory store (resets on server restart). Can be extended to DB later.
"""
import threading
from dataclasses import dataclass, asdict
from typing import List

@dataclass
class LLMCallRecord:
    timestamp: str; agent: str; provider: str; model: str
    input_tokens: int; output_tokens: int; total_tokens: int; cost_usd: float

_lock = threading.Lock()
_records: List[LLMCallRecord] = []
_MAX = 200

# Per-command token accumulator keyed by OS thread ID.
# Each recorder/command call runs in its own plain thread — this is safe.
_thread_trackers: dict = {}
_tt_lock = threading.Lock()

def start_command_tracking() -> None:
    """Call at the start of _execute() — resets the tracker for this thread."""
    tid = threading.get_ident()
    with _tt_lock:
        _thread_trackers[tid] = {"total_tokens": 0, "cost_usd": 0.0}

def end_command_tracking() -> dict:
    """Call at the end of _execute() — returns accumulated totals and cleans up."""
    tid = threading.get_ident()
    with _tt_lock:
        return _thread_trackers.pop(tid, {"total_tokens": 0, "cost_usd": 0.0})

def log_async(data: dict):
    """Call from anywhere — never blocks, never raises. Synchronous O(1) append."""
    try:
        r = LLMCallRecord(**data)
        global _records
        with _lock:
            _records.append(r)
            if len(_records) > _MAX:
                _records = _records[-_MAX:]
        # Also accumulate into the per-command tracker for this thread (if active)
        tid = threading.get_ident()
        with _tt_lock:
            tracker = _thread_trackers.get(tid)
        if tracker is not None:
            tracker["total_tokens"] += data["total_tokens"]
            tracker["cost_usd"] = round(tracker["cost_usd"] + data["cost_usd"], 8)
    except Exception:
        pass

def get_stats() -> dict:
    with _lock:
        if not _records:
            return {"total_calls":0,"total_input_tokens":0,"total_output_tokens":0,
                    "total_tokens":0,"total_cost_usd":0.0,"by_provider":{},"recent_calls":[]}
        total_in  = sum(r.input_tokens  for r in _records)
        total_out = sum(r.output_tokens for r in _records)
        by_prov: dict = {}
        for r in _records:
            p = by_prov.setdefault(r.provider,
                {"calls":0,"input_tokens":0,"output_tokens":0,"total_tokens":0,"cost_usd":0.0})
            p["calls"]+=1; p["input_tokens"]+=r.input_tokens
            p["output_tokens"]+=r.output_tokens; p["total_tokens"]+=r.total_tokens
            p["cost_usd"]=round(p["cost_usd"]+r.cost_usd,8)
        return {"total_calls":len(_records),"total_input_tokens":total_in,
                "total_output_tokens":total_out,"total_tokens":total_in+total_out,
                "total_cost_usd":round(sum(r.cost_usd for r in _records),8),
                "by_provider":by_prov,
                "recent_calls":[asdict(r) for r in reversed(_records[-10:])]}

def reset_records():
    global _records
    with _lock: _records = []
