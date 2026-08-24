"""ConfigForge API: FastAPI backend for the generation workbench.

Provider Selection Strategy (by env var):
- ARK_CODING_API_KEY / DOUBAO_API_KEY / ARK_API_KEY set → DoubaoProvider for generation (火山方舟 Coding Plan)
- DEEPSEEK_API_KEY set → DeepSeekProvider for critic (异构模型交叉审查)
- Neither set          → MockLLMProvider (MVP mode, 无需 API Key)
"""
import sys, os, asyncio, re, threading, uuid
from pathlib import Path
from typing import Any, Optional

CF_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if CF_ROOT not in sys.path:
    sys.path.insert(0, CF_ROOT)

# Load .env (force-override to ensure latest values)
env_path = Path(CF_ROOT) / ".env"
if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if v:  # only set non-empty values
                    os.environ[k] = v

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

from backend.stores.seed_store import SeedStore
from backend.stores.momo_seed_store import MomoSeedStore
from backend.stores.momo_table_store import MomoTableStore
from backend.stores.trace_store import TraceStore
from backend.stores.result_store import ResultStore
from backend.stores.event_bus import event_bus
from backend.validators.rule_engine import RuleEngine
from backend.validators.momo_rules import MomoRuleEngine
from backend.pipeline.mock_provider import MockLLMProvider
from backend.pipeline.orchestrator import Orchestrator
from backend.pipeline.exporter import CsvExporter
from backend.pipeline.momo_exporter import MomoExporter, MomoExportResult
from backend.evaluation.runner import EvalRunner
from backend.agents.generator import GeneratorAgent
from backend.agents.critic import CriticAgent
from backend.schemas.momo import MomoEncounterBundle, MomoEnemyBundle

