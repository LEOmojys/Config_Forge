"""Evaluation module: runs eval sets and produces ablation study results."""
import json
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from ..pipeline.orchestrator import Orchestrator
from ..schemas.bundle import SkillBundle, MonsterBundle, QuestBundle

DEFAULT_EVAL_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "eval"


@dataclass
class EvalSample:
    id: int
    type: str  # skill | monster | quest
    requirement: str
    expected: dict = field(default_factory=dict)


@dataclass
class EvalResult:
    sample_id: int
    job_type: str
    passed: bool
    rounds: int
    errors: list[str] = field(default_factory=list)


class EvalRunner:
    def __init__(self, orchestrator: Orchestrator, output_dir: str | Path = None,
                 rule_engine=None):
        self.orchestrator = orchestrator
        self.output_dir = Path(output_dir) if output_dir else DEFAULT_EVAL_OUTPUT_DIR
        # Golden-yardstick auditor: scores every group's final output against
        # the FULL rule contract, independent of which gates the group enabled.
        self.rule_engine = rule_engine if rule_engine is not None else getattr(orchestrator, "rules", None)
        self._samples_source = "unknown"
        self.last_report: dict = {}

    def load_samples(self, path: str = "backend/evaluation/eval_set.json") -> list[EvalSample]:
        p = Path(path)
        if not p.exists():
            self._samples_source = "builtin_default_20"
            return self._default_samples()
        self._samples_source = str(p)
        raw = json.loads(p.read_text(encoding="utf-8"))
        return [EvalSample(**item) for item in raw]

    def run_ablation(self, samples: list[EvalSample], save_report: bool = True,
                     progress_cb=None, checkpoint_path=None) -> dict:
        """Run G0-G3 ablation groups, persist a report, and return results.

        progress_cb(event_type, data) is invoked with:
          - ("eval_start", {"total": N})
          - ("group_start", {"group": key, "group_index": i, "label": ..., "total": N})
          - ("sample_done", {"group": key, "index": i, "total": N, "passed": bool, "rounds": n})
          - ("group_done", {"group": key, "result": {...}})

        checkpoint_path: if given, a JSON checkpoint of completed groups plus
        the current group is written before every group runs. On success the
        checkpoint is removed; if the process dies mid-run, the checkpoint
        survives as the recovery artifact.
        """
        group_labels = {
            "G0_pure_llm": "G0: Pure LLM",
            "G1_pydantic": "G1: + Pydantic",
            "G2_rules": "G2: + RuleEngine",
            "G3_full": "G3: + Critic",
        }
        cp = Path(checkpoint_path) if checkpoint_path else None
        results = {}

        def emit(etype: str, data: dict):
            if progress_cb is not None:
                progress_cb(etype, data)

        def _checkpoint(current_group: Optional[str]):
            if cp is None:
                return
            try:
                cp.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "status": "running",
                    "current_group": current_group,
                    "sample_total": len(samples),
                    "sample_source": self._samples_source,
                    "groups": results,
                }
                cp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass  # checkpointing must never break the run

        def group_emit(group_key: str):
            def _cb(etype: str, data: dict):
                if etype == "sample_done":
                    data = {"group": group_key, **data}
                emit(etype, data)
            return _cb

        emit("eval_start", {"total": len(samples)})

        # G0 cannot be measured by this structured pipeline: providers must pass
        # Pydantic before Orchestrator receives a bundle.
        emit("group_start", {"group": "G0_pure_llm", "group_index": 1,
                             "label": group_labels["G0_pure_llm"], "total": len(samples)})
        results["G0_pure_llm"] = self._not_measured(
            samples,
            "Raw LLM output is not available because generation is schema-gated before orchestration.",
        )
        emit("group_done", {"group": "G0_pure_llm", "result": results["G0_pure_llm"]})
        _checkpoint("G1_pydantic")

        # G1: LLM + Pydantic only (Pydantic built into GeneratorAgent._generate)
        emit("group_start", {"group": "G1_pydantic", "group_index": 2,
                             "label": group_labels["G1_pydantic"], "total": len(samples)})
        results["G1_pydantic"] = self._run_group(samples, skip_validation=True, enable_critic=False, progress_cb=group_emit("G1_pydantic"))
        emit("group_done", {"group": "G1_pydantic", "result": results["G1_pydantic"]})
        _checkpoint("G2_rules")

        # G2: LLM + Pydantic + RuleEngine (no Critic)
        emit("group_start", {"group": "G2_rules", "group_index": 3,
                             "label": group_labels["G2_rules"], "total": len(samples)})
        results["G2_rules"] = self._run_group(samples, skip_validation=False, enable_critic=False, progress_cb=group_emit("G2_rules"))
        emit("group_done", {"group": "G2_rules", "result": results["G2_rules"]})
        _checkpoint("G3_full")

        # G3: Full pipeline (RuleEngine + Critic)
        emit("group_start", {"group": "G3_full", "group_index": 4,
                             "label": group_labels["G3_full"], "total": len(samples)})
        results["G3_full"] = self._run_group(samples, skip_validation=False, enable_critic=True, progress_cb=group_emit("G3_full"))
        emit("group_done", {"group": "G3_full", "result": results["G3_full"]})

        if save_report:
            self.save_report(results, len(samples))
        if cp is not None:
            cp.unlink(missing_ok=True)
        return results

    @staticmethod
    def finalize_checkpoint(checkpoint_path, status: str):
        """Mark a surviving checkpoint with its terminal status (e.g. after
        the process was interrupted mid-run)."""
        cp = Path(checkpoint_path)
        if not cp.exists():
            return
        try:
            payload = json.loads(cp.read_text(encoding="utf-8"))
            payload["status"] = status
            cp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass  # best-effort recovery marker

    def save_report(self, results: dict, sample_total: int = None) -> dict:
        """Persist ablation results as JSON + Markdown under output/eval/.

        Returns {"json": <path>, "markdown": <path>} and stores it on
        self.last_report so callers (e.g. the API endpoint) can surface it.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        self.output_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "sample_total": sample_total if sample_total is not None else self._total_samples(results),
            "sample_source": self._samples_source,
            "generator_provider": self._provider_name(getattr(self.orchestrator, "generator", None)),
            "critic_provider": self._provider_name(getattr(self.orchestrator, "critic", None)),
            "groups": results,
        }

        json_path = self.output_dir / f"ablation_{ts}.json"
        md_path = self.output_dir / f"ablation_{ts}.md"
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        md_path.write_text(self._build_markdown_report(payload), encoding="utf-8")

        self.last_report = {"json": str(json_path), "markdown": str(md_path)}
        return self.last_report

    @staticmethod
    def _provider_name(agent) -> str:
        provider = getattr(agent, "provider", None)
        return type(provider).__name__ if provider is not None else "unknown"

    @staticmethod
    def _total_samples(results: dict) -> int:
        for group in results.values():
            if isinstance(group, dict) and "total" in group:
                return group["total"]
        return 0

    @staticmethod
    def _build_markdown_report(payload: dict) -> str:
        groups = payload["groups"]
        labels = {
            "G0_pure_llm": ("G0: Pure LLM", "基线：纯 LLM 输出（无任何校验层）"),
            "G1_pydantic": ("G1: + Pydantic", "LLM + Pydantic 结构化校验"),
            "G2_rules": ("G2: + RuleEngine", "Pydantic + 10 条规则引擎"),
            "G3_full": ("G3: + Critic", "完整管线：规则 + Critic 评审"),
        }
        lines = [
            "# ConfigForge 消融实验报告",
            "",
            f"- 生成时间: {payload['generated_at']}",
            f"- 样本数: {payload['sample_total']}",
            f"- 样本来源: {payload['sample_source']}",
            f"- 生成端 Provider: {payload['generator_provider']}",
            f"- 评审端 Provider: {payload['critic_provider']}",
            "",
            "## 总览",
            "",
            "| 组 | 说明 | 通过率 | 合同符合率 | 平均轮数 | 平均token/样本 | 修订样本 | 失败(生成/耗尽) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for key, (title, desc) in labels.items():
            g = groups.get(key) or {}
            if g.get("disabled"):
                lines.append(f"| {title} | {desc} | N/A | N/A | N/A | N/A | N/A | N/A |")
            else:
                fb = g.get("failures_by_kind") or {}
                lines.append(
                    f"| {title} | {desc} "
                    f"| {g['pass_rate'] * 100:.1f}% ({g['passed']}/{g['total']}) "
                    f"| **{g.get('contract_pass_rate', 0) * 100:.1f}%** ({g.get('contract_passed', 0)}/{g['total']}) "
                    f"| {g['avg_rounds']} "
                    f"| {g.get('avg_tokens_per_sample', 0)} "
                    f"| {g.get('revised', 0)} ({g.get('revision_rate', 0) * 100:.0f}%) "
                    f"| {fb.get('generation_error', 0)}/{fb.get('need_human', 0)} |"
                )
        lines.append("")
        lines.append(
            "> **通过率** = 该组门禁下的管线状态通过率（及格线随组变化，不跨组可比）。"
        )
        lines.append(
            "> **合同符合率** = 统一裁判：各组最终产物经完整规则引擎离线审计的通过率"
            "（同一把尺子，跨组可比，是消融对比的金标准）。"
        )
        lines.append("")

        for key, (title, _) in labels.items():
            g = groups.get(key) or {}
            lines.append(f"## {title}")
            if g.get("disabled"):
                lines.append("")
                lines.append(f"> 未测量：{g.get('note', '')}")
                lines.append("")
                continue
            lines.append("")
            lines.append("| ID | 类型 | 通过 | 轮数 | 错误 |")
            lines.append("|---|---|---|---|---|")
            for d in g.get("details", []):
                err = (d.get("error") or "").replace("|", "\\|")
                lines.append(
                    f"| {d['id']} | {d['type']} | {'✅' if d['passed'] else '❌'} "
                    f"| {d['rounds']} | {err} |"
                )
            lines.append("")
        return "\n".join(lines)

    def _not_measured(self, samples: list[EvalSample], note: str) -> dict:
        return {
            "passed": 0,
            "total": len(samples),
            "pass_rate": 0,
            "avg_rounds": 0,
            "details": [],
            "disabled": True,
            "note": note,
        }

    def _audit(self, job_type: str, bundle_dict: Optional[dict]):
        """Golden-yardstick audit: score the final bundle against the FULL rule
        contract, regardless of which gates this group enabled. Returns None
        when the audit cannot run (no rules engine, no bundle, or rebuild
        failure) — the audit must never break the eval."""
        if self.rule_engine is None or not bundle_dict:
            return None
        try:
            if job_type == "skill":
                bundle = SkillBundle.model_validate(bundle_dict)
                return self.rule_engine.validate_skill_bundle(bundle)
            if job_type == "monster":
                bundle = MonsterBundle.model_validate(bundle_dict)
                return self.rule_engine.validate_monster_bundle(bundle)
            if job_type == "quest":
                bundle = QuestBundle.model_validate(bundle_dict)
                return self.rule_engine.validate_quest_bundle(bundle)
        except Exception:
            pass
        return None

    def _run_group(self, samples: list[EvalSample], skip_validation: bool, enable_critic: bool,
                   progress_cb=None) -> dict:
        group_results = []
        passed = 0
        contract_passed = 0
        total_rounds = 0
        total_tokens = 0
        revised = 0  # samples that needed >1 round (revision loop actually engaged)
        failures_by_kind: dict[str, int] = {"generation_error": 0, "need_human": 0}
        for index, sample in enumerate(samples, start=1):
            try:
                res = self.orchestrator._run(
                    sample.type, sample.requirement,
                    enable_critic=enable_critic,
                    skip_validation=skip_validation,
                    dry_run=True,  # eval mode: no file writes
                )
                ok = res["status"] == "passed"
                if ok:
                    passed += 1
                total_rounds += res["rounds"]
                entry = {
                    "id": sample.id, "passed": ok, "rounds": res["rounds"], "type": sample.type,
                    "error_kind": None if ok else ("need_human" if res["status"] == "need_human" else "unknown"),
                }
                if res["rounds"] > 1:
                    revised += 1

                # Golden-yardstick audit: same full contract for every group.
                audit = self._audit(sample.type, res.get("bundle"))
                if audit is None:
                    entry["audit_passed"] = False
                    entry["audit_errors"] = None
                    entry["audit_error_rule_ids"] = []
                else:
                    entry["audit_passed"] = audit.passed
                    entry["audit_errors"] = len(audit.errors)
                    entry["audit_error_rule_ids"] = [v.rule_id for v in audit.errors]
                    if audit.passed:
                        contract_passed += 1

                # Aggregate token usage across all rounds (generation + critic).
                tokens = {"prompt": 0, "completion": 0, "total": 0}
                for log in res.get("round_logs") or []:
                    for side in ("generation", "critic"):
                        u = (log.get("tokens") or {}).get(side) or {}
                        tokens["prompt"] += u.get("prompt_tokens", 0) or 0
                        tokens["completion"] += u.get("completion_tokens", 0) or 0
                        tokens["total"] += u.get("total_tokens", 0) or 0
                entry["tokens"] = tokens
                total_tokens += tokens["total"]

                if not ok and res["status"] == "need_human":
                    failures_by_kind["need_human"] += 1
                    entry["error"] = f"need_human after {res['rounds']} revision rounds"
                    logs = res.get("round_logs") or []
                    if logs:
                        entry["last_violations"] = logs[-1].get("violations", [])
                        entry["last_critic"] = logs[-1].get("critic")
                group_results.append(entry)
            except Exception as e:
                failures_by_kind["generation_error"] += 1
                group_results.append({
                    "id": sample.id, "passed": False, "rounds": 0, "type": sample.type,
                    "error_kind": "generation_error",
                    "error": str(e),
                    "tokens": {"prompt": 0, "completion": 0, "total": 0},
                    # No output produced: not contract-compliant by definition.
                    "audit_passed": False,
                    "audit_errors": None,
                    "audit_error_rule_ids": [],
                })
            if progress_cb is not None:
                done = group_results[-1]
                progress_cb("sample_done", {
                    "index": index,
                    "total": len(samples),
                    "passed": done.get("passed", False),
                    "rounds": done.get("rounds", 0),
                    "error": done.get("error"),
                })
        return {
            "passed": passed,
            "total": len(samples),
            "pass_rate": round(passed / len(samples), 3) if samples else 0,
            # Golden yardstick: same full-contract criterion for all groups.
            "contract_passed": contract_passed,
            "contract_pass_rate": round(contract_passed / len(samples), 3) if samples else 0,
            "avg_rounds": round(total_rounds / len(samples), 2) if samples else 0,
            "avg_tokens_per_sample": round(total_tokens / len(samples), 1) if samples else 0,
            "revised": revised,
            "revision_rate": round(revised / len(samples), 3) if samples else 0,
            "failures_by_kind": failures_by_kind,
            "details": group_results,
        }

    def _default_samples(self) -> list[EvalSample]:
        """Built-in 20-sample eval set."""
        return [
            EvalSample(id=1, type="skill", requirement="Generate a fire-type normal attack skill with medium damage and short cooldown."),
            EvalSample(id=2, type="skill", requirement="Generate an ice-type ultimate skill with high AOE damage and long cooldown."),
            EvalSample(id=3, type="skill", requirement="Generate a thunder-type passive skill that boosts attack."),
            EvalSample(id=4, type="skill", requirement="Generate a water-type healing ultimate skill for team support."),
            EvalSample(id=5, type="skill", requirement="Generate a physical monster skill with high stagger damage."),
            EvalSample(id=6, type="skill", requirement="Generate a wind-type normal skill with moderate range and low energy cost."),
            EvalSample(id=7, type="monster", requirement="Generate a level 30 fire-element elite monster with high HP and melee AI."),
            EvalSample(id=8, type="monster", requirement="Generate a level 50 ice-element boss monster with boss_phase AI and at least 3 skills."),
            EvalSample(id=9, type="monster", requirement="Generate a level 15 thunder-element normal monster with ranged AI."),
            EvalSample(id=10, type="monster", requirement="Generate a level 40 physical-element summoner elite monster that summons minions."),
            EvalSample(id=11, type="monster", requirement="Generate a level 25 wind-element elite monster with support AI and healing abilities."),
            EvalSample(id=12, type="monster", requirement="Generate a level 60 quantum-element boss monster with high defense and 2+ skills."),
            EvalSample(id=13, type="monster", requirement="Generate a level 10 water-element normal monster with basic melee attacks."),
            EvalSample(id=14, type="monster", requirement="Generate a level 70 imaginary-element boss monster with massive HP and multiple phases."),
            EvalSample(id=15, type="quest", requirement="Generate a main quest requiring level 10, with kill and collect objectives."),
            EvalSample(id=16, type="quest", requirement="Generate a side quest requiring level 5, with talk and explore objectives."),
            EvalSample(id=17, type="quest", requirement="Generate a daily quest requiring level 20, with one kill objective."),
            EvalSample(id=18, type="quest", requirement="Generate a challenge quest requiring level 50, with kill a boss and collect rare items."),
            EvalSample(id=19, type="quest", requirement="Generate a main quest requiring level 30, with talk, explore, and kill objectives."),
            EvalSample(id=20, type="quest", requirement="Generate a side quest requiring level 15, with collect items and explore objectives."),
        ]
