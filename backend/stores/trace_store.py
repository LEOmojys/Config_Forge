"""Trace store: persists generation traces for replay and debugging."""
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
import uuid


class TraceStore:
    def __init__(self, trace_dir: str = "output/traces"):
        self._dir = Path(trace_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def create(self, job_type: str, requirement: str, metadata: Optional[dict] = None) -> str:
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
        if metadata:
            trace.update(metadata)
        self._write(trace_id, trace)
        return trace_id

    def add_batch_item(self, trace_id: str, item: dict):
        trace = self._read(trace_id)
        if trace is None:
            return
        trace.setdefault("batch_items", []).append(item)
        self._write(trace_id, trace)

    def add_round(self, trace_id: str, round_no: int, data: dict):
        trace = self._read(trace_id)
        if trace is None:
            return
        trace["rounds"].append({"round": round_no, **data})
        self._write(trace_id, trace)

    def complete(self, trace_id: str, status: str, result: Optional[dict] = None,
                 error: Optional[str] = None, config_name: str = "") -> str:
        """完成 trace 并重命名为可读文件名。"""
        trace = self._read(trace_id)
        if trace is None:
            return trace_id
        trace["status"] = status
        trace["final_result"] = result
        trace["error"] = error
        trace["completed_at"] = datetime.now().isoformat(timespec="seconds")

        # 生成可读文件名：trace__{type}__{name}__{短id}.json
        if config_name:
            new_id = self._readable_id(trace_id, trace.get("job_type", ""), config_name)
            trace["trace_id"] = new_id
            self._write(trace_id, trace)  # 先保存旧文件
            self._rename(trace_id, new_id)  # 再重命名
            trace["trace_id"] = new_id
            return new_id
        else:
            self._write(trace_id, trace)
            return trace_id

    def rename(self, trace_id: str, config_name: str) -> Optional[str]:
        """手动重命名 trace 文件，返回新的 trace_id。"""
        trace = self._read(trace_id)
        if trace is None:
            return None
        new_id = self._readable_id(trace_id, trace.get("job_type", ""), config_name)
        self._rename(trace_id, new_id)
        trace["trace_id"] = new_id
        self._write(new_id, trace)
        return new_id

    def _readable_id(self, trace_id: str, job_type: str, config_name: str) -> str:
        """生成可读 trace_id: trace__{type}__{name}__{短uuid}"""
        safe_name = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", config_name)
        safe_name = re.sub(r"_+", "_", safe_name).strip("_")[:20]
        short = trace_id.replace("trace_", "")[-6:]
        return f"trace__{job_type}__{safe_name}__{short}"

    def _rename(self, old_id: str, new_id: str):
        """重命名磁盘上的 trace 文件。"""
        old_path = self._path(old_id)
        new_path = self._path(new_id)
        if old_path.exists() and not new_path.exists():
            old_path.rename(new_path)

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