app = FastAPI(title="ConfigForge API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ── Stores ────────────────────────────────────────────
seed_store = SeedStore(str(Path(CF_ROOT) / "data" / "seed"))
momo_seed_store = MomoSeedStore(Path(CF_ROOT) / "data" / "seed" / "momo")
trace_store = TraceStore(str(Path(CF_ROOT) / "output" / "traces"))
result_store = ResultStore(str(Path(CF_ROOT) / "output"))
rule_engine = RuleEngine(seed_store)
momo_rule_engine = MomoRuleEngine(momo_seed_store)
csv_exporter = CsvExporter(str(Path(CF_ROOT) / "output" / "csv"))
momo_exporter = MomoExporter(Path(CF_ROOT) / "output" / "momo", momo_rule_engine)
momo_table_store = MomoTableStore(Path(CF_ROOT) / "output" / "momo")

# ── Provider Selection ────────────────────────────────
_ARK = bool(
    os.environ.get("ARK_CODING_API_KEY")
    or os.environ.get("DOUBAO_API_KEY")
    or os.environ.get("ARK_API_KEY")
)
_DS  = bool(os.environ.get("DEEPSEEK_API_KEY"))
gen_provider = None
crit_provider = None
mock_provider = MockLLMProvider(seed_store, momo_seed_store)

if _ARK:
    try:
        from backend.providers import DoubaoProvider
        gen_provider = DoubaoProvider()
        print("[ConfigForge] Generator: DoubaoProvider (火山方舟 Coding Plan)")
    except Exception as e:
        print(f"[ConfigForge] Doubao init failed: {e}")

if _DS:
    try:
        from backend.providers import DeepSeekProvider
        crit_provider = DeepSeekProvider()
        print("[ConfigForge] Critic: DeepSeekProvider (异构交叉审查)")
    except Exception as e:
        print(f"[ConfigForge] DeepSeek init failed: {e}")

# Fallback: if no Doubao but DeepSeek available, use DeepSeek for both
if gen_provider is None and crit_provider is not None:
    gen_provider = crit_provider
    print("[ConfigForge] Generator: DeepSeekProvider (fallback, 无豆包)")

# ── Agent Wrappers ────────────────────────────────────
if gen_provider:
    generator = GeneratorAgent(gen_provider, seed_store, momo_seed_store)
    critic = CriticAgent(crit_provider) if crit_provider else None
else:
    # Mock mode
    class _MockGen:
        def __init__(self, m): self.m = m
        def generate_skill(self, r, fb=""): return self.m.generate_skill_bundle(r, fb)
        def generate_monster(self, r, fb=""): return self.m.generate_monster_bundle(r, fb)
        def generate_quest(self, r, fb=""): return self.m.generate_quest_bundle(r, fb)
        def generate_momo_enemy(self, r, fb=""): return self.m.generate_momo_enemy_bundle(r, fb)
        def generate_momo_encounter(self, r, fb=""): return self.m.generate_momo_encounter_bundle(r, fb)
    class _MockCritic:
        def review(self, d): return mock_provider.review(d, "unknown")
    generator = _MockGen(mock_provider)
    critic = _MockCritic()
    print("[ConfigForge] Using MockLLMProvider (MVP mode)")

orchestrator = Orchestrator(
    generator,
    critic,
    seed_store,
    rule_engine,
    trace_store,
    result_store,
    event_bus=event_bus,
    momo_rule_engine=momo_rule_engine,
)
eval_runner = EvalRunner(orchestrator, rule_engine=rule_engine)
_eval_lock = threading.Lock()
_eval_state = {"running": False}


# ── Models ────────────────────────────────────────────
class GenerateRequest(BaseModel):
    job_type: str = Field(..., pattern="^(skill|monster|quest|momo_enemy|momo_encounter)$")
    requirement: str = Field(..., min_length=3, max_length=500)
    enable_critic: bool = True
    batch_count: Optional[int] = Field(default=None, ge=1, le=20)


class TableRowRequest(BaseModel):
    row: dict[str, Any]


def _chinese_number(value: str) -> Optional[int]:
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
    if value in digits:
        return digits[value]
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return None


def _resolve_batch_count(req: GenerateRequest) -> int:
    requirement = req.requirement
    numeric_patterns = [
        r"(?:生成|创建|设计|制作)\s*(\d{1,2})\s*(?:种|个|只|份|套)",
        r"(\d{1,2})\s*(?:种|个|只|份|套)\s*(?:不同的?)?\s*(?:怪物|技能|任务)",
        r"(?:generate|create|produce)\s+(\d{1,2})\b",
    ]
    for pattern in numeric_patterns:
        match = re.search(pattern, requirement, flags=re.IGNORECASE)
        if match:
            return max(1, min(int(match.group(1)), 20))

    chinese_match = re.search(
        r"(?:生成|创建|设计|制作)\s*([一二三四五六七八九十]{1,3})\s*(?:种|个|只|份|套)",
        requirement,
    )
    if chinese_match:
        count = _chinese_number(chinese_match.group(1))
        if count:
            return max(1, min(count, 20))
    return req.batch_count if req.batch_count is not None else 1


def _generate_one(job_type: str, requirement: str, enable_critic: bool,
                  job_id: str, trace_id: str, emit_events: bool = True) -> dict:
    kwargs = {
        "job_id": job_id,
        "trace_id": trace_id,
        "close_events": False,
        "emit_events": emit_events,
    }
    if job_type == "skill":
        return orchestrator.generate_skill(requirement, enable_critic, **kwargs)
    if job_type == "monster":
        return orchestrator.generate_monster(requirement, enable_critic, **kwargs)
    if job_type == "quest":
        return orchestrator.generate_quest(requirement, enable_critic, **kwargs)
    if job_type == "momo_enemy":
        return orchestrator.generate_momo_enemy(requirement, enable_critic, **kwargs)
    return orchestrator.generate_momo_encounter(requirement, enable_critic, **kwargs)


def _bundle_identity(job_type: str, bundle: dict) -> dict:
    if job_type == "monster":
        config = bundle.get("monster_config") or {}
        return {"id": config.get("monster_id"), "name": config.get("name")}
    if job_type == "quest":
        config = bundle.get("quest_template") or {}
        return {"id": config.get("quest_id"), "name": config.get("name")}
    if job_type == "momo_enemy":
        config = bundle.get("enemy") or {}
        return {"id": config.get("enemy_id"), "name": config.get("name")}
    if job_type == "momo_encounter":
        config = bundle.get("encounter") or {}
        return {"id": config.get("encounter_id"), "name": config.get("name")}
    skills = bundle.get("skills") or []
    first = skills[0] if skills else {}
    return {"id": first.get("skill_id"), "name": first.get("name")}


def _batch_item_requirement(req: GenerateRequest, index: int, total: int,
                            parent_trace_id: str, previous: list[dict]) -> str:
    unique_token = f"b{parent_trace_id[-6:]}_{index:02d}"
    previous_text = ", ".join(
        f"{item.get('name') or 'unnamed'}({item.get('id') or 'no_id'})"
        for item in previous
    ) or "无"
    loot_rule = ""
    if req.job_type == "monster":
        loot_rule = (
            "\n怪物必须提供至少 1 条 monster_loot，item_id 只能从可用道具中选择，"
            "且 loot_group_id 必须与 monster_config.loot_group_id 一致。"
        )
    return (
        f"【原始批量需求】{req.requirement}\n"
        f"【当前子任务】这是批次中的第 {index}/{total} 项；只生成 1 个 {req.job_type} 配置。\n"
        f"【差异化要求】本项必须与其他项在名称、主 ID、数值、技能/目标组合上明显不同。"
        f"所有新建主 ID 应包含唯一标记 {unique_token}。\n"
        f"【已生成项，禁止重复】{previous_text}"
        f"{loot_rule}"
    )


def _is_momo_job(job_type: str) -> bool:
    return job_type in {"momo_enemy", "momo_encounter"}


def _export_momo_release(job_type: str, bundle_dicts: list[dict], job_id: str, trace_id: str) -> MomoExportResult:
    trace = trace_store.get(trace_id) or {"trace_id": trace_id, "status": "unknown", "rounds": []}
    if job_type == "momo_enemy":
        bundles = [MomoEnemyBundle(**bundle) for bundle in bundle_dicts]
    else:
        bundles = [MomoEncounterBundle(**bundle) for bundle in bundle_dicts]
    return momo_exporter.export_release(job_type, bundles, job_id, trace)


def _run_batch_generation(req: GenerateRequest, batch_count: int,
                          parent_job_id: str, parent_trace_id: str) -> dict:
    event_bus.push(parent_job_id, "batch_start", {
        "total": batch_count,
        "job_type": req.job_type,
    })
    items = []
    identities: list[dict] = []
    all_csv_files: set[str] = set()
    is_momo = _is_momo_job(req.job_type)

    for index in range(1, batch_count + 1):
        child_requirement = _batch_item_requirement(
            req, index, batch_count, parent_trace_id, identities
        )
        child_trace_id = trace_store.create(req.job_type, child_requirement, metadata={
            "parent_trace_id": parent_trace_id,
            "batch_index": index,
            "batch_total": batch_count,
        })
        child_job_id = child_trace_id.replace("trace_", "j_")
        event_bus.push(parent_job_id, "batch_item_start", {
            "index": index,
            "total": batch_count,
            "trace_id": child_trace_id,
        })

        try:
            child = _generate_one(
                req.job_type,
                child_requirement,
                req.enable_critic,
                child_job_id,
                child_trace_id,
                emit_events=False,
            )
            # orchestrator 可能已重命名 trace，使用更新后的 trace_id
            child_trace_id = child.get("trace_id", child_trace_id)
            child["csv_files"] = [] if is_momo else [
                str(path) for path in _export(child["bundle"], req.job_type)
            ]
            all_csv_files.update(child["csv_files"])
            identity = _bundle_identity(req.job_type, child["bundle"])
            identities.append(identity)
            item = {
                "index": index,
                **child,
                **identity,
            }
            items.append(item)
            summary = {
                "index": index,
                "job_id": child_job_id,
                "trace_id": child_trace_id,
                "status": child["status"],
                **identity,
            }
            trace_store.add_batch_item(parent_trace_id, summary)
            event_bus.push(parent_job_id, "batch_item_done", {
                **summary,
                "total": batch_count,
            })
        except Exception as exc:
            import traceback
            traceback.print_exc()
            trace_store.complete(child_trace_id, "failed", error=str(exc))
            item = {
                "index": index,
                "job_id": child_job_id,
                "trace_id": child_trace_id,
                "status": "failed",
                "error": str(exc),
            }
            items.append(item)
            trace_store.add_batch_item(parent_trace_id, item)
            event_bus.push(parent_job_id, "batch_item_error", {
                **item,
                "total": batch_count,
            })

    succeeded = sum(item.get("status") == "passed" for item in items)
    failed = batch_count - succeeded
    status = "passed" if failed == 0 else "partial" if succeeded else "failed"
    summary_items = [
        {key: item.get(key) for key in ("index", "job_id", "trace_id", "status", "id", "name", "error")}
        for item in items
    ]
    result = {
        "job_id": parent_job_id,
        "trace_id": parent_trace_id,
        "status": status,
        "type": req.job_type,
        "is_batch": True,
        "batch_count": batch_count,
        "succeeded": succeeded,
        "failed": failed,
        "rounds": sum(item.get("rounds", 0) for item in items),
        "items": items,
        "bundle": [item["bundle"] for item in items if item.get("bundle")],
        "csv_files": sorted(all_csv_files),
    }
    trace_result = {
        "job_id": parent_job_id,
        "type": req.job_type,
        "batch_count": batch_count,
        "succeeded": succeeded,
        "failed": failed,
        "items": summary_items,
    }
    trace_store.complete(parent_trace_id, status, trace_result)
    if is_momo and result["bundle"]:
        release = _export_momo_release(req.job_type, result["bundle"], parent_job_id, parent_trace_id)
        result["csv_files"] = [str(path) for path in release.files if path.suffix == ".csv"]
        result["momo_release"] = release.to_response()
        trace_store.complete(parent_trace_id, status, {**trace_result, "momo_release": result["momo_release"]})
    return result


# ═══════════════ API Routes ═══════════════════════════

@app.get("/api/status")
async def status():
    import os
    provider_model = getattr(gen_provider, "model", None)
    provider_models = getattr(gen_provider, "models", [])
    provider_base_url = getattr(gen_provider, "base_url", None)
    return {
        "mode": "live" if gen_provider else "mock",
        "generator": type(gen_provider).__name__ if gen_provider else "MockLLMProvider",
        "critic": type(crit_provider).__name__ if crit_provider else "MockLLMProvider",
        "model": provider_model or os.environ.get("ARK_CODING_MODEL") or os.environ.get("ARK_MODEL") or "N/A",
        "model_candidates": provider_models,
        "base_url": provider_base_url or os.environ.get("ARK_CODING_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3"),
        "coding_key_set": bool(
            os.environ.get("ARK_CODING_API_KEY")
            or os.environ.get("DOUBAO_API_KEY")
            or os.environ.get("ARK_API_KEY")
        ),
        "ark_key_set": bool(os.environ.get("ARK_API_KEY")),
        "deepseek_key_set": bool(os.environ.get("DEEPSEEK_API_KEY")),
    }


@app.get("/api/test-doubao")
async def test_doubao():
    """测试豆包 API：自动探测可用模型"""
    import os
    from openai import OpenAI

    api_key = (
        os.environ.get("ARK_CODING_API_KEY", "")
        or os.environ.get("DOUBAO_API_KEY", "")
        or os.environ.get("ARK_API_KEY", "")
    )
    candidates = [
        os.environ.get("ARK_CODING_MODEL", ""),
        os.environ.get("ARK_MODEL", ""),
        "ark-code-latest",
        "doubao-seed-code-preview-latest",
        "doubao-seed-2.0-code",
        "doubao-seed-code",
    ]
    candidates = list(dict.fromkeys([c for c in candidates if c]))  # unique, no empty

    results_coding = {}
    client = OpenAI(
        base_url=os.environ.get("ARK_CODING_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v3"),
        api_key=api_key,
    )
    for model in candidates:
        try:
            resp = client.chat.completions.create(
                model=model, max_tokens=10,
                messages=[{"role": "user", "content": "hi"}],
            )
            results_coding[model] = f"OK: {resp.choices[0].message.content}"
        except Exception as e:
            results_coding[model] = str(e)[:150]

    return {
        "coding_endpoint": results_coding,
        "available_models": candidates,
    }

@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """Start generation in background, return job_id immediately for SSE streaming."""
    try:
        batch_count = _resolve_batch_count(req)
        # Pre-allocate IDs so SSE can start listening immediately
        trace_id = trace_store.create(req.job_type, req.requirement, metadata={
            "is_batch": batch_count > 1,
            "batch_count": batch_count,
            "batch_items": [],
        })
        job_id = trace_id.replace("trace_", "j_")

        # Push initial start event
        event_bus.push(job_id, "start", {
            "job_type": req.job_type,
            "requirement": req.requirement,
            "job_id": job_id,
            "batch_count": batch_count,
        })

        # Run generation in background thread
        def _run_orch():
            try:
                if batch_count > 1:
                    result = _run_batch_generation(req, batch_count, job_id, trace_id)
                else:
                    result = _generate_one(
                        req.job_type,
                        req.requirement,
                        req.enable_critic,
                        job_id,
                        trace_id,
                    )
                    if _is_momo_job(req.job_type):
                        release = _export_momo_release(req.job_type, [result["bundle"]], job_id, result["trace_id"])
                        result["csv_files"] = [str(path) for path in release.files if path.suffix == ".csv"]
                        result["momo_release"] = release.to_response()
                        trace_store.complete(result["trace_id"], result["status"], {
                            "job_id": job_id,
                            "type": req.job_type,
                            "momo_release": result["momo_release"],
                        })
                    else:
                        result["csv_files"] = [
                            str(path) for path in _export(result["bundle"], req.job_type)
                        ]
                event_bus.mark_done(job_id, result)
            except Exception as e:
                import traceback; traceback.print_exc()
                trace_store.complete(trace_id, "failed", error=str(e))
                event_bus.mark_error(job_id, str(e))

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _run_orch)

        return JSONResponse({
            "job_id": job_id,
            "trace_id": trace_id,
            "status": "started",
            "batch_count": batch_count,
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, detail=str(e))


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    """SSE endpoint: stream generation progress events."""
    async def event_stream():
        async for chunk in event_bus.stream(job_id):
            yield chunk
    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    return await get_trace(job_id.replace("j_", "trace_"))

@app.get("/api/traces")
async def list_traces(limit: int = Query(50, ge=1, le=200)):
    return trace_store.list_all()[:limit]

@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    t = trace_store.get(trace_id)
    if t is None: raise HTTPException(404, "Trace not found")
    return t

@app.delete("/api/traces/{trace_id}")
async def delete_trace(trace_id: str):
    if not trace_store.delete(trace_id):
        raise HTTPException(404, "Trace not found")
    return {"status": "ok", "deleted": 1, "trace_id": trace_id}

@app.delete("/api/traces")
async def clear_traces(status: Optional[str] = Query(None, pattern="^(running|passed|partial|need_human|failed|error)$")):
    deleted = trace_store.clear(status=status)
    return {"status": "ok", "deleted": deleted, "filter": {"status": status}}

@app.get("/api/tables")
async def list_tables():
    return [*csv_exporter.list_tables(), *momo_table_store.list_tables()]

@app.get("/api/tables/{table_name}")
async def get_table(table_name: str):
    if momo_table_store.is_momo_table_id(table_name):
        try:
            return momo_table_store.read_table(table_name)
        except FileNotFoundError as exc:
            raise HTTPException(404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc))
    return csv_exporter.read_table(table_name)

