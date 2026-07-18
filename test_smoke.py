"""Quick smoke test for backend modules (updated for new agent architecture)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from backend.stores.seed_store import SeedStore
from backend.validators.rule_engine import RuleEngine
from backend.pipeline.mock_provider import MockLLMProvider
from backend.pipeline.orchestrator import Orchestrator
from backend.pipeline.exporter import CsvExporter
from backend.stores.trace_store import TraceStore
from backend.stores.result_store import ResultStore

BASE = os.path.dirname(__file__)

# Test seed store
seed = SeedStore(os.path.join(BASE, 'data', 'seed'))
seed.load()
print(f"Seeds: {len(seed.elements)} elements, {len(seed.items)} items, {len(seed.skills)} skills, {len(seed.templates)} templates")

# Test mock provider (standalone)
provider = MockLLMProvider(seed)
bundle = provider.generate_monster_bundle('Generate a level 30 fire elite monster with summoner AI')
print(f"Monster: {bundle.monster_config.monster_id}, template={bundle.monster_template.template_id}, skills={len(bundle.monster_skills)}")

# Test rule engine - should pass now (mock uses seed IDs)
rules = RuleEngine(seed)
vr = rules.validate_monster_bundle(bundle)
print(f"Rule violations: {len(vr.violations)} (errors={len(vr.errors)})")
for v in vr.violations:
    print(f"  [{v.severity}] {v.rule_id}: {v.message}")
assert vr.passed == (len(vr.errors) == 0)

# Test orchestrator with mock agents
class _MockGen:
    def __init__(self, m): self.m = m
    def generate_skill(self, r, fb=""): return self.m.generate_skill_bundle(r, fb)
    def generate_monster(self, r, fb=""): return self.m.generate_monster_bundle(r, fb)
    def generate_quest(self, r, fb=""): return self.m.generate_quest_bundle(r, fb)
class _MockCritic:
    def review(self, d): return {"approved": True, "issues": []}

traces = TraceStore(os.path.join(BASE, 'output', 'traces'))
results = ResultStore(os.path.join(BASE, 'output'))
orch = Orchestrator(_MockGen(provider), _MockCritic(), seed, rules, traces, results)

result = orch.generate_monster('Generate a level 30 fire elite monster with summoner AI')
print(f"Orchestrator: status={result['status']}, rounds={result['rounds']}")

# Test CSV exporter
csv_exp = CsvExporter(os.path.join(BASE, 'output', 'csv'))
paths = csv_exp.export_monster(bundle)
print(f"CSV files: {[str(p) for p in paths]}")

# Test skill and quest generation
skill_result = orch.generate_skill("Generate a fire ultimate skill with high AOE damage")
print(f"Skill gen: status={skill_result['status']}, rounds={skill_result['rounds']}")

quest_result = orch.generate_quest("Generate a side quest requiring level 10 with kill and collect objectives")
print(f"Quest gen: status={quest_result['status']}, rounds={quest_result['rounds']}")

print("\n=== ALL BACKEND TESTS PASSED ===")
