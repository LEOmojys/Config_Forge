"""ConfigForge API: FastAPI backend for the generation workbench.

Provider Selection Strategy (by env var):
- ARK_API_KEY set     → DoubaoProvider for generation (火山方舟 json_schema 严格输出)
- DEEPSEEK_API_KEY set → DeepSeekProvider for critic (异构模型交叉审查)
- Neither set          → MockLLMProvider (MVP mode, 无需 API Key)
"""
import sys, os, asyncio
from pathlib import Path
from typing import Optional

CF_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if CF_ROOT not in sys.path:
    sys.path.insert(0, CF_ROOT)

# Load .env
env_path = Path(CF_ROOT) / ".env"
if env_path.exists():
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

from backend.stores.seed_store import SeedStore
from backend.stores.trace_store import TraceStore
from backend.stores.result_store import ResultStore
from backend.stores.event_bus import event_bus
from backend.validators.rule_engine import RuleEngine
from backend.pipeline.mock_provider import MockLLMProvider
from backend.pipeline.orchestrator import Orchestrator
from backend.pipeline.exporter import CsvExporter
from backend.evaluation.runner import EvalRunner
from backend.agents.generator import GeneratorAgent
from backend.agents.critic import CriticAgent

app = FastAPI(title="ConfigForge API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ── Stores ────────────────────────────────────────────
seed_store = SeedStore(str(Path(CF_ROOT) / "data" / "seed"))
trace_store = TraceStore(str(Path(CF_ROOT) / "output" / "traces"))
result_store = ResultStore(str(Path(CF_ROOT) / "output"))
rule_engine = RuleEngine(seed_store)
csv_exporter = CsvExporter(str(Path(CF_ROOT) / "output" / "csv"))

# ── Provider Selection ────────────────────────────────
_ARK = bool(os.environ.get("ARK_API_KEY"))
_DS  = bool(os.environ.get("DEEPSEEK_API_KEY"))
gen_provider = None
crit_provider = None
mock_provider = MockLLMProvider(seed_store)

if _ARK:
    try:
        from backend.providers import DoubaoProvider
        gen_provider = DoubaoProvider()
        print("[ConfigForge] Generator: DoubaoProvider (火山方舟 json_schema strict)")
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
    generator = GeneratorAgent(gen_provider, seed_store)
    critic = CriticAgent(crit_provider) if crit_provider else None
else:
    # Mock mode
    class _MockGen:
        def __init__(self, m): self.m = m
        def generate_skill(self, r, fb=""): return self.m.generate_skill_bundle(r, fb)
        def generate_monster(self, r, fb=""): return self.m.generate_monster_bundle(r, fb)
        def generate_quest(self, r, fb=""): return self.m.generate_quest_bundle(r, fb)
    class _MockCritic:
        def review(self, d): return mock_provider.review(d, "unknown")
    generator = _MockGen(mock_provider)
    critic = _MockCritic()
    print("[ConfigForge] Using MockLLMProvider (MVP mode)")

orchestrator = Orchestrator(generator, critic, seed_store, rule_engine, trace_store, result_store, event_bus=event_bus)
eval_runner = EvalRunner(orchestrator)


# ── Models ────────────────────────────────────────────
class GenerateRequest(BaseModel):
    job_type: str = Field(..., pattern="^(skill|monster|quest)$")
    requirement: str = Field(..., min_length=3, max_length=500)
    enable_critic: bool = True


# ═══════════════ API Routes ═══════════════════════════

@app.get("/api/status")
async def status():
    return {
        "mode": "live" if gen_provider else "mock",
        "generator": type(gen_provider).__name__ if gen_provider else "MockLLMProvider",
        "critic": type(crit_provider).__name__ if crit_provider else "MockLLMProvider",
        "ark_api_key_set": _ARK,
        "deepseek_api_key_set": _DS,
    }

@app.post("/api/generate")
async def generate(req: GenerateRequest):
    """Start generation in background, return job_id immediately for SSE streaming."""
    try:
        import uuid
        # Pre-allocate IDs so SSE can start listening immediately
        trace_id = trace_store.create(req.job_type, req.requirement)
        job_id = trace_id.replace("trace_", "j_")

        # Push initial start event
        event_bus.push(job_id, "start", {
            "job_type": req.job_type, "requirement": req.requirement, "job_id": job_id
        })

        # Run generation in background thread
        def _run_orch():
            try:
                if req.job_type == "skill":
                    result = orchestrator.generate_skill(req.requirement, req.enable_critic,
                                                         job_id=job_id, trace_id=trace_id)
                elif req.job_type == "monster":
                    result = orchestrator.generate_monster(req.requirement, req.enable_critic,
                                                          job_id=job_id, trace_id=trace_id)
                else:
                    result = orchestrator.generate_quest(req.requirement, req.enable_critic,
                                                         job_id=job_id, trace_id=trace_id)
                # Export CSV after generation
                result["csv_files"] = [str(p) for p in _export(result["bundle"], req.job_type)]
                event_bus.mark_done(job_id, result)
            except Exception as e:
                import traceback; traceback.print_exc()
                event_bus.mark_error(job_id, str(e))

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _run_orch)

        return JSONResponse({"job_id": job_id, "trace_id": trace_id, "status": "started"})
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

@app.get("/api/tables")
async def list_tables():
    return csv_exporter.list_tables()

@app.get("/api/tables/{table_name}")
async def get_table(table_name: str):
    return csv_exporter.read_table(table_name)

@app.post("/api/tables/validate-all")
async def validate_all():
    return {"status": "ok"}

@app.post("/api/eval/run")
async def run_eval():
    return eval_runner.run_ablation(eval_runner.load_samples())

@app.post("/api/export")
async def export_result(trace_id: str = Query(...)):
    t = trace_store.get(trace_id)
    if t is None: raise HTTPException(404, "Trace not found")
    return {"status": "ok", "trace": t}

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


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
