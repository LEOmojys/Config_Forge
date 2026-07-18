"""Verify real provider + agent imports work."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

from backend.providers import LLMProvider, DoubaoProvider, DeepSeekProvider
from backend.agents import GeneratorAgent, CriticAgent, ReviewResult
from backend.prompts import GENERATOR_SYSTEM_PROMPT, CRITIC_SYSTEM_PROMPT

print("All providers + agents + prompts imported OK")
print(f"ReviewResult fields: {list(ReviewResult.model_json_schema()['properties'].keys())}")
print(f"Generator prompt length: {len(GENERATOR_SYSTEM_PROMPT)} chars")
print(f"Critic prompt length: {len(CRITIC_SYSTEM_PROMPT)} chars")
print("\n=== PROVIDER ARCHITECTURE VERIFIED ===")
