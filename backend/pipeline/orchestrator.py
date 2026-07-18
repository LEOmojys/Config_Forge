"""Orchestrator: generation -> validation -> critic -> revision loop."""
from typing import Optional
from ..schemas.bundle import SkillBundle, MonsterBundle, QuestBundle
from ..validators.rule_engine import ValidationResult

MAX_ROUNDS = 3


class Orchestrator:
    """主编排器：生成 → 校验 → 审查 → 修订循环（硬上限 3 轮）"""

    def __init__(self, generator, critic, seed_store,
                 rule_engine, trace_store, result_store, event_bus=None):
        self.generator = generator
        self.critic = critic
        self.seed = seed_store
        self.rules = rule_engine
        self.traces = trace_store
        self.results = result_store
        self.events = event_bus

    def generate_skill(self, requirement: str, enable_critic: bool = True,
                       skip_validation: bool = False, dry_run: bool = False,
                       job_id: str = None, trace_id: str = None) -> dict:
        return self._run("skill", requirement, enable_critic, skip_validation, dry_run, job_id, trace_id)

    def generate_monster(self, requirement: str, enable_critic: bool = True,
                         skip_validation: bool = False, dry_run: bool = False,
                         job_id: str = None, trace_id: str = None) -> dict:
        return self._run("monster", requirement, enable_critic, skip_validation, dry_run, job_id, trace_id)

    def generate_quest(self, requirement: str, enable_critic: bool = True,
                       skip_validation: bool = False, dry_run: bool = False,
                       job_id: str = None, trace_id: str = None) -> dict:
        return self._run("quest", requirement, enable_critic, skip_validation, dry_run, job_id, trace_id)

    def _run(self, job_type: str, requirement: str, enable_critic: bool,
             skip_validation: bool = False, dry_run: bool = False,
             job_id: str = None, trace_id: str = None) -> dict:
        self.seed.load()
        if dry_run:
            trace_id, job_id = None, None
        else:
            if trace_id is None:
                trace_id = self.traces.create(job_type, requirement)
            if job_id is None:
                job_id = trace_id.replace("trace_", "j_") if trace_id else None
                job_id = trace_id.replace("trace_", "j_")
        feedback: Optional[str] = None
        final_bundle = None
        bundle = None  # initialized for linter

        def _emit(etype: str, data: dict):
            if self.events and job_id:
                self.events.push(job_id, etype, data)

        _emit("start", {"job_type": job_type, "requirement": requirement, "job_id": job_id})

        for round_no in range(1, MAX_ROUNDS + 1):
            _emit("round_start", {"round": round_no})

            # 1) Generate via GeneratorAgent
            _emit("generating", {"round": round_no, "message": f"Round {round_no}: LLM generating..."})
            if job_type == "skill":
                bundle = self.generator.generate_skill(requirement, feedback or "")
                validate_fn = self.rules.validate_skill_bundle
            elif job_type == "monster":
                bundle = self.generator.generate_monster(requirement, feedback or "")
                validate_fn = self.rules.validate_monster_bundle
            else:
                bundle = self.generator.generate_quest(requirement, feedback or "")
                validate_fn = self.rules.validate_quest_bundle

            _emit("generated", {"round": round_no, "bundle_summary": str(type(bundle).__name__)})

            # Register bundle-internal skills/templates
            if hasattr(self.seed, 'register_bundle'):
                self.seed.register_bundle(bundle)

            # 2) L2 规则引擎校验
            if skip_validation:
                vr = ValidationResult()
            else:
                _emit("validating", {"round": round_no, "message": "Running RuleEngine..."})
                vr: ValidationResult = validate_fn(bundle)

            for v in vr.violations:
                _emit("violation", {
                    "round": round_no,
                    "rule_id": v.rule_id, "severity": v.severity,
                    "table": v.table, "field": v.field, "message": v.message,
                })

            # 3) L3 Critic 审查
            critic_result = None
            if not vr.errors and enable_critic and self.critic is not None:
                _emit("reviewing", {"round": round_no, "message": "Critic reviewing..."})
                critic_result = self.critic.review(bundle.model_dump(mode="json", exclude_none=True))
                _emit("reviewed", {
                    "round": round_no,
                    "approved": critic_result.get("approved", True),
                    "issues": critic_result.get("issues", []),
                })

            # 4) Trace
            round_data = {
                "bundle": bundle.model_dump(mode="json", exclude_none=True),
                "violations": [
                    {"rule_id": v.rule_id, "severity": v.severity,
                     "table": v.table, "field": v.field, "message": v.message}
                    for v in vr.violations
                ],
                "critic": critic_result,
                "passed": vr.passed and (critic_result is None or critic_result.get("approved", True)),
            }
            if not dry_run:
                self.traces.add_round(trace_id, round_no, round_data)

            _emit("round_end", {
                "round": round_no,
                "passed": round_data["passed"],
                "violations_count": len(vr.violations),
                "errors_count": len(vr.errors),
            })

            if round_data["passed"]:
                final_bundle = bundle
                break

            feedback = self._build_feedback(vr, critic_result)

        # 循环结束
        if final_bundle is None:
            final_bundle = bundle
            final_status = "need_human"
        else:
            final_status = "passed"

        if dry_run:
            return {
                "status": final_status, "rounds": round_no,
                "bundle": final_bundle.model_dump(mode="json", exclude_none=True) if final_bundle else None,
                "type": job_type,
            }

        self.results.save_json(job_id, final_bundle)
        self.traces.complete(trace_id, final_status, {"job_id": job_id, "type": job_type})

        result = {
            "job_id": job_id, "trace_id": trace_id,
            "status": final_status, "rounds": round_no,
            "bundle": final_bundle.model_dump(mode="json", exclude_none=True),
            "type": job_type,
        }
        _emit("done", {"status": final_status, "rounds": round_no, "type": job_type})
        if self.events and job_id:
            self.events.mark_done(job_id, result)

        return result

    @staticmethod
    def _build_feedback(vr: ValidationResult, critic_result: Optional[dict]) -> str:
        """Build feedback string: errors only, no warnings."""
        parts = []
        if vr.errors:
            lines = ["[Rule Violations Found - 请逐条修复]"]
            for v in vr.errors:
                lines.append(f"  [ERROR] {v.rule_id} @ {v.table}.{v.field}: {v.message}")
            parts.append("\n".join(lines))
        if critic_result and not critic_result.get("approved", True):
            issues = "\n".join(f"- {i}" for i in critic_result.get("issues", []))
            parts.append(f"[设计审查]\n{issues}")
        return "\n\n".join(parts)
