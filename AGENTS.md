# AGENTS.md

Guidance for coding agents working in this repository. `README.md` documents the request flow, each SSE
event payload, every module, and how to run, test and lint the project. **Read it before changing pipeline
behaviour.** This file only covers what isn't in there.

## Architecture notes

- **Adding a pipeline stage** means adding a `yield` in `common/workflow.py` and an event model in
  `schemas/responses/event_responses.py`.
- **Datasets are keyed by `file_id` throughout.** Agent responses are paired with the file id of the
  request that produced them. The model is never asked to echo an id back.
- **UUIDs are deliberately kept out of prompts.** Filter selections go through reference numbers (see
  `build_filter_item_candidates`) for this reason.
- **Degrade rather than raise.** `parse_llm_response` logs and returns `None` on malformed LLM output, and
  callers drop that dataset's results for that agent. Keep that pattern for new agents.
- **Importing `common/search_client.py` without `AZURE_SEARCH_*` env vars raises `KeyError`**, because it
  builds its `SearchClient`s at import time. This applies transitively (e.g. via `common.workflow`), so test
  pure helpers or patch around the import.

## Conventions

- **Schemas** extend `CamelModel` or `StrictCamelModel` from `schemas/shared/base_models.py`: snake_case
  fields with camelCase aliases, so dump with `model_dump(by_alias=True)` for anything leaving the API.
- Where an LLM response shape (`schemas/llm/`) and a public response shape (`schemas/responses/`) currently
  coincide, they are still declared separately (with a docstring saying so) so they can diverge later. Keep
  that separation.
- **Prompts** are module-level string constants in each agent file (`llm_*_sys_prompt` /
  `llm_*_user_prompt`), with untrusted input wrapped in `<user_query>` / `<query_requirements>` tags and a
  `# Security` section telling the model to treat tagged content as data. New prompts should carry the same
  section.
- **Logging**: `logger = logging.getLogger(__name__)` per module, `%s` lazy formatting.
- **New top-level packages** need adding to the logging config in (`core/logging_config.py`) to be visible,
  and to `artifactContents` in `azure-pipelines.yml` to be deployed.
- **Tests**: use `build_dataset` from `tests/conftest.py` to construct a `DatasetWithSubjectMeta` with
  placeholder metadata, so a test only specifies the subject meta it cares about. JSON fixtures go in a
  `fixtures/` directory beside the tests that use them, where `load_json_fixture` finds them.
- **Commits** follow `EES-<ticket number> <Description> (#<PR number>)`. The ` (#<PR number>)` suffix is
  added by GitHub when a PR's commits are squashed on merging.

## Regression tests

`tools/regression_tests/` imports the service's `schemas/responses` models, so a change to an SSE event model
may need a matching change there. Never run it against a deployed environment without being asked, as every
query costs Azure OpenAI tokens. Use `--replay <report>` instead.

It has its own `requirements.txt` and venv, separate from the service's, listing only the third-party
dependencies of the `schemas` and `clients` modules it imports. A new third-party import in those modules,
or a new service module imported by the tool, may need a matching entry adding there.
