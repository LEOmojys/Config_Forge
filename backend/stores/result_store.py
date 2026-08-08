"""Result store: persists generated config bundles as JSON with readable filenames."""
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
from ..schemas.bundle import SkillBundle, MonsterBundle, QuestBundle


def _sanitize_name(name: str, max_len: int = 24) -> str:
    """将配置名转为安全文件名片段：中文保留，特殊字符替换为下划线。"""
    sanitized = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized[:max_len] if len(sanitized) > max_len else sanitized


def _extract_config_name(bundle) -> str:
    """从 Bundle 中提取配置名称。"""
    if isinstance(bundle, SkillBundle) and bundle.skills:
        return bundle.skills[0].name
    elif isinstance(bundle, MonsterBundle):
        return bundle.monster_config.name
    elif isinstance(bundle, QuestBundle):
        return bundle.quest_template.name
    return "unknown"


class ResultStore:
    def __init__(self, output_dir: str = "output"):
        self._dir = Path(output_dir)
        self._json_dir = self._dir / "json"
        self._json_dir.mkdir(parents=True, exist_ok=True)

    def save_json(self, bundle, job_id: str = None) -> Path:
        """保存 Bundle 为 JSON，文件名包含类型 + 配置名 + 时间戳，人类可读。"""
        if isinstance(bundle, SkillBundle):
            prefix = "skill"
        elif isinstance(bundle, MonsterBundle):
            prefix = "monster"
        elif isinstance(bundle, QuestBundle):
            prefix = "quest"
        else:
            raise ValueError(f"Unknown bundle type: {type(bundle)}")

        config_name = _sanitize_name(_extract_config_name(bundle))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        if job_id:
            # job_id 形如 j_a1b2c3d4e5f6，取后6位保证唯一性
            short_id = job_id.replace("j_", "")[-6:]
            filename = f"{prefix}__{config_name}__{ts}_{short_id}.json"
        else:
            filename = f"{prefix}__{config_name}__{ts}.json"

        path = self._json_dir / filename
        path.write_text(
            bundle.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )
        return path
