"""Evaluation module: runs eval sets and produces ablation study results."""
import json
import time
from pathlib import Path
from dataclasses import dataclass, field
from ..pipeline.orchestrator import Orchestrator


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
    def __init__(self, orchestrator: Orchestrator):
        self.orchestrator = orchestrator

    def load_samples(self, path: str = "backend/evaluation/eval_set.json") -> list[EvalSample]:
        p = Path(path)
        if not p.exists():
            return self._default_samples()
        raw = json.loads(p.read_text(encoding="utf-8"))
        return [EvalSample(**item) for item in raw]

    def run_ablation(self, samples: list[EvalSample]) -> dict:
        """Run G0-G3 ablation groups and return results."""
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
        return results

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
