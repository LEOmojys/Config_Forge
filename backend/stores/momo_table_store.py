import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from ..pipeline.exporter import CsvExporter
from ..schemas.momo import (
    MomoAttackDefinition,
    MomoEncounterDefinition,
    MomoEncounterWave,
    MomoEnemyDefinition,
    MomoSpawn,
)


_TABLE_PREFIX: Final = "momo:"
_TABLES_BY_JOB_TYPE: Final = {
    "momo_enemy": ("enemies", "enemy_attacks"),
    "momo_encounter": ("encounters", "encounter_waves"),
}
_CHILD_TABLES: Final = {
    "enemies": ("enemy_attacks", "enemy_id"),
    "encounters": ("encounter_waves", "encounter_id"),
}
_PARENT_TABLES: Final = {child: (parent, field) for parent, (child, field) in _CHILD_TABLES.items()}
_WAVE_ROW_FIELDS: Final = (
    "encounter_id",
    "wave_index",
    "enemy_id",
    "count",
    "spawn_group",
    "spawn_x",
    "spawn_y",
)


@dataclass(frozen=True, slots=True)
class _MomoTableLocation:
    release_dir: Path
    table_name: str
    job_type: str


class MomoTableStore:
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir).resolve()

    @staticmethod
    def is_momo_table_id(table_id: str) -> bool:
        return table_id.startswith(_TABLE_PREFIX)

    def list_tables(self) -> list[str]:
        if not self.output_dir.is_dir():
            return []

        tables: list[str] = []
        for release_dir in sorted(self.output_dir.iterdir(), key=lambda path: path.name, reverse=True):
            if not release_dir.is_dir():
                continue
            try:
                job_type = self._release_job_type(release_dir)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                continue
            for table_name in _TABLES_BY_JOB_TYPE[job_type]:
                if (release_dir / f"{table_name}.csv").is_file():
                    tables.append(self._table_id(release_dir.name, table_name))
        return tables

    def read_table(self, table_id: str) -> dict:
        location = self._resolve_table(table_id)
        return self._read_table(location, table_id)

    def add_row(self, table_id: str, row: dict) -> tuple[dict, dict]:
        location = self._resolve_table(table_id)
        clean_row = self._validate_row(location.table_name, row)
        self._ensure_parent_exists(location, clean_row)
        table = self._exporter(location).add_row(location.table_name, clean_row)
        table["table_name"] = table_id
        return table, self._sync_release(location)

    def update_row(self, table_id: str, row_index: int, row: dict) -> tuple[dict, dict]:
        location = self._resolve_table(table_id)
        clean_row = self._validate_row(location.table_name, row)
        self._ensure_parent_exists(location, clean_row)
        previous, table = self._exporter(location).update_row(location.table_name, row_index, clean_row)
        related_rows = self._cascade_child_rows(location, previous, clean_row)
        table["table_name"] = table_id
        return table, self._sync_release(location, related_rows + 1)

    def delete_row(self, table_id: str, row_index: int) -> tuple[dict, dict, dict]:
        location = self._resolve_table(table_id)
        deleted, table = self._exporter(location).delete_row(location.table_name, row_index)
        related_rows = self._cascade_child_rows(location, deleted, None)
        table["table_name"] = table_id
        return deleted, table, self._sync_release(location, related_rows + 1)

    def _resolve_table(self, table_id: str) -> _MomoTableLocation:
        parts = table_id.split(":")
        if len(parts) != 3 or parts[0] != "momo":
            raise ValueError(f"Invalid MoMo table ID: {table_id}")

        release_name, table_name = parts[1:]
        if (
            not release_name.startswith("release_")
            or any(character in release_name for character in ("/", "\\", ":"))
        ):
            raise ValueError(f"Invalid MoMo release name: {release_name}")

        release_dir = (self.output_dir / release_name).resolve()
        if release_dir.parent != self.output_dir or not release_dir.is_dir():
            raise FileNotFoundError(f"MoMo release not found: {release_name}")

        job_type = self._release_job_type(release_dir)
        if table_name not in _TABLES_BY_JOB_TYPE[job_type]:
            raise ValueError(f"Unsupported MoMo table: {table_name}")
        if not (release_dir / f"{table_name}.csv").is_file():
            raise FileNotFoundError(f"MoMo table not found: {table_name}")

        return _MomoTableLocation(release_dir, table_name, job_type)

    def _read_table(self, location: _MomoTableLocation, table_id: str) -> dict:
        table = self._exporter(location).read_table(location.table_name)
        table["table_name"] = table_id
        return table

    @staticmethod
    def _table_id(release_name: str, table_name: str) -> str:
        return f"{_TABLE_PREFIX}{release_name}:{table_name}"

    @staticmethod
    def _exporter(location: _MomoTableLocation) -> CsvExporter:
        return CsvExporter(location.release_dir)

    def _release_job_type(self, release_dir: Path) -> str:
        manifest = self._read_json(release_dir / "manifest.json")
        job_type = manifest.get("job_type")
        if job_type not in _TABLES_BY_JOB_TYPE:
            raise ValueError(f"Unsupported MoMo release job type: {job_type}")
        return job_type

    def _sync_release(self, location: _MomoTableLocation, records_updated: int = 1) -> dict:
        content = {
            "format": "momo-content-pack",
            "job_type": location.job_type,
        }
        for table_name in _TABLES_BY_JOB_TYPE[location.job_type]:
            content[table_name] = self._validated_rows(location.release_dir, table_name)

        self._write_json(location.release_dir / "content.json", content)
        self._mark_validation_stale(location.release_dir, len(content[_TABLES_BY_JOB_TYPE[location.job_type][0]]))
        return {
            "files_updated": 3,
            "records_updated": records_updated,
            "warnings": ["MoMo release validation is stale after a table edit."],
        }

    def _ensure_parent_exists(self, location: _MomoTableLocation, row: dict) -> None:
        parent = _PARENT_TABLES.get(location.table_name)
        if parent is None:
            return
        parent_table, reference_field = parent
        table = self._exporter(location).read_table(parent_table)
        references = {item[table["headers"].index(reference_field)] for item in table["rows"]}
        if str(row[reference_field]) not in references:
            raise ValueError(f"{location.table_name}.{reference_field} must reference an existing {parent_table} row")

    def _cascade_child_rows(self, location: _MomoTableLocation, previous: dict, row: dict | None) -> int:
        child = _CHILD_TABLES.get(location.table_name)
        if child is None:
            return 0
        child_table, reference_field = child
        exporter = self._exporter(location)
        table = exporter.read_table(child_table)
        reference_index = table["headers"].index(reference_field)
        old_reference = str(previous[reference_field])
        next_reference = str(row[reference_field]) if row is not None else None
        changed = 0
        for row_index in range(len(table["rows"]) - 1, -1, -1):
            child_row = table["rows"][row_index]
            if child_row[reference_index] != old_reference:
                continue
            if next_reference is None:
                exporter.delete_row(child_table, row_index)
            else:
                values = dict(zip(table["headers"], child_row))
                values[reference_field] = next_reference
                exporter.update_row(child_table, row_index, values)
            changed += 1
        return changed

    def _validated_rows(self, release_dir: Path, table_name: str) -> list[dict]:
        table = CsvExporter(release_dir).read_table(table_name)
        if table.get("error"):
            raise FileNotFoundError(f"MoMo table not found: {table_name}")

        headers = table["headers"]
        rows: list[dict] = []
        for row in table["rows"]:
            if len(row) != len(headers):
                raise ValueError(f"Invalid CSV row width in {table_name}")
            rows.append(self._validate_row(table_name, dict(zip(headers, row))))
        return rows

    def _validate_row(self, table_name: str, row: dict) -> dict:
        clean = {key: None if value == "" else value for key, value in row.items()}
        try:
            match table_name:
                case "enemies":
                    return MomoEnemyDefinition(**clean).model_dump(mode="json")
                case "enemy_attacks":
                    return MomoAttackDefinition(**clean).model_dump(mode="json")
                case "encounters":
                    return MomoEncounterDefinition(**clean).model_dump(mode="json")
                case "encounter_waves":
                    return self._validate_wave_row(clean)
                case _:
                    raise ValueError(f"Unsupported MoMo table: {table_name}")
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    @staticmethod
    def _validate_wave_row(row: dict) -> dict:
        unexpected_fields = set(row) - set(_WAVE_ROW_FIELDS)
        if unexpected_fields:
            raise ValueError(f"Unexpected encounter wave fields: {sorted(unexpected_fields)}")

        spawn = MomoSpawn(**{field: row.get(field) for field in _WAVE_ROW_FIELDS[2:]})
        wave = MomoEncounterWave(
            encounter_id=row.get("encounter_id"),
            wave_index=row.get("wave_index"),
            spawns=[spawn],
        )
        return {
            "encounter_id": wave.encounter_id,
            "wave_index": wave.wave_index,
            **spawn.model_dump(mode="json"),
        }

    def _mark_validation_stale(self, release_dir: Path, bundle_count: int) -> None:
        manifest_path = release_dir / "manifest.json"
        manifest = self._read_json(manifest_path)
        manifest["status"] = "needs_review"
        manifest["validation_stale"] = True
        manifest["bundle_count"] = bundle_count
        self._write_json(manifest_path, manifest)

        report_path = release_dir / "validation-report.json"
        report = self._read_json(report_path)
        report["stale"] = True
        report["stale_reason"] = "A MoMo table was edited after this release was validated."
        self._write_json(report_path, report)

    @staticmethod
    def _read_json(path: Path) -> dict:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Expected JSON object in {path.name}")
        return payload

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
