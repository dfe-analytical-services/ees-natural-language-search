# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

An Azure Functions + FastAPI API that turns a plain-English query into ranked EES dataset
recommendations, each with the filters, indicators and time period worth selecting. It combines
Azure Cognitive Search (hybrid BM25 + vector) with a multi-stage Azure OpenAI pipeline, and streams
results back as Server-Sent Events.

`README.md` documents the request flow, each SSE event payload and every module in depth. **Read it
before changing pipeline behaviour** — this file only covers what isn't in there.

## Commands

```bash
pip install -r requirements-test.txt   # installs requirements.txt too
pytest                                 # pytest.ini supplies all args (coverage + junit xml)
pytest tests/common/test_location_utils.py::test_name   # single test
func start                             # run locally on http://localhost:7071
```

CI (`azure-pipelines.yml`) targets **Python 3.14** and runs `pytest` only — there is no linter or
formatter configured, so match the style of surrounding code rather than reformatting.

Local config: copy `local.settings.example.json` to `local.settings.json` and fill it in.
`core/config.py` loads it into `os.environ` when not running in Azure (detected via
`WEBSITE_INSTANCE_ID`), so uvicorn works too.

## Architecture notes

- **`common/workflow.py` is the orchestrator.** It's an async generator that `yield`s a plain dict
  per stage; `routes/natural_language_search_function.py` serialises each as `data: <json>\n\n` and
  is the only place exceptions become an `{"error": ...}` SSE event. Adding a stage means adding a
  yield here and an event model in `schemas/responses/event_responses.py`.
- **Datasets are keyed by `file_id` throughout.** Every per-dataset map (`reranked_datasets_by_file_id`,
  `filter_item_candidates_by_file_id`, the agent response lists, location results) uses the same key.
  Agent responses are paired with the file id of the request that produced them — the model is never
  asked to echo an id back.
- **Filter selections are keyed by reference number, not id.** `build_filter_item_candidates` numbers
  the candidate filter items and the prompt lists them as `<n>. <label>`; the agent returns those
  numbers, and `build_final_dataset_response` resolves them back through the same candidate map. UUIDs
  are deliberately kept out of prompts. `filterItemLabel` is echoed back only so a mis-reference can
  be detected and logged.
- **Everything the model returns is validated, never trusted.** Indicator and time period selections
  are checked against subject meta; anything unresolvable becomes a `DatasetValidationError` and
  clears `isValidForTableGeneration`. Results that are merely broader than the query (fallback
  selections) become a `DatasetValidationWarning` instead, which does *not* invalidate the result.
  Codes live in `schemas/responses/final_dataset_response.py`.
- **Degrade rather than raise.** `parse_llm_response` logs and returns `None` on malformed LLM output,
  and callers drop that dataset's results for that agent. Keep that pattern for new agents.
- **`common/search_client.py` builds its `SearchClient`s at import time** from `AZURE_SEARCH_*` env
  vars, so importing it (directly or transitively, e.g. via `common.workflow`) without those set
  raises `KeyError`. This is why the existing tests only cover modules with no search client in their
  import chain — pick pure helpers to test, or inject/patch around the import.

## Conventions

- **Schemas** live in `schemas/`, grouped by the boundary they describe: `ees_data_api/`, `llm/`
  (the shape each agent is prompted to return), `domain/` (internal DTOs), `responses/` (SSE payloads),
  `shared/` (bases). Models extend `CamelModel` or `StrictCamelModel` from
  `schemas/shared/base_models.py` — snake_case fields, camelCase aliases, so dump with
  `model_dump(by_alias=True)` for anything leaving the API.
- Where an LLM response shape and a public response shape currently coincide they are still declared
  separately (with a docstring saying so) so they can diverge later. Keep that separation.
- **Prompts** are module-level string constants in each agent file (`llm_*_sys_prompt` /
  `llm_*_user_prompt`), with untrusted input wrapped in `<user_query>` / `<query_requirements>` tags
  and a `# Security` section telling the model to treat tagged content as data. New prompts should
  carry the same section.
- **Logging**: `logger = logging.getLogger(__name__)` per module, `%s` lazy formatting. Only the
  `clients`, `common`, `core` and `routes` loggers are at INFO (`core/logging_config.py`); root is
  WARNING, so a new top-level package needs adding there to be visible.
- **Tests** mirror the package they cover (`tests/common/test_x.py` ↔ `common/x.py`). Shared fixtures
  are in `tests/conftest.py` — use `build_dataset` to construct a `DatasetWithSubjectMeta` with
  placeholder metadata so a test only specifies the subject meta it cares about, and
  `load_json_fixture` for sample EES Data API payloads in `tests/fixtures/`.
- **Commits** follow `EES-<ticket number> <Description> (#<PR number>)`.

## Out of scope for CI

`tools/data-sync/` is a manually-run notebook that builds the Azure AI Search index documents. It has
its own README and requirements, and is excluded from the pipeline triggers.