@app.post("/api/tables/{table_name}/rows")
async def add_table_row(table_name: str, req: TableRowRequest):
    try:
        if momo_table_store.is_momo_table_id(table_name):
            table, sync = momo_table_store.add_row(table_name, req.row)
            return {"status": "ok", "table": table, "json_sync": sync}
        row = _validate_table_row(table_name, req.row)
        table = csv_exporter.add_row(table_name, row)
        sync = _sync_table_change(table_name, "add", row)
        return {"status": "ok", "table": table, "json_sync": sync}
    except FileNotFoundError as exc:
        raise HTTPException(404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))

@app.put("/api/tables/{table_name}/rows/{row_index}")
async def update_table_row(table_name: str, row_index: int, req: TableRowRequest):
    try:
        if momo_table_store.is_momo_table_id(table_name):
            table, sync = momo_table_store.update_row(table_name, row_index, req.row)
            return {"status": "ok", "table": table, "json_sync": sync}
        row = _validate_table_row(table_name, req.row)
        previous, table = csv_exporter.update_row(table_name, row_index, row)
        sync = _sync_table_change(table_name, "update", row, previous=previous)
        return {"status": "ok", "table": table, "json_sync": sync}
    except FileNotFoundError as exc:
        raise HTTPException(404, detail=str(exc))
    except IndexError as exc:
        raise HTTPException(404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))

