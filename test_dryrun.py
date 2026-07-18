"""Verify eval dry-run mode produces no files."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from backend.stores.seed_store import SeedStore
from backend.stores.trace_store import TraceStore
from backend.stores.result_store import ResultStore
from backend.validators.rule_engine import RuleEngine
from backend.pipeline.mock_provider import MockLLMProvider
from backend.pipeline.orchestrator import Orchestrator
from backend.evaluation.runner import EvalRunner

seed = SeedStore("data/seed")
seed.load()
rules = RuleEngine(seed)
traces = TraceStore("output/traces")
results = ResultStore("output")


class _MockGen:
    def __init__(self, m):
        self.m = m

    def generate_skill(self, r, fb=""):
        return self.m.generate_skill_bundle(r, fb)

    def generate_monster(self, r, fb=""):
        return self.m.generate_monster_bundle(r, fb)

    def generate_quest(self, r, fb=""):
        return self.m.generate_quest_bundle(r, fb)


class _MockCritic:
    def review(self, d):
        return {"approved": True, "issues": []}


orch = Orchestrator(_MockGen(MockLLMProvider(seed)), _MockCritic(), seed, rules, traces, results)
runner = EvalRunner(orch)

before_json = set(os.listdir("output/json"))
before_csv = set(os.listdir("output/csv"))
before_traces = set(os.listdir("output/traces"))

samples = runner.load_samples()[:5]
result = runner.run_ablation(samples)

after_json = set(os.listdir("output/json"))
after_csv = set(os.listdir("output/csv"))
after_traces = set(os.listdir("output/traces"))

new_json = len(after_json - before_json)
new_csv = len(after_csv - before_csv)
new_traces = len(after_traces - before_traces)

print(f"G0 pass_rate: {result['G0_pure_llm']['pass_rate']}")
print(f"G2 pass_rate: {result['G2_rules']['pass_rate']}")
print(f"G3 pass_rate: {result['G3_full']['pass_rate']}")
print(f"G0 avg_rounds: {result['G0_pure_llm']['avg_rounds']}")
print(f"G2 avg_rounds: {result['G2_rules']['avg_rounds']}")
print(f"New JSON: {new_json} (expect 0)")
print(f"New CSV: {new_csv} (expect 0)")
print(f"New traces: {new_traces} (expect 0)")
print(
    "Dry-run mode: OK" if new_json == 0 and new_csv == 0 and new_traces == 0 else "FAIL"
)
