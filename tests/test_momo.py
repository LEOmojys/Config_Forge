import csv
import importlib
import json
from pathlib import Path

from backend.pipeline.mock_provider import MockLLMProvider
from backend.pipeline.orchestrator import Orchestrator
from backend.schemas.momo import (
    MomoAttackCategory,
    MomoAttackDefinition,
    MomoArchetype,
    MomoEncounterBundle,
    MomoEncounterDefinition,
    MomoEncounterType,
    MomoEncounterWave,
    MomoEnemyBundle,
    MomoEnemyDefinition,
    MomoRole,
    MomoSpawn,
)
from backend.stores.momo_seed_store import MomoSeedStore
from backend.stores.result_store import ResultStore
from backend.stores.seed_store import SeedStore
from backend.stores.trace_store import TraceStore
from backend.validators.momo_rules import MomoRuleEngine
from backend.pipeline.momo_exporter import MomoExporter


ROOT = Path(__file__).resolve().parents[1]
MOMO_SEED_DIR = ROOT / "data" / "seed" / "momo"


def _rules() -> MomoRuleEngine:
    store = MomoSeedStore(MOMO_SEED_DIR)
    store.load()
    return MomoRuleEngine(store)


def _normal_enemy() -> MomoEnemyBundle:
    enemy = MomoEnemyDefinition(
        enemy_id="momo_enemy_cinder_stalker",
        region_id="region_1_foundry",
        role=MomoRole.NORMAL_MELEE,
        archetype=MomoArchetype.CRAWLER,
        name="Cinder Stalker",
        description="A fast scrap crawler that pressures close-range movement.",
        max_health=32,
        move_speed=2.4,
        radius=0.48,
        touch_range=1.0,
        preferred_range=0.0,
        damage=2,
        telegraph_time=0.38,
        active_time=0.18,
        recovery_time=0.72,
        cooldown=1.28,
        tuning_profile_id="region_1_normal",
        asset_id="enemy_scrap_crawler",
    )
    attack = MomoAttackDefinition(
        attack_id="momo_attack_cinder_stalker_slam",
        enemy_id=enemy.enemy_id,
        attack_category=MomoAttackCategory.DIRECT,
        damage=2,
        telegraph_time=0.38,
        active_time=0.18,
        recovery_time=0.72,
        cooldown=1.28,
        max_hits_per_target=1,
        projectile_type=None,
        warning_asset_id="enemy_warning_ring",
        summon_enemy_id=None,
        phase=1,
        description="A short-range scraping slam.",
    )
    return MomoEnemyBundle(enemy=enemy, attacks=[attack])


def _boss_enemy() -> MomoEnemyBundle:
    enemy = _normal_enemy().enemy.model_copy(
        update={
            "enemy_id": "momo_enemy_furnace_overseer",
            "role": MomoRole.BOSS,
            "archetype": MomoArchetype.BOSS,
            "name": "Furnace Overseer",
            "max_health": 560,
            "move_speed": 1.25,
            "radius": 1.05,
            "touch_range": 1.65,
            "damage": 4,
            "tuning_profile_id": "region_1_boss",
            "asset_id": "enemy_furnace_overseer",
        }
    )
    return MomoEnemyBundle(
        enemy=enemy,
        attacks=[
            MomoAttackDefinition(
                attack_id="momo_attack_overseer_crush",
                enemy_id=enemy.enemy_id,
                attack_category=MomoAttackCategory.DIRECT,
                damage=4,
                telegraph_time=0.72,
                active_time=0.22,
                recovery_time=1.05,
                cooldown=1.9,
                max_hits_per_target=1,
                projectile_type=None,
                warning_asset_id="enemy_warning_ring",
                summon_enemy_id=None,
                phase=1,
                description="A close hammer crush.",
            ),
            MomoAttackDefinition(
                attack_id="momo_attack_overseer_fireball",
                enemy_id=enemy.enemy_id,
                attack_category=MomoAttackCategory.PROJECTILE,
                damage=3,
                telegraph_time=0.8,
                active_time=0.2,
                recovery_time=1.1,
                cooldown=2.5,
                max_hits_per_target=1,
                projectile_type="enemy_boss_fireball",
                warning_asset_id="enemy_warning_ring",
                summon_enemy_id=None,
                phase=1,
                description="Launches a furnace fireball.",
            ),
            MomoAttackDefinition(
                attack_id="momo_attack_overseer_summon",
                enemy_id=enemy.enemy_id,
                attack_category=MomoAttackCategory.SUMMON,
                damage=0,
                telegraph_time=0.8,
                active_time=0.2,
                recovery_time=1.2,
                cooldown=7.0,
                max_hits_per_target=0,
                projectile_type=None,
                warning_asset_id="enemy_warning_ring",
                summon_enemy_id="enemy_crawler",
                phase=2,
                description="Summons two crawler workers.",
            ),
        ],
    )


