import json

from pydantic import BaseModel

from ..stores.momo_seed_store import MomoSeedStore


MOMO_SYSTEM_PROMPT = """You create standalone MoMo game-design content packs.
Return only schema-valid JSON. Use only IDs, regions, room IDs, archetypes, tuning profiles, and assets present in the supplied MoMo seed snapshot. Do not emit Lua, source code, file paths, or runtime integration instructions. Design attacks that are readable in a top-down action roguelike. A boss must have exactly direct, projectile-or-area, and summon attack categories."""


def build_momo_prompt(requirement: str, job_type: str, schema: type[BaseModel], seed_store: MomoSeedStore, feedback: str = "") -> tuple[str, str]:
    seed_store.load()
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
    parts = [
        f"Requirement:\n{requirement}",
        f"Content type: {job_type}",
        f"MoMo seed snapshot:\n{seed_store.to_context()}",
        f"Output JSON Schema:\n{schema_json}",
    ]
    if feedback:
        parts.append(f"Validation feedback to fix:\n{feedback}")
    return MOMO_SYSTEM_PROMPT, "\n\n".join(parts)
