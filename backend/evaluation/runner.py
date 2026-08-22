"""Evaluation module: runs eval sets and produces ablation study results."""
import json
import time
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from ..pipeline.orchestrator import Orchestrator

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
    def __init__(self, orchestrator: Orchestrator, output_dir: str | Path = None):
        self.orchestrator = orchestrator
        self.output_dir = Path(output_dir) if output_dir else DEFAULT_EVAL_OUTPUT_DIR
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

    def run_ablation(self, samples: list[EvalSample], save_report: bool = True) -> dict:
        """Run G0-G3 ablation groups, persist a report, and return results."""
        results = {}
        # G0 cannot be measured by this structured pipeline: providers must pass
        # Pydantic before Orchestrator receives a bundle.
        results["G0_pure_llm"] = self._not_measured(
            samples,
            "Raw LLM output is not available because generation is schema-gated before orchestration.",
        )
        # G1: LLM + Pydantic only (Pydantic built into GeneratorAgent._generate)
        results["G1_pydantic"] = self._run_group(samples, skip_validation=True, enable_critic=False)
        # G2: LLM + Pydantic + RuleEngine (no Critic)
        results["G2_rules"] = self._run_group(samples, skip_validation=False, enable_critic=False)
        # G3: Full pipeline (RuleEngine + Critic)
        results["G3_full"] = self._run_group(samples, skip_validation=False, enable_critic=True)
        if save_report:
            self.save_report(results, len(samples))
        return results

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
            "| 组 | 说明 | 通过/总数 | 通过率 | 平均轮数 |",
            "|---|---|---|---|---|",
        ]
        for key, (title, desc) in labels.items():
            g = groups.get(key) or {}
            if g.get("disabled"):
                lines.append(f"| {title} | {desc} | N/A | N/A | N/A |")
            else:
                lines.append(
                    f"| {title} | {desc} | {g['passed']}/{g['total']} "
                    f"| {g['pass_rate'] * 100:.1f}% | {g['avg_rounds']} |"
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

    def _run_group(self, samples: list[EvalSample], skip_validation: bool, enable_critic: bool) -> dict:
        group_results = []
        passed = 0
        total_rounds = 0
        for sample in samples:
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
                group_results.append({"id": sample.id, "passed": ok, "rounds": res["rounds"], "type": sample.type})
            except Exception as e:
                group_results.append({"id": sample.id, "passed": False, "rounds": 0, "type": sample.type, "error": str(e)})
        return {
            "passed": passed,
            "total": len(samples),
            "pass_rate": round(passed / len(samples), 3) if samples else 0,
            "avg_rounds": round(total_rounds / len(samples), 2) if samples else 0,
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