def _encounter() -> MomoEncounterBundle:
    encounter = MomoEncounterDefinition(
        encounter_id="momo_encounter_foundry_patrol",
        region_id="region_1_foundry",
        encounter_type=MomoEncounterType.NORMAL,
        room_id="open_court",
        name="Foundry Patrol",
        reward_gold=14,
        combat_seed_policy="derived",
        max_alive_enemies=5,
        description="A mixed patrol guarding the foundry approach.",
    )
    wave = MomoEncounterWave(
        encounter_id=encounter.encounter_id,
        wave_index=1,
        spawns=[
            MomoSpawn(
                enemy_id="enemy_crawler",
                count=3,
                spawn_group="north_scrap",
                spawn_x=-5.2,
                spawn_y=2.4,
            ),
            MomoSpawn(
                enemy_id="enemy_shooter",
                count=2,
                spawn_group="south_rivets",
                spawn_x=5.2,
                spawn_y=-2.4,
            ),
        ],
    )
    return MomoEncounterBundle(encounter=encounter, waves=[wave])


def test_enemy_bundle_passes_when_seed_and_combat_rules_are_satisfied() -> None:
    assert _rules().validate_enemy_bundle(_normal_enemy()).passed


def test_boss_bundle_fails_when_core_summon_attack_is_missing() -> None:
    bundle = _boss_enemy()
    invalid = bundle.model_copy(update={"attacks": bundle.attacks[:2]})

    violations = _rules().validate_enemy_bundle(invalid).violations

    assert any(item.rule_id == "MOMO_R008" for item in violations)


def test_enemy_bundle_rejects_unknown_asset() -> None:
    bundle = _normal_enemy()
    invalid = bundle.model_copy(update={"enemy": bundle.enemy.model_copy(update={"asset_id": "enemy_unknown"})})

    assert not _rules().validate_enemy_bundle(invalid).passed


def test_enemy_bundle_rejects_unknown_region_and_duplicate_attack_id() -> None:
    bundle = _normal_enemy()
    duplicate = bundle.attacks[0].model_copy()
    invalid = bundle.model_copy(
        update={
            "enemy": bundle.enemy.model_copy(update={"region_id": "region_unknown"}),
            "attacks": [bundle.attacks[0], duplicate],
        }
    )

    rule_ids = {item.rule_id for item in _rules().validate_enemy_bundle(invalid).violations}

    assert {"MOMO_R002", "MOMO_R004"}.issubset(rule_ids)


def test_enemy_bundle_rejects_unreadable_attack_timing() -> None:
    bundle = _normal_enemy()
    invalid_attack = bundle.attacks[0].model_copy(update={"telegraph_time": 0.05})
    invalid = bundle.model_copy(update={"attacks": [invalid_attack]})

    assert any(item.rule_id == "MOMO_R006" for item in _rules().validate_enemy_bundle(invalid).violations)


def test_encounter_bundle_passes_when_spawns_fit_region_constraints() -> None:
    assert _rules().validate_encounter_bundle(_encounter()).passed


def test_encounter_bundle_rejects_unknown_enemy_reference() -> None:
    bundle = _encounter()
    unknown_spawn = bundle.waves[0].spawns[0].model_copy(update={"enemy_id": "enemy_unknown"})
    invalid_wave = bundle.waves[0].model_copy(update={"spawns": [unknown_spawn]})
    invalid = bundle.model_copy(update={"waves": [invalid_wave]})

    assert any(item.rule_id == "MOMO_R009" for item in _rules().validate_encounter_bundle(invalid).violations)


def test_mock_generation_is_deterministic_and_satisfies_momo_rules() -> None:
    generic_seed = SeedStore(ROOT / "data" / "seed")
    generic_seed.load()
    momo_seed = MomoSeedStore(MOMO_SEED_DIR)
    momo_seed.load()
    provider = MockLLMProvider(generic_seed, momo_seed)

    first = provider.generate_momo_enemy_bundle("Generate a foundry boss for MoMo")
    second = provider.generate_momo_enemy_bundle("Generate a foundry boss for MoMo")

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert _rules().validate_enemy_bundle(first).passed


def test_mock_batch_generation_keeps_ten_enemy_identities_unique() -> None:
    generic_seed = SeedStore(ROOT / "data" / "seed")
    generic_seed.load()
    momo_seed = MomoSeedStore(MOMO_SEED_DIR)
    momo_seed.load()
    provider = MockLLMProvider(generic_seed, momo_seed)

    bundles = [
        provider.generate_momo_enemy_bundle(f"Generate a foundry enemy batch token {index}")
        for index in range(10)
    ]

    assert len({bundle.enemy.enemy_id for bundle in bundles}) == 10
    assert len({bundle.enemy.name for bundle in bundles}) == 10
    assert all(_rules().validate_enemy_bundle(bundle).passed for bundle in bundles)