@app.delete("/api/tables/{table_name}/rows/{row_index}")
async def delete_table_row(table_name: str, row_index: int):
    try:
        if momo_table_store.is_momo_table_id(table_name):
            deleted, table, sync = momo_table_store.delete_row(table_name, row_index)
            return {"status": "ok", "table": table, "deleted_row": deleted, "json_sync": sync}
        deleted, table = csv_exporter.delete_row(table_name, row_index)
        sync = _sync_table_change(table_name, "delete", deleted, previous=deleted)
        return {"status": "ok", "table": table, "deleted_row": deleted, "json_sync": sync}
    except FileNotFoundError as exc:
        raise HTTPException(404, detail=str(exc))
    except IndexError as exc:
        raise HTTPException(404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))

@app.post("/api/tables/validate-all")
async def validate_all():
    return _validate_exported_tables()

@app.post("/api/eval/run")
async def run_eval():
    """Start ablation study in background, return job_id for SSE streaming.

    Progress events are pushed to the event bus under the returned job_id
    (group_start / sample_done / group_done / done) and streamed via the
    existing /api/jobs/{job_id}/events SSE endpoint.
    """
    with _eval_lock:
        if _eval_state["running"]:
            raise HTTPException(409, "An ablation run is already in progress")
        _eval_state["running"] = True

    job_id = f"eval_{uuid.uuid4().hex[:10]}"
    checkpoint_path = str(Path(CF_ROOT) / "output" / "eval" / f"eval_running_{job_id}.json")
    event_bus.push(job_id, "start", {
        "job_id": job_id,
        "message": "Ablation study started (G0-G3)",
    })

    def _run_eval():
        try:
            samples = eval_runner.load_samples()

            def emit(etype: str, data: dict):
                event_bus.push(job_id, etype, data)

            results = eval_runner.run_ablation(
                samples, save_report=True, progress_cb=emit,
                checkpoint_path=checkpoint_path,
            )
            event_bus.mark_done(job_id, {**results, "_report": eval_runner.last_report})
        except Exception as e:
            import traceback
            traceback.print_exc()
            # Keep the partial checkpoint as the recovery artifact.
            eval_runner.finalize_checkpoint(checkpoint_path, "interrupted")
            event_bus.mark_error(job_id, str(e))
        finally:
            with _eval_lock:
                _eval_state["running"] = False

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _run_eval)

    return JSONResponse({
        "job_id": job_id,
        "status": "started",
    })

