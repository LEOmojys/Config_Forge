"""Data contracts for requirement-to-output acceptance tests."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class AcceptanceCase:
    id: str
    job_type: str
    requirement: str
    expected: dict[str, Any]
    description: str = ""
    batch_count: int = 1
    enable_critic: bool = False
    repeat: int = 1
    modes: tuple[str, ...] = ("mock", "live")
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AcceptanceCase":
        required = {"id", "job_type", "requirement", "expected"}
        missing = sorted(required - raw.keys())
        if missing:
            raise ValueError(f"Acceptance case missing fields: {missing}")
        if raw["job_type"] not in {"skill", "monster", "quest"}:
            raise ValueError(f"Unsupported job_type in {raw['id']}: {raw['job_type']}")
        batch_count = int(raw.get("batch_count", 1))
        if not 1 <= batch_count <= 20:
            raise ValueError(f"batch_count must be 1-20 in {raw['id']}")
        return cls(
            id=str(raw["id"]),
            job_type=str(raw["job_type"]),
            requirement=str(raw["requirement"]),
            expected=dict(raw["expected"]),
            description=str(raw.get("description", "")),
            batch_count=batch_count,
            enable_critic=bool(raw.get("enable_critic", False)),
            repeat=max(1, int(raw.get("repeat", 1))),
            modes=tuple(raw.get("modes", ["mock", "live"])),
            tags=tuple(raw.get("tags", [])),
        )


@dataclass(frozen=True)
class AuditFinding:
    code: str
    message: str
    path: str = ""
    severity: str = "error"


@dataclass
class AuditReport:
    case_id: str
    provider_mode: str
    run_index: int
    findings: list[AuditFinding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(item.severity == "error" for item in self.findings)

    def add(self, code: str, message: str, path: str = "", severity: str = "error"):
        self.findings.append(AuditFinding(code, message, path, severity))

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "provider_mode": self.provider_mode,
            "run_index": self.run_index,
            "passed": self.passed,
            "findings": [asdict(item) for item in self.findings],
            "metrics": self.metrics,
            "artifacts": self.artifacts,
        }


def load_cases(path: str | Path) -> list[AcceptanceCase]:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    raw_cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(raw_cases, list):
        raise ValueError(f"Acceptance case file must contain a list: {source}")
    cases = [AcceptanceCase.from_dict(item) for item in raw_cases]
    ids = [item.id for item in cases]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"Duplicate acceptance case IDs: {duplicates}")
    return cases
