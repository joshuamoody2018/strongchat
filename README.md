## Contributing & Licensing

This project is licensed under the **CC BY-NC 4.0** license. Commercial use requires explicit approval.

By contributing to this repository, you agree to the terms of our [Contributor License Agreement (CLA)](CLA.md).

---

# StrongChat

StrongChat is a Bible verse retrieval and answer synthesis system built around a multi-step LLM pipeline. It disambiguates a user's question, generates Hypothetical Document Embeddings (HyDE), retrieves relevant verses from English and original-language biblical corpora, and synthesizes a grounded answer.

## Features

- **Intent disambiguation**: clarifies ambiguous or shorthand biblical questions before retrieval.
- **HyDE generation**: produces hypothetical answer passages to improve semantic retrieval.
- **Cross-language retrieval**: English semantic search with original-language grounding.
- **Structured LLM outputs**: JSON-schema validation and recorded message history for auditability.
- **Modular service architecture**: intent, HyDE, embedding, vector store, and retrieval services.

## Directory Layout

```
architecture/     System design and architecture documentation
src/              Source code and service implementations
  services/       LLM framework, pipeline services, SQLite storage
  config/         JSON schemas, prompt templates, model configs
scripts/          Setup, utility, and pipeline scripts
  setup_environment.sh    Bootstrap Python environment and dependencies
  ingest_corpus.py        Ingest Bible corpus into ChromaDB
  create_new_database.py  Create the SQLite schema and seed ref_message_types
tests/            Test suites
  system/         System/integration tests
  scripts/        Script-level tests
data/             SQLite database and generated artifacts
```

## Prerequisites

- Python 3.12 or newer
- Ubuntu/Debian-based environment
- Git

## Installation

Run the committed setup script to create a virtual environment and install dependencies:

```bash
bash scripts/setup_environment.sh
```

Then create a `.env` file in the project root with at least your OpenRouter API key:

```bash
OPENROUTER_API_KEY="sk-or-..."
```

## Usage

Run the full pipeline against a question:

```bash
set -a; . ./.env; set +a
.venv/bin/python src/main.py "your question"
```

## Testing

Run the script-style tests directly:

```bash
.venv/bin/python tests/scripts/<file>.py
```

For example:

```bash
.venv/bin/python tests/scripts/test_intent_service.py
.venv/bin/python tests/scripts/test_pipeline_offline.py
```

Live system tests need an `OPENROUTER_API_KEY` in your environment:

```bash
set -a; . ./.env; set +a
.venv/bin/python tests/system/<file>.py
```

For example:

```bash
.venv/bin/python tests/system/test_intent_generation.py
.venv/bin/python tests/system/test_hyde_generation.py
.venv/bin/python tests/system/test_pipeline_e2e.py
```

Top-level tests in `tests/` are runnable with `unittest`:

```bash
.venv/bin/python -m unittest tests.test_integration
```

## Documentation

- `architecture/high-level.md` — 13-step pipeline overview
- `architecture/reference.md` — agent workflow and integration
- `architecture/implementation-status.md` — current progress tracking
- `todo.md` — implementation backlog and next steps
