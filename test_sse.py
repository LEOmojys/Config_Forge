"""Test SSE event stream end-to-end."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from backend.stores.seed_store import SeedStore
from backend.stores.trace_store import TraceStore
from backend.stores.result_store import ResultStore
from backend.stores.event_bus import event_bus
from backend.validators.rule_engine import RuleEngine
from backend.pipeline.mock_provider import MockLLMProvider
from backend.pipeline.orchestrator import Orchestrator
import threading

seed = SeedStore("data/seed")
seed.load()
rules = RuleEngine(seed)
traces = TraceStore("output/traces")
results = ResultStore("output")
mock = MockLLMProvider(seed)

class _MockGen:
    def __init__(self, m): self.m = m
    def generate_skill(self, r, fb=""): return self.m.generate_skill_bundle(r, fb)
    def generate_monster(self, r, fb=""): return self.m.generate_monster_bundle(r, fb)
    def generate_quest(self, r, fb=""): return self.m.generate_quest_bundle(r, fb)

class _MockCritic:
    def review(self, d): return {"approved": True, "issues": []}

orch = Orchestrator(_MockGen(mock), _MockCritic(), seed, rules, traces, results, event_bus=event_bus)

# Run generation in background thread
def run_gen():
    orch.generate_skill("Generate a fire ultimate AOE skill")

t = threading.Thread(target=run_gen)
t.start()

# Collect events
events = []
seen = 0
start = time.time()
while time.time() - start < 10:
    new, done = event_bus.get_new_events("j_placeholder", seen)
    # The orchestrator will auto-generate the job_id from trace_id
    # Let's check all keys in the event bus
    with event_bus._lock:
        all_keys = list(event_bus._events.keys())

    for key in all_keys:
        new_evts, is_done = event_bus.get_new_events(key, 0)
        if new_evts:
            for e in new_evts:
                print(f"  [{key[:12]}...] {e['type']}: {json.dumps(e['data'], ensure_ascii=False)[:80]}")
            if is_done:
                print("\nSSE stream test: PASSED")
                sys.exit(0)
    time.sleep(0.5)

t.join(timeout=10)
print("\nSSE stream test: DONE")
