"""Verify real provider + agent imports work."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from backend.providers import LLMProvider
from backend.agents import GeneratorAgent, CriticAgent, ReviewResult
from backend.prompts import GENERATOR_SYSTEM_PROMPT, CRITIC_SYSTEM_PROMPT

print("Base provider + agents + prompts imported OK")
print(f"ReviewResult fields: {list(ReviewResult.model_json_schema()['properties'].keys())}")
print(f"Generator prompt length: {len(GENERATOR_SYSTEM_PROMPT)} chars")
print(f"Critic prompt length: {len(CRITIC_SYSTEM_PROMPT)} chars")

for provider_name in ("DoubaoProvider", "DeepSeekProvider"):
    try:
        provider = getattr(__import__("backend.providers", fromlist=[provider_name]), provider_name)
        print(f"{provider_name} import OK: {provider.__name__}")
    except ModuleNotFoundError as exc:
        print(f"{provider_name} skipped: missing optional dependency {exc.name}")

print("\n=== PROVIDER ARCHITECTURE VERIFIED ===")