def test_orchestrator_generates_a_momo_enemy_in_dry_run_mode(tmp_path: Path) -> None:
    generic_seed = SeedStore(ROOT / "data" / "seed")
    generic_seed.load()
    momo_seed = MomoSeedStore(MOMO_SEED_DIR)
    momo_seed.load()
    provider = MockLLMProvider(generic_seed, momo_seed)

    class MomoGenerator:
        def generate_momo_enemy(self, requirement: str, feedback: str = "") -> MomoEnemyBundle:
            return provider.generate_momo_enemy_bundle(requirement, feedback)

    orchestrator = Orchestrator(
        MomoGenerator(),
        critic=None,
        seed_store=generic_seed,
        rule_engine=None,
        trace_store=TraceStore(tmp_path / "traces"),
        result_store=ResultStore(tmp_path / "output"),
        momo_rule_engine=_rules(),
    )

    result = orchestrator.generate_momo_enemy("Generate an elite MoMo foundry enemy", dry_run=True)

    assert result["status"] == "passed"
    assert result["type"] == "momo_enemy"
    assert result["bundle"]["enemy"]["archetype"] == "elite"


def test_completed_trace_returns_the_readable_trace_id_after_rename(tmp_path: Path) -> None:
    traces = TraceStore(tmp_path / "traces")
    trace_id = traces.create("momo_enemy", "Generate a foundry enemy")

    readable_trace_id = traces.complete(trace_id, "passed", config_name="Foundry Crawler")

    assert readable_trace_id.startswith("trace__momo_enemy__Foundry_Crawler__")
    assert traces.get(readable_trace_id) is not None


def test_exporter_writes_a_self_consistent_enemy_release_pack(tmp_path: Path) -> None:
    exporter = MomoExporter(tmp_path / "momo", _rules())
    release = exporter.export_release(
        job_type="momo_enemy",
        bundles=[_normal_enemy()],
        job_id="j_release_test",
        trace={"trace_id": "trace_release_test", "status": "passed", "rounds": []},
    )

    expected_files = {
        "manifest.json",
        "content.json",
        "enemies.csv",
        "enemy_attacks.csv",
        "validation-report.json",
        "trace.json",
    }
    assert expected_files.issubset({path.name for path in release.files})

    content = json.loads((release.release_dir / "content.json").read_text(encoding="utf-8"))
    with (release.release_dir / "enemies.csv").open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))

    assert content["enemies"][0]["enemy_id"] == csv_rows[0]["enemy_id"]
    assert content["enemies"][0]["asset_id"] == csv_rows[0]["asset_id"]


def test_api_batch_generation_writes_one_momo_release_without_generic_csv(tmp_path: Path, monkeypatch) -> None:
    api = importlib.import_module("backend.api.app")

    generic_seed = SeedStore(ROOT / "data" / "seed")
    generic_seed.load()
    momo_seed = MomoSeedStore(MOMO_SEED_DIR)
    momo_seed.load()
    rules = MomoRuleEngine(momo_seed)
    provider = MockLLMProvider(generic_seed, momo_seed)

    class MomoGenerator:
        def generate_momo_enemy(self, requirement: str, feedback: str = "") -> MomoEnemyBundle:
            return provider.generate_momo_enemy_bundle(requirement, feedback)

    class EventBus:
        def push(self, job_id: str, event_type: str, data: dict) -> None:
            return None

    traces = TraceStore(tmp_path / "traces")
    monkeypatch.setattr(api, "trace_store", traces)
    monkeypatch.setattr(api, "event_bus", EventBus())
    monkeypatch.setattr(api, "momo_exporter", MomoExporter(tmp_path / "momo", rules))
    monkeypatch.setattr(
        api,
        "orchestrator",
        Orchestrator(
            MomoGenerator(),
            critic=None,
            seed_store=generic_seed,
            rule_engine=None,
            trace_store=traces,
            result_store=ResultStore(tmp_path / "output"),
            momo_rule_engine=rules,
        ),
    )
    parent_trace_id = traces.create("momo_enemy", "Generate 10 foundry enemies")
    request = api.GenerateRequest(
        job_type="momo_enemy",
        requirement="Generate 10 different MoMo foundry enemies",
        enable_critic=False,
    )

    result = api._run_batch_generation(request, 10, "j_parent", parent_trace_id)

    release_dir = Path(result["momo_release"]["release_dir"])
    content = json.loads((release_dir / "content.json").read_text(encoding="utf-8"))
    assert result["status"] == "passed"
    assert result["succeeded"] == 10
    assert len(content["enemies"]) == 10
    assert (release_dir / "enemies.csv").exists()
    assert not (tmp_path / "output" / "csv").exists()
