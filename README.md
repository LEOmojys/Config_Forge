# ConfigForge MVP

Game configuration generation agent workbench. Input natural language requirements → output structured JSON + CSV config tables.

## Quick Start

Windows one-click startup:

```bat
start-dev.bat
```

The script checks backend/frontend dependencies, starts FastAPI and Vite in separate PowerShell windows, then opens http://localhost:3000.

First-time or forced dependency setup:

```powershell
.\start-dev.ps1 -Install
```

Use a specific Python/conda interpreter:

```powershell
.\start-dev.ps1 -PythonPath "C:\path\to\python.exe"
```

Manual startup:

```bash
# Backend
cd configforge
pip install -r backend/requirements.txt
python -m uvicorn backend.api.app:app --host 0.0.0.0 --port 8000 --reload

# Frontend
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

## Doubao Coding Plan Setup

Use the Coding Plan endpoint for Doubao generation:

```env
ARK_CODING_API_KEY=your_volcengine_ark_api_key
ARK_CODING_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
ARK_CODING_MODEL=ark-code-latest
```

The backend also accepts `DOUBAO_API_KEY` or legacy `ARK_API_KEY`, but `ARK_CODING_API_KEY` is preferred. Do not use old online-inference model IDs such as `doubao-pro-32k-240615` for Coding Plan requests.

## Supported Generation Types

| Type | Output | CSV Tables |
|---|---|---|
| Skill | `SkillBundle` | `skills.csv` |
| Monster | `MonsterBundle` | `monster_templates.csv` + `monster_configs.csv` + `monster_skills.csv` + `monster_loot.csv` |
| Quest | `QuestBundle` | `quest_templates.csv` + `quest_objectives.csv` |

## Pipeline

```
Requirement → Generator (Mock/LLM) → Pydantic Validate → RuleEngine (10 rules) → Critic Review → Export (JSON + CSV)
```

Up to 3 revision rounds. Exceeding returns `need_human` status.

## API Routes

| Method | Path | Description |
|---|---|---|
| POST | `/api/generate` | Generate config from requirement |
| GET | `/api/traces` | List generation traces |
| GET | `/api/traces/{id}` | Get trace detail |
| GET | `/api/tables` | List CSV tables |
| GET | `/api/tables/{name}` | Read CSV table |
| POST | `/api/eval/run` | Run ablation study (G0-G3) |
| GET | `/api/seed/context` | Get available IDs for prompt |

## Evaluation

20-sample eval set. 4 ablation groups:

- G0: Pure LLM output (baseline)
- G1: + Pydantic validation
- G2: + RuleEngine (10 rules)
- G3: + Critic review (full pipeline)

## Technology

- **Backend**: Python 3.11+, FastAPI, Pydantic v2
- **Frontend**: React 18, TypeScript, Vite, Ant Design 5
- **Mock Provider**: Deterministic template-based generation (no API key needed for MVP)

## Data Sources

Seed data (elements, items, skills, templates) is original content inspired by public anime-style game configuration table structures (e.g., Genshin Impact's `ExcelBinOutput/MonsterExcelConfigData`, Arknights' `enemy_database.json`, Honkai: Star Rail's `AvatarConfig`). No actual commercial game data is used.

## MVP Scope

What's included:
- 3 generation types (Skill, Monster, Quest)
- 9 CSV output tables with proper foreign-key relationships
- 10 business rules with structured violation reports
- Full trace replay for all generation rounds
- Ablation study evaluation
- Web UI with 4 pages

What's deferred to v2:
- Real LLM API integration (Doubao/DeepSeek)
- Multi-language text_map
- Character/equipment/relic systems
- Complex table editing
- Langfuse observability
- Unity/Unreal integration
