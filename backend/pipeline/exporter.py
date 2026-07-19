"""CSV Exporter: deterministically splits bundles into flat CSV tables."""
import csv
from pathlib import Path
from ..schemas.bundle import MonsterBundle, QuestBundle, SkillBundle


class CsvExporter:
    def __init__(self, output_dir: str = "output/csv"):
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def export_skill(self, bundle: SkillBundle) -> list[Path]:
        path = self._dir / "skills.csv"
        self._append_csv(path, ["skill_id","name","skill_type","element_id","cooldown","damage_multiplier","stance_damage","range","is_aoe","energy_cost","description"], [
            [s.skill_id, s.name, s.skill_type.value, s.element_id.value, s.cooldown, s.damage_multiplier, s.stance_damage, s.range, s.is_aoe, s.energy_cost, s.description]
            for s in bundle.skills
        ])
        return [path]

    def export_monster(self, bundle: MonsterBundle) -> list[Path]:
        paths = []
        # skills.csv (bundle-internal skill definitions)
        if bundle.skills:
            paths.append(self._append_csv(self._dir / "skills.csv",
                ["skill_id","name","skill_type","element_id","cooldown","damage_multiplier","stance_damage","range","is_aoe","energy_cost","description"],
                [[s.skill_id, s.name, s.skill_type.value, s.element_id.value, s.cooldown, s.damage_multiplier, s.stance_damage, s.range, s.is_aoe, s.energy_cost, s.description]
                 for s in bundle.skills]))
        # monster_templates.csv
        t = bundle.monster_template
        paths.append(self._append_csv(self._dir / "monster_templates.csv",
            ["template_id","name","monster_type","base_hp","base_attack","base_defense","base_speed","base_stance","default_ai"],
            [[t.template_id, t.name, t.monster_type.value, t.base_hp, t.base_attack, t.base_defense, t.base_speed, t.base_stance, t.default_ai.value]]))
        # monster_configs.csv
        c = bundle.monster_config
        paths.append(self._append_csv(self._dir / "monster_configs.csv",
            ["monster_id","name","template_id","level","element_id","hp_modify_ratio","attack_modify_ratio","defense_modify_ratio","stance_modify_ratio","loot_group_id","summon_group_id","description"],
            [[c.monster_id, c.name, c.template_id, c.level, c.element_id.value, c.hp_modify_ratio, c.attack_modify_ratio, c.defense_modify_ratio, c.stance_modify_ratio, c.loot_group_id, c.summon_group_id or "", c.description]]))
        # monster_skills.csv
        if bundle.monster_skills:
            paths.append(self._append_csv(self._dir / "monster_skills.csv",
                ["monster_id","slot","skill_id","trigger_key","weight"],
                [[s.monster_id, s.slot, s.skill_id, s.trigger_key, s.weight] for s in bundle.monster_skills]))
        # monster_loot.csv
        if bundle.monster_loot:
            paths.append(self._append_csv(self._dir / "monster_loot.csv",
                ["loot_group_id","item_id","chance","min_count","max_count"],
                [[l.loot_group_id, l.item_id, l.chance, l.min_count, l.max_count] for l in bundle.monster_loot]))
        # summon sub-tables
        if bundle.summon_template:
            st = bundle.summon_template
            paths.append(self._append_csv(self._dir / "monster_templates.csv",
                ["template_id","name","monster_type","base_hp","base_attack","base_defense","base_speed","base_stance","default_ai"],
                [[st.template_id, st.name, st.monster_type.value, st.base_hp, st.base_attack, st.base_defense, st.base_speed, st.base_stance, st.default_ai.value]]))
        if bundle.summon_config:
            sc = bundle.summon_config
            paths.append(self._append_csv(self._dir / "monster_configs.csv",
                ["monster_id","name","template_id","level","element_id","hp_modify_ratio","attack_modify_ratio","defense_modify_ratio","stance_modify_ratio","loot_group_id","summon_group_id","description"],
                [[sc.monster_id, sc.name, sc.template_id, sc.level, sc.element_id.value, sc.hp_modify_ratio, sc.attack_modify_ratio, sc.defense_modify_ratio, sc.stance_modify_ratio, sc.loot_group_id, sc.summon_group_id or "", sc.description]]))
        if bundle.summon_skills:
            paths.append(self._append_csv(self._dir / "monster_skills.csv",
                ["monster_id","slot","skill_id","trigger_key","weight"],
                [[s.monster_id, s.slot, s.skill_id, s.trigger_key, s.weight] for s in bundle.summon_skills]))
        return paths

    def export_quest(self, bundle: QuestBundle) -> list[Path]:
        paths = []
        q = bundle.quest_template
        paths.append(self._append_csv(self._dir / "quest_templates.csv",
            ["quest_id","name","quest_type","required_level","pre_quest_id","reward_group_id","description"],
            [[q.quest_id, q.name, q.quest_type.value, q.required_level, q.pre_quest_id or "", q.reward_group_id, q.description]]))
        if bundle.quest_objectives:
            paths.append(self._append_csv(self._dir / "quest_objectives.csv",
                ["objective_id","quest_id","objective_type","target_id","target_count","description"],
                [[o.objective_id, o.quest_id, o.objective_type.value, o.target_id, o.target_count, o.description] for o in bundle.quest_objectives]))
        return paths

    def _append_csv(self, path: Path, headers: list[str], rows: list[list]) -> Path:
        file_exists = path.exists()
        if file_exists:
            # Verify header consistency
            with open(path, "r", encoding="utf-8-sig") as f:
                existing = next(csv.reader(f), [])
                if existing != headers:
                    raise ValueError(
                        f"CSV header mismatch for {path.name}: "
                        f"expected {headers}, got {existing}"
                    )
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(headers)
            for row in rows:
                writer.writerow(row)
        return path

    def read_table(self, table_name: str) -> dict:
        """Read a CSV table and return headers + rows for API."""
        path = self._table_path(table_name)
        if not path.exists():
            return {"table_name": table_name, "headers": [], "rows": [], "error": "Table not found"}
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            headers = next(reader, [])
            rows = [row for row in reader]
        return {"table_name": table_name, "headers": headers, "rows": rows}

    def list_tables(self) -> list[str]:
        """List available table names."""
        return sorted([p.stem for p in self._dir.glob("*.csv")])

    def add_row(self, table_name: str, row: dict) -> dict:
        table = self.read_table(table_name)
        if table.get("error"):
            raise FileNotFoundError(table["error"])
        headers = table["headers"]
        rows = table["rows"]
        rows.append(self._dict_to_row(headers, row))
        self._write_table(table_name, headers, rows)
        return self.read_table(table_name)

    def update_row(self, table_name: str, row_index: int, row: dict) -> tuple[dict, dict]:
        table = self.read_table(table_name)
        if table.get("error"):
            raise FileNotFoundError(table["error"])
        headers = table["headers"]
        rows = table["rows"]
        if row_index < 0 or row_index >= len(rows):
            raise IndexError("Row index out of range")
        previous = self._row_to_dict(headers, rows[row_index])
        rows[row_index] = self._dict_to_row(headers, row)
        self._write_table(table_name, headers, rows)
        return previous, self.read_table(table_name)

    def delete_row(self, table_name: str, row_index: int) -> tuple[dict, dict]:
        table = self.read_table(table_name)
        if table.get("error"):
            raise FileNotFoundError(table["error"])
        headers = table["headers"]
        rows = table["rows"]
        if row_index < 0 or row_index >= len(rows):
            raise IndexError("Row index out of range")
        deleted = self._row_to_dict(headers, rows.pop(row_index))
        self._write_table(table_name, headers, rows)
        return deleted, self.read_table(table_name)

    def _table_path(self, table_name: str) -> Path:
        if "/" in table_name or "\\" in table_name or table_name in {"", ".", ".."}:
            raise ValueError(f"Invalid table name: {table_name}")
        return self._dir / f"{table_name}.csv"

    def _write_table(self, table_name: str, headers: list[str], rows: list[list]) -> Path:
        path = self._table_path(table_name)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        return path

    @staticmethod
    def _dict_to_row(headers: list[str], row: dict) -> list[str]:
        return ["" if row.get(header) is None else str(row.get(header, "")) for header in headers]

    @staticmethod
    def _row_to_dict(headers: list[str], row: list[str]) -> dict:
        return {header: (row[idx] if idx < len(row) else "") for idx, header in enumerate(headers)}
