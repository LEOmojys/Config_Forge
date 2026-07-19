"""Trace store: persists generation traces for replay and debugging."""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
import uuid


class TraceStore:
    def __init__(self, trace_dir: str = "output/traces"):
        self._dir = Path(trace_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def create(self, job_type: str, requirement: str) -> str:
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        trace = {
            "trace_id": trace_id,
            "job_type": job_type,
            "requirement": requirement,
            "status": "running",
            "rounds": [],
            "final_result": None,
            "error": None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "completed_at": None,
        }
        self._write(trace_id, trace)
        return trace_id

    def add_round(self, trace_id: str, round_no: int, data: dict):
        trace = self._read(trace_id)
        if trace is None:
            return
        trace["rounds"].append({"round": round_no, **data})
        self._write(trace_id, trace)

    def complete(self, trace_id: str, status: str, result: Optional[dict] = None, error: Optional[str] = None):
        trace = self._read(trace_id)
        if trace is None:
            return
        trace["status"] = status
        trace["final_result"] = result
        trace["error"] = error
        trace["completed_at"] = datetime.now().isoformat(timespec="seconds")
        self._write(trace_id, trace)

    def get(self, trace_id: str) -> Optional[dict]:
        return self._read(trace_id)

    def list_all(self) -> list[dict]:
        traces = []
        for f in self._dir.glob("trace_*.json"):
            traces.append(json.loads(f.read_text(encoding="utf-8")))
        return sorted(traces, key=lambda item: item.get("created_at") or "", reverse=True)

    def delete(self, trace_id: str) -> bool:
        p = self._path(trace_id)
        if not p.exists():
            return False
        p.unlink()
        return True

    def clear(self, status: Optional[str] = None) -> int:
        deleted = 0
        for f in self._dir.glob("trace_*.json"):
            if status:
                try:
                    trace = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if trace.get("status") != status:
                    continue
            f.unlink()
            deleted += 1
        return deleted

    def _path(self, trace_id: str) -> Path:
        return self._dir / f"{trace_id}.json"

    def _read(self, trace_id: str) -> Optional[dict]:
        p = self._path(trace_id)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def _write(self, trace_id: str, data: dict):
        self._path(trace_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