@app.post("/api/export")
async def export_result(trace_id: str = Query(...)):
    t = trace_store.get(trace_id)
    if t is None: raise HTTPException(404, "Trace not found")
    if _is_momo_job(t["job_type"]) and t.get("final_result", {}).get("momo_release"):
        return {"status": "ok", "trace_id": trace_id, "momo_release": t["final_result"]["momo_release"]}
    rounds = t.get("rounds") or []
    if not rounds:
        raise HTTPException(400, "Trace has no generation rounds")
    final_round = next((r for r in reversed(rounds) if r.get("passed")), rounds[-1])
    bundle = final_round.get("bundle")
    if not bundle:
        raise HTTPException(400, "Trace has no bundle to export")
    if _is_momo_job(t["job_type"]):
        release = _export_momo_release(t["job_type"], [bundle], f"j_{trace_id[-6:]}", trace_id)
        return {
            "status": "ok",
            "trace_id": trace_id,
            "csv_files": [str(path) for path in release.files if path.suffix == ".csv"],
            "momo_release": release.to_response(),
        }
    csv_files = [str(p) for p in _export(bundle, t["job_type"])]
    return {"status": "ok", "trace_id": trace_id, "csv_files": csv_files}

@app.get("/api/seed/context")
async def seed_context():
    seed_store.load()
    return seed_store.to_context()


