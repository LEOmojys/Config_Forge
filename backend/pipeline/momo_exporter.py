import csv
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..schemas.momo import MomoEncounterBundle, MomoEnemyBundle
from ..validators.momo_rules import MomoRuleEngine


@dataclass(frozen=True, slots=True)
class MomoExportResult:
    release_dir: Path
    files: list[Path]
    validation_passed: bool

    def to_response(self) -> dict[str, str | bool]:
        return {
            "release_dir": str(self.release_dir),
            "manifest": str(self.release_dir / "manifest.json"),
            "validation_report": str(self.release_dir / "validation-report.json"),
            "validation_passed": self.validation_passed,
        }


class MomoExporter:
    def __init__(self, output_dir: str | Path, rule_engine: MomoRuleEngine) -> None:
        self.output_dir = Path(output_dir)
        self.rule_engine = rule_engine

    def export_release(self, job_type: str, bundles: list[MomoEnemyBundle] | list[MomoEncounterBundle], job_id: str, trace: dict) -> MomoExportResult:
        self.rule_engine.seed.load()
        release_dir = self._release_dir(job_id)
        release_dir.mkdir(parents=True, exist_ok=False)
        content = self._content(job_type, bundles)
        validation = self._validation(job_type, bundles)
        status = "approved" if validation["passed"] else "needs_review"
        balance = self.rule_engine.seed.balance
        manifest = {
            "format": "momo-content-pack",
            "format_version": 1,
            "design_version": balance.design_version if balance else "unknown",
            "config_version": balance.config_version if balance else "unknown",
            "source": "configforge",
            "status": status,
            "job_type": job_type,
            "bundle_count": len(bundles),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        files = [
            self._write_json(release_dir / "manifest.json", manifest),
            self._write_json(release_dir / "content.json", content),
            self._write_json(release_dir / "validation-report.json", validation),
            self._write_json(release_dir / "trace.json", {**trace, "momo_release": str(release_dir)}),
        ]
        match job_type:
            case "momo_enemy":
                files.extend(self._write_enemy_csvs(release_dir, content))
            case "momo_encounter":
                files.extend(self._write_encounter_csvs(release_dir, content))
            case _:
                raise ValueError(f"Unsupported MoMo job type: {job_type}")
        return MomoExportResult(release_dir, files, bool(validation["passed"]))

    def _content(self, job_type: str, bundles: list[MomoEnemyBundle] | list[MomoEncounterBundle]) -> dict:
        match job_type:
            case "momo_enemy":
                enemy_bundles = [bundle for bundle in bundles if isinstance(bundle, MomoEnemyBundle)]
                return {
                    "format": "momo-content-pack",
                    "job_type": job_type,
                    "enemies": [bundle.enemy.model_dump(mode="json") for bundle in enemy_bundles],
                    "enemy_attacks": [attack.model_dump(mode="json") for bundle in enemy_bundles for attack in bundle.attacks],
                }
            case "momo_encounter":
                encounter_bundles = [bundle for bundle in bundles if isinstance(bundle, MomoEncounterBundle)]
                return {
                    "format": "momo-content-pack",
                    "job_type": job_type,
                    "encounters": [bundle.encounter.model_dump(mode="json") for bundle in encounter_bundles],
                    "encounter_waves": [
                        {
                            "encounter_id": wave.encounter_id,
                            "wave_index": wave.wave_index,
                            **spawn.model_dump(mode="json"),
                        }
                        for bundle in encounter_bundles
                        for wave in bundle.waves
                        for spawn in wave.spawns
                    ],
                }
            case _:
                raise ValueError(f"Unsupported MoMo job type: {job_type}")

    def _validation(self, job_type: str, bundles: list[MomoEnemyBundle] | list[MomoEncounterBundle]) -> dict:
        violations = []
        for bundle in bundles:
            match job_type:
                case "momo_enemy":
                    result = self.rule_engine.validate_enemy_bundle(bundle)
                case "momo_encounter":
                    result = self.rule_engine.validate_encounter_bundle(bundle)
                case _:
                    raise ValueError(f"Unsupported MoMo job type: {job_type}")
            violations.extend(
                {
                    "rule_id": item.rule_id,
                    "severity": item.severity,
                    "table": item.table,
                    "field": item.field,
                    "message": item.message,
                }
                for item in result.violations
            )
        return {"passed": not violations, "violations": violations}

    def _write_enemy_csvs(self, release_dir: Path, content: dict) -> list[Path]:
        return [
            self._write_csv(release_dir / "enemies.csv", content["enemies"]),
            self._write_csv(release_dir / "enemy_attacks.csv", content["enemy_attacks"]),
        ]

    def _write_encounter_csvs(self, release_dir: Path, content: dict) -> list[Path]:
        return [
            self._write_csv(release_dir / "encounters.csv", content["encounters"]),
            self._write_csv(release_dir / "encounter_waves.csv", content["encounter_waves"]),
        ]

    @staticmethod
    def _write_json(path: Path, payload: dict) -> Path:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _write_csv(path: Path, rows: list[dict]) -> Path:
        headers = list(rows[0].keys()) if rows else []
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def _release_dir(self, job_id: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = uuid.uuid4().hex[:6]
        return self.output_dir / f"release_{stamp}_{job_id.replace('j_', '')[-6:]}_{suffix}"
