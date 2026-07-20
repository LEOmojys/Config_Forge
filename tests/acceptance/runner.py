"""Isolated Mock/Live execution for acceptance cases."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import os
import time

from backend.agents.critic import CriticAgent
from backend.agents.generator import GeneratorAgent
from backend.pipeline.exporter import CsvExporter
from backend.pipeline.mock_provider import MockLLMProvider
from backend.pipeline.orchestrator import Orchestrator
from backend.schemas.bundle import MonsterBundle, QuestBundle, SkillBundle
from backend.stores.result_store import ResultStore
from backend.stores.seed_store import SeedStore
from backend.stores.trace_store import TraceStore
from backend.validators.rule_engine import RuleEngine
from .auditor import OutputAuditor
from .models import AcceptanceCase, AuditReport


def load_project_env(project_root: str | Path) -> Path:
    """Load non-empty .env values without overriding the caller environment."""
    env_path = Path(project_root).resolve() / ".env"
    if not env_path.exists():
        return env_path
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            os.environ.setdefault(key, value)
    return env_path


class _MockGenerator:
    def __init__(self, provider):
        self.provider = provider

    def generate_skill(self, requirement, feedback=""):
        return self.provider.generate_skill_bundle(requirement, feedback)

    def generate_monster(self, requirement, feedback=""):
        return self.provider.generate_monster_bundle(requirement, feedback)

    def generate_quest(self, requirement, feedback=""):
        return self.provider.generate_quest_bundle(requirement, feedback)


class _MockCritic:
    def __init__(self, provider):
        self.provider = provider

    def review(self, bundle):
        return self.provider.review(bundle, "unknown")


class AcceptanceRunner:
    def __init__(self, project_root: str | Path, output_root: str | Path,
                 provider_mode: str = "mock"):
        self.project_root = Path(project_root).resolve()
        self.output_root = Path(output_root).resolve()
        self.provider_mode = provider_mode
        if provider_mode not in {"mock", "live"}:
            raise ValueError("provider_mode must be 'mock' or 'live'")
        self.env_path = load_project_env(self.project_root)

    def run_case(self, case: AcceptanceCase, run_index: int = 1) -> AuditReport:
        run_root = self.output_root / case.id / f"run_{run_index:02d}"
        if run_root.exists():
            raise FileExistsError(f"Acceptance run directory already exists: {run_root}")
        run_root.mkdir(parents=True)

        report = AuditReport(case.id, self.provider_mode, run_index)
        report.artifacts = {
            "root": str(run_root),
            "json": str(run_root / "json"),
            "csv": str(run_root / "csv"),
            "traces": str(run_root / "traces"),
        }
        seed = SeedStore(str(self.project_root / "data" / "seed"))
        seed.load()
        trace_store = TraceStore(str(run_root / "traces"))
        result_store = ResultStore(str(run_root))
        exporter = CsvExporter(str(run_root / "csv"))
        generator, critic = self._build_agents(seed, case.enable_critic)
        orchestrator = Orchestrator(
            generator,
            critic,
            seed,
            RuleEngine(seed),
            trace_store,
            result_store,
            event_bus=None,
        )

        bundles: list[dict[str, Any]] = []
        statuses: list[str] = []
        parent_trace_id = None
        if case.batch_count > 1:
            parent_trace_id = trace_store.create(case.job_type, case.requirement, metadata={
                "is_batch": True,
                "batch_count": case.batch_count,
                "batch_items": [],
                "acceptance_case_id": case.id,
            })

        started = time.perf_counter()
        for index in range(1, case.batch_count + 1):
            requirement = self._item_requirement(case, index)
            trace_id = trace_store.create(case.job_type, requirement, metadata={
                "parent_trace_id": parent_trace_id,
                "batch_index": index,
                "batch_total": case.batch_count,
                "acceptance_case_id": case.id,
            })
            job_id = trace_id.replace("trace_", "j_")
            try:
                result = self._generate(
                    orchestrator, case.job_type, requirement,
                    case.enable_critic, job_id, trace_id,
                )
                bundle = result["bundle"]
                self._export(exporter, case.job_type, bundle)
                bundles.append(bundle)
                statuses.append(result["status"])
                identity = self._identity(case.job_type, bundle)
                if parent_trace_id:
                    trace_store.add_batch_item(parent_trace_id, {
                        "index": index,
                        "job_id": job_id,
                        "trace_id": trace_id,
                        "status": result["status"],
                        **identity,
                    })
            except Exception as exc:
                statuses.append("failed")
                trace_store.complete(trace_id, "failed", error=str(exc))
                report.add("GENERATION_ERROR", str(exc), f"items[{index - 1}]")
                if parent_trace_id:
                    trace_store.add_batch_item(parent_trace_id, {
                        "index": index,
                        "job_id": job_id,
                        "trace_id": trace_id,
                        "status": "failed",
                        "error": str(exc),
                    })

        duration = time.perf_counter() - started
        if parent_trace_id:
            succeeded = sum(status == "passed" for status in statuses)
            parent_status = "passed" if succeeded == case.batch_count else "partial" if succeeded else "failed"
            trace_store.complete(parent_trace_id, parent_status, {
                "type": case.job_type,
                "batch_count": case.batch_count,
                "succeeded": succeeded,
                "failed": case.batch_count - succeeded,
            })

        report.metrics.update({
            "duration_seconds": round(duration, 4),
            "average_item_seconds": round(duration / case.batch_count, 4),
        })
        return OutputAuditor(seed).audit(case, bundles, statuses, run_root, report)

    def _build_agents(self, seed: SeedStore, enable_critic: bool):
        if self.provider_mode == "mock":
            provider = MockLLMProvider(seed)
            return _MockGenerator(provider), _MockCritic(provider) if enable_critic else None

        from backend.providers import DeepSeekProvider, DoubaoProvider

        if not (
            os.environ.get("ARK_CODING_API_KEY")
            or os.environ.get("DOUBAO_API_KEY")
            or os.environ.get("ARK_API_KEY")
        ):
            raise RuntimeError(
                "Doubao API key is missing. Checked process environment and "
                f"{self.env_path}. Set ARK_CODING_API_KEY, DOUBAO_API_KEY, or ARK_API_KEY."
            )
        generator = GeneratorAgent(DoubaoProvider(), seed)
        critic = None
        if enable_critic:
            if not os.environ.get("DEEPSEEK_API_KEY"):
                raise RuntimeError("DEEPSEEK_API_KEY is required for live critic acceptance cases")
            critic = CriticAgent(DeepSeekProvider())
        return generator, critic

    @staticmethod
    def _generate(orchestrator: Orchestrator, job_type: str, requirement: str,
                  enable_critic: bool, job_id: str, trace_id: str) -> dict:
        kwargs = {
            "job_id": job_id,
            "trace_id": trace_id,
            "emit_events": False,
        }
        if job_type == "skill":
            return orchestrator.generate_skill(requirement, enable_critic, **kwargs)
        if job_type == "monster":
            return orchestrator.generate_monster(requirement, enable_critic, **kwargs)
        return orchestrator.generate_quest(requirement, enable_critic, **kwargs)

    @staticmethod
    def _export(exporter: CsvExporter, job_type: str, bundle: dict):
        if job_type == "skill":
            exporter.export_skill(SkillBundle.model_validate(bundle))
        elif job_type == "monster":
            exporter.export_monster(MonsterBundle.model_validate(bundle))
        else:
            exporter.export_quest(QuestBundle.model_validate(bundle))

    @staticmethod
    def _item_requirement(case: AcceptanceCase, index: int) -> str:
        if case.batch_count == 1:
            return case.requirement
        return (
            f"{case.requirement}\n"
            f"Acceptance batch item {index}/{case.batch_count}: generate exactly one {case.job_type}. "
            f"Use unique marker acceptance_{case.id}_{index:02d} in new primary IDs. "
            "Names, IDs, values, skills/objectives and drops must differ from other items."
        )

    @staticmethod
    def _identity(job_type: str, bundle: dict) -> dict[str, Any]:
        if job_type == "monster":
            item = bundle.get("monster_config") or {}
            return {"id": item.get("monster_id"), "name": item.get("name")}
        if job_type == "quest":
            item = bundle.get("quest_template") or {}
            return {"id": item.get("quest_id"), "name": item.get("name")}
        items = bundle.get("skills") or [{}]
        return {"id": items[0].get("skill_id"), "name": items[0].get("name")}


def timestamped_output_root(project_root: str | Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(project_root) / "output" / "acceptance" / stamp
