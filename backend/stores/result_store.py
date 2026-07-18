"""Result store: persists generated config bundles as JSON."""
import json
from pathlib import Path
from typing import Optional
from ..schemas.bundle import SkillBundle, MonsterBundle, QuestBundle


class ResultStore:
    def __init__(self, output_dir: str = "output"):
        self._dir = Path(output_dir)
        self._json_dir = self._dir / "json"
        self._json_dir.mkdir(parents=True, exist_ok=True)

    def save_json(self, job_id: str, bundle) -> Path:
        if isinstance(bundle, SkillBundle):
            prefix = "skill"
        elif isinstance(bundle, MonsterBundle):
            prefix = "monster"
        elif isinstance(bundle, QuestBundle):
            prefix = "quest"
        else:
            raise ValueError(f"Unknown bundle type: {type(bundle)}")
        filename = f"{prefix}_{job_id}.json"
        path = self._json_dir / filename
        path.write_text(
            bundle.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )
        return path
