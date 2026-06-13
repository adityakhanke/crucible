# 🔥 CRUCIBLE

**A Local Autonomous Research Engine with Dialectical Reasoning**

*Five models. Five minds. One GPU. Zero cloud dependencies.*

CRUCIBLE implements a 5-phase dialectical research pipeline that extracts, maps, attacks, synthesizes, and audits scientific claims — using architecturally diverse language models that never review their own output.

## Architecture

```
ArXiv/Papers → Docling (PDF→Markdown) → SCOUT (ingest)
                                            ↓
                               ┌─── DIALECTIC CYCLE ───┐
                               │                        │
                               │  Phase 1: SURVEY       │  ← DeepSeek R1 14B
                               │  Phase 2: MAP          │  ← Ministral 3 14B
                               │  Phase 3: ATTACK       │  ← Phi-4-Reasoning 14.7B
                               │  Phase 4: SYNTHESIZE   │  ← Gemma 3 12B
                               │  Phase 5: META-REVIEW  │  ← Qwen 3.5 4B/9B
                               │                        │
                               └────────────────────────┘
                                            ↓
                            Frontier Map + Research Journal
                                            ↓
                                    REVIEW (Human)
```

## Requirements

- **GPU:** 16 GB VRAM (single GPU)
- **RAM:** 32 GB minimum, 64 GB recommended (for tmpfs model caching)
- **Storage:** 50+ GB for models, papers, graph data
- **OS:** Linux (tested on Ubuntu 22.04+)

## Install

```bash
# 1. Create environment
python -m venv .venv && source .venv/bin/activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Download models (edit config/models.yaml with your paths first)
python -m crucible.models.download

# 4. Start services (Neo4j + Qdrant)
docker compose up -d

# 5. Initialize the knowledge graph schema
python -m crucible init-db

# 6. Run Genesis Protocol with seed papers
python -m crucible genesis --seeds 2401.00001 2403.12345

# 7. Run your first DIALECTIC cycle
python -m crucible dialectic
```

## Usage

```bash
# Nightly paper ingestion
python -m crucible scout

# Full dialectical analysis cycle
python -m crucible dialectic

# Review research briefs interactively
python -m crucible review

# Check system status
python -m crucible status

# Export frontier map
python -m crucible export-map --format json
```

## Configuration

All configuration lives in `config/`:
- `settings.yaml` — paths, thresholds, scheduling
- `models.yaml` — model roster, engines, VRAM budgets
- `tools.yaml` — external API tools and permissions

## Project Structure

```
crucible/
├── config/                 # All YAML configuration
├── crucible/               # Main package
│   ├── cli.py              # CLI entry point
│   ├── engine/             # Dialectical engine + scheduler
│   │   └── phases/         # 5 phase implementations
│   ├── models/             # Model manager + inference engines
│   ├── graph/              # Neo4j knowledge graph + entity resolution
│   ├── memory/             # Mem0 semantic memory
│   ├── parsing/            # Docling PDF pipeline
│   ├── tools/              # Tool router + API clients
│   ├── context/            # Phase-aware context builder
│   ├── journal/            # Research journal writer
│   ├── frontier/           # Frontier map manager
│   ├── genesis/            # Day-0 bootstrapping
│   └── schemas/            # Pydantic data models
├── prompts/                # System prompts per phase
├── scripts/                # Cron scripts
└── data/                   # Runtime data (papers, checkpoints, outputs)
```

## Hardware Constraint as Design Principle

The 16 GB VRAM limit is not a limitation — it's a forcing function. Only one model loads at a time, which mechanically enforces that no model ever reviews its own output. The sequential swap protocol (~2-3s from tmpfs, ~25-30s from NVMe) is the cost of genuine cognitive diversity.

## License

MIT