def _export(bundle_dict: dict, job_type: str):
    from backend.schemas.bundle import SkillBundle, MonsterBundle, QuestBundle
    if job_type == "skill":
        return csv_exporter.export_skill(SkillBundle(**bundle_dict))
    elif job_type == "monster":
        return csv_exporter.export_monster(MonsterBundle(**bundle_dict))
    else:
        return csv_exporter.export_quest(QuestBundle(**bundle_dict))

def _schema_by_table():
    from backend.schemas.skill import SkillConfig
    from backend.schemas.monster import MonsterTemplateConfig, MonsterConfig, MonsterSkillLink, MonsterLootEntry
    from backend.schemas.quest import QuestTemplateConfig, QuestObjectiveConfig

    return {
        "skills": SkillConfig,
        "monster_templates": MonsterTemplateConfig,
        "monster_configs": MonsterConfig,
        "monster_skills": MonsterSkillLink,
        "monster_loot": MonsterLootEntry,
        "quest_templates": QuestTemplateConfig,
        "quest_objectives": QuestObjectiveConfig,
    }


def _validate_table_row(table_name: str, row: dict[str, Any]) -> dict[str, Any]:
    schema = _schema_by_table().get(table_name)
    if schema is None:
        raise ValueError(f"Unknown table: {table_name}")

    clean = {key: (None if value == "" else value) for key, value in row.items()}
    try:
        model = schema(**clean)
    except Exception as exc:
        raise ValueError(str(exc))
    return model.model_dump(mode="json")


