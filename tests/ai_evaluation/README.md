# AI Evaluation Framework

This directory contains a deterministic regression‑testing framework for the AI features in the FreightPulse codebase.

## Structure
```
tests/ai_evaluation/
├── fixtures/
│   ├── carrier_summarizer/
│   │   ├── carrier_001.json
│   │   └── carrier_002.json
│   ├── rate_outlook/
│   │   ├── rate_outlook_001.json
│   │   └── rate_outlook_002.json
│   └── route_brief/
│       ├── route_brief_001.json
│       └── route_brief_002.json
├── evaluators/
│   ├── __init__.py
│   ├── base.py
│   ├── carrier.py
│   ├── rate_outlook.py
│   └── route_brief.py
├── fake_ai_client.py
├── test_ai_evaluation.py
└── README.md
```

* **fixtures/** – JSON files describing realistic inputs and the expected deterministic outputs.  Each fixture contains an `id`, `version`, `description`, `input`, `expected_output`, and `criteria`.
* **evaluators/** – Helper modules that load a fixture, invoke the real AI component with a deterministic `FakeFreightPulseAIClient`, validate the Pydantic schema and run domain‑specific criteria.
* **fake_ai_client.py** – Minimal stand‑in for `FreightPulseAIClient` that returns the `expected_output` from a fixture without contacting OpenAI.
* **test_ai_evaluation.py** – Pytest entry point that runs the evaluators over all fixtures and also includes a regression‑detection sanity test.
* **README.md** – Documentation for contributors (you are reading it!).

## How to Run
```bash
# Deterministic evaluation (runs offline)
PYTHONPATH=. .venv/bin/pytest -q tests/ai_evaluation

# Full test suite (includes existing tests)
PYTHONPATH=. .venv/bin/pytest -q
```

## Adding a New Fixture
1. Choose the feature directory (`carrier_summarizer`, `rate_outlook`, or `route_brief`).
2. Create a JSON file following the schema demonstrated in the existing fixtures.
3. Increment the `version` field whenever the expected output changes.
4. Commit the new file – the evaluation suite will automatically pick it up.

## Live LLM Mode (optional)
If you have OpenAI credentials and want to see how the real model behaves, run:
```bash
PYTHONPATH=. .venv/bin/pytest -q -m ai_live
```
Live tests are **not** part of the default CI and will never cause a CI failure.

---
**Note:** This framework does **not** modify any production code. It only adds test‑only utilities under `tests/ai_evaluation/`.