_TABLE_KEY_FIELDS = {
    "skills": ("skill_id",),
    "monster_templates": ("template_id",),
    "monster_configs": ("monster_id",),
    "monster_skills": ("monster_id", "slot"),
    "monster_loot": ("loot_group_id", "item_id"),
    "quest_templates": ("quest_id",),
    "quest_objectives": ("objective_id",),
}


def _row_key(table_name: str, row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(field, "")) for field in _TABLE_KEY_FIELDS[table_name])


def _matches_row(table_name: str, candidate: Optional[dict], row: dict[str, Any]) -> bool:
    if not isinstance(candidate, dict):
        return False
    return _row_key(table_name, candidate) == _row_key(table_name, row)


def _sync_table_change(table_name: str, action: str, row: dict[str, Any], previous: Optional[dict[str, Any]] = None) -> dict:
    json_dir = Path(CF_ROOT) / "output" / "json"
    trace_dir = Path(CF_ROOT) / "output" / "traces"
    match_row = previous or row
    warnings: list[str] = []
    files_updated = 0
    records_updated = 0

    for path in json_dir.glob("*.json"):
        changed, count = _sync_bundle_file(path, table_name, action, row, match_row, warnings)
        if changed:
            files_updated += 1
            records_updated += count

    for path in trace_dir.glob("trace_*.json"):
        try:
            data = _read_json(path)
        except Exception:
            continue
        changed = False
        count = 0
        for round_data in data.get("rounds", []):
            bundle = round_data.get("bundle")
            if isinstance(bundle, dict):
                round_changed, round_count = _apply_table_change_to_bundle(bundle, table_name, action, row, match_row, warnings)
                changed = changed or round_changed
                count += round_count
        if changed:
            path.write_text(_json_dumps(data), encoding="utf-8")
            files_updated += 1
            records_updated += count

    return {
        "files_updated": files_updated,
        "records_updated": records_updated,
        "warnings": sorted(set(warnings)),
    }


def _sync_bundle_file(path: Path, table_name: str, action: str, row: dict[str, Any],
                      match_row: dict[str, Any], warnings: list[str]) -> tuple[bool, int]:
    try:
        data = _read_json(path)
    except Exception:
        return False, 0
    changed, count = _apply_table_change_to_bundle(data, table_name, action, row, match_row, warnings)
    if changed:
        path.write_text(_json_dumps(data), encoding="utf-8")
    return changed, count


def _apply_table_change_to_bundle(bundle: dict[str, Any], table_name: str, action: str,
                                  row: dict[str, Any], match_row: dict[str, Any],
    warnings: list[str]) -> tuple[bool, int]:
    if table_name == "skills":
        if action == "add":
            warnings.append("skills: add cannot be assigned to a generated JSON bundle automatically")
            return False, 0
        return _apply_list_change(bundle.get("skills"), table_name, action, row, match_row)
    if table_name == "monster_templates":
        return _apply_object_change(bundle, ("monster_template", "summon_template"), table_name, action, row, match_row, warnings)
    if table_name == "monster_configs":
        return _apply_object_change(bundle, ("monster_config", "summon_config"), table_name, action, row, match_row, warnings)
    if table_name == "monster_skills":
        return _apply_parented_list_change(bundle, table_name, action, row, match_row, [
            ("monster_config", "monster_id", "monster_skills"),
            ("summon_config", "monster_id", "summon_skills"),
        ])
    if table_name == "monster_loot":
        return _apply_parented_list_change(bundle, table_name, action, row, match_row, [
            ("monster_config", "loot_group_id", "monster_loot"),
            ("summon_config", "loot_group_id", "summon_loot"),
        ])
    if table_name == "quest_templates":
        return _apply_object_change(bundle, ("quest_template",), table_name, action, row, match_row, warnings)
    if table_name == "quest_objectives":
        return _apply_parented_list_change(bundle, table_name, action, row, match_row, [
            ("quest_template", "quest_id", "quest_objectives"),
        ])
    return False, 0


def _apply_object_change(bundle: dict[str, Any], object_keys: tuple[str, ...], table_name: str, action: str,
                         row: dict[str, Any], match_row: dict[str, Any], warnings: list[str]) -> tuple[bool, int]:
    changed = False
    count = 0
    if action == "add":
        warnings.append(f"{table_name}: top-level add cannot be assigned to a generated JSON bundle automatically")
        return False, 0
    for key in object_keys:
        if _matches_row(table_name, bundle.get(key), match_row):
            if action == "delete":
                warnings.append(f"{table_name}: top-level delete was applied to CSV only; generated JSON bundle was kept valid")
                continue
            bundle[key] = row
            changed = True
            count += 1
    return changed, count


def _apply_list_change(items: Any, table_name: str, action: str,
                       row: dict[str, Any], match_row: dict[str, Any]) -> tuple[bool, int]:
    if not isinstance(items, list):
        return False, 0
    if action == "add":
        if any(_matches_row(table_name, item, row) for item in items):
            return False, 0
        items.append(row)
        return True, 1

    changed = False
    count = 0
    next_items = []
    for item in items:
        if _matches_row(table_name, item, match_row):
            changed = True
            count += 1
            if action == "update":
                next_items.append(row)
        else:
            next_items.append(item)
    if changed:
        items[:] = next_items
    return changed, count


def _apply_parented_list_change(bundle: dict[str, Any], table_name: str, action: str,
                                row: dict[str, Any], match_row: dict[str, Any],
                                mappings: list[tuple[str, str, str]]) -> tuple[bool, int]:
    changed = False
    count = 0
    for parent_key, parent_field, list_key in mappings:
        parent = bundle.get(parent_key)
        items = bundle.get(list_key)
        if not isinstance(parent, dict) or not isinstance(items, list):
            continue
        if action == "add" and str(parent.get(parent_field, "")) != str(row.get(parent_field, "")):
            continue
        list_changed, list_count = _apply_list_change(items, table_name, action, row, match_row)
        changed = changed or list_changed
        count += list_count
    return changed, count


def _read_json(path: Path) -> dict:
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def _json_dumps(data: dict) -> str:
    import json
    return json.dumps(data, ensure_ascii=False, indent=2)


def _validate_exported_tables():
    schema_by_table = _schema_by_table()

    violations = []
    checked_rows = 0
    for table_name in csv_exporter.list_tables():
        schema = schema_by_table.get(table_name)
        if schema is None:
            continue
        table = csv_exporter.read_table(table_name)
        headers = table.get("headers", [])
        for idx, row in enumerate(table.get("rows", []), start=2):
            checked_rows += 1
            values = {
                header: (None if value == "" else value)
                for header, value in zip(headers, row)
            }
            try:
                schema(**values)
            except Exception as exc:
                violations.append({
                    "table": table_name,
                    "row": idx,
                    "message": str(exc),
                })

    return {
        "status": "ok" if not violations else "failed",
        "checked_rows": checked_rows,
        "violations": violations,
    }


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
