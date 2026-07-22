# EES Natural Language Search

## Overview

An Azure-hosted API that turns plain-English queries into ranked educational dataset recommendations from the DfE's Explore Educational Statistics (EES) platform. A user asks *"pupil attendance for London secondary schools 2023"*; the system returns relevant datasets, each with the specific filters and indicators worth selecting.

It combines **Azure Cognitive Search** (hybrid BM25 + vector) with a multi-stage **Azure OpenAI** pipeline (GPT-4.1-mini by default). Results stream back to the client as **Server-Sent Events (SSE)** so partial results appear progressively.

**Stack:** Python - Azure Functions - FastAPI (mounted as ASGI) - Azure Cognitive Search - Azure OpenAI

---

## Project Structure
```
ees-natural-language-search/
├── function_app.py                  # Azure Functions entry point - mounts FastAPI via an ASGI proxy
├── host.json                        # Functions runtime config
├── requirements.txt                 
├── local.settings.example.json      # Template for local env vars
├── azure-pipelines.yml              # CI/CD
│
├── core/
│   ├── app.py                       # Builds the FastAPI app, registers the main routes
|   └── config.py                    # Loads local.settings.json into os.environ (local only)
| 
├── common/                          # All business logic
│   ├── workflow.py                  # Pipeline orchestrator
│   ├── retrieve_datasets.py         # Thin wrapper over multi_index_search
│   ├── search_client.py             # Azure Search clients + embeddings + hybrid search
│   ├── openai_client.py             # generate_answer() - Azure OpenAI chat wrapper
│   ├── reranker.py                  # LLM agent: rerank + extract query requirements
│   ├── filter_selection.py          # LLM agent: pick relevant filter values per dataset
│   ├── indicator_selection.py       # LLM agent: pick relevant indicators per dataset
│   ├── data_utils.py                # Filter retrieval, response merge, score conversion
│   └── geography_levels_utils.py    # Fuzzy location matching + geographic-level grouping
│
└── routes/
    ├── natural_language_search_function.py  # POST /api/natural_language_search_function (SSE)
    ├── healthcheck.py                       # GET /health_check
    └── vectorizer_middleware.py             # POST /api/vectorizer_middleware (embeddings for indexers)
```

---

## How a request flows
 1. `function_app.py` proxies the main API routes into the FastAPI ASGI app, while the health check is registered directly as an Azure Functions route. Streaming responses are forwarded through an `asyncio.Queue`.
 2. The route handler in `natural_language_search_function.py` calls `run_workflow(...)`, which is an **async generator** which yields plain dicts; the route serialises each one as `data: <json>\n\n` and is also where exceptions become a `{"error": ...}` SSE event.
 3. `common/workflow.py` runs the pipeline stage by stage, yielding after each.

 ```
 run_workflow(user_query, publication)
   │
   ├── 1. retrieve_relevant_datasets -> multi_index_search       (search_client.py -> Azure Search)
   │        Hybrid BM25 + vector search over the Filter index; dataset docs fetched by id.
   │        Also returns grouped filter labels per dataset for downstream narrowing.
   │        yields {stage:"retrieved datasets", data:{datasets:[...]}}
   │
   ├── 2. run_reranking_agent                                    (reranker.py -> Azure OpenAI)
   │        LLM shortlists datasets and extracts queryRequirements (filters, geography, timePeriod).
   │        Workflow augments the shortlisted datasets dataset metadata and relevanceScore obtained at the previous step.
   │        yields {stage:"reranker complete", data:{confidence, datasets:[...], query_requirements, token_usage, cost}}
   │
   ├── 3. Build reranked dataset map with subject metadata       (workflow.py + EES Data API subject meta)
   │        Build reranked_datasets_by_id from reranker datasets + subject meta
   │
   ├── 4. get_geographical_matches                               (geography_levels_utils.py)
   │        Fuzzy-match mentioned locations, group by allowed geographic levels per dataset
   │
   ├── 5. retrieve_and_transform_filter_data                     (data_utils.py -> Azure Search filter index)
   │        Fetch full filter values for shortlisted datasets, flattened for the LLM
   │
   ├── 6. filter + indicator + time period agents in parallel    (asyncio.gather -> Azure OpenAI)
   │        Per-dataset relevance decisions for each filter value/indicator
   │
   └── 7. combine_final_dataset_responses                        (data_utils.py)
            Merge filters + indicators + geography + a relevance reason per dataset
            yields {stage:"pipeline complete", data:{datasets:[...], token_usage:<int>}}
```

### SSE events

| Stage | `data` payload |
|---|---|
|`starting pipeline` | *(none)* |
|`retrieved datasets` | `{datasets:[...]}` |
|`reranker complete` | `{confidence, datasets:[...], query_requirements, token_usage, cost}` |
|`pipeline complete` | `{datasets:[{fileId, filters:[{id, label}], indicators:[{id, label}], timePeriod, geographicLevels, relevanceReason}], token_usage, cost}` |
| `error` *(from route, on exception)* | `{error: <message>}` |

---

## Components in depth

### `workflow.py` - orchestrator
The most important file. Accumulates `token_usage` across all LLM calls and `yield`s after each stage. It builds a `reranked_datasets_by_id` map with dataset metadata plus subject meta and passes that through geography/filter/indicator/time period stages. If the reranker shortlists nothing, downstream stages simply produce empty results.

### search_client.py - Azure Search and embeddings
- Module-level `filter_client` and `dataset_client` are created at import. Credential is `AzureKeyCredential` if `AZURE_SEARCH_KEY` is set, else `DefaultAzureCredential()`.
- `get_embeddings(input_text, model_name, dimensions=1536)` -> `**returns (embeddings, total_tokens)**`. Lists are batched in groups of 15 with up to 2 attempts and exponential backoff on transient errors.
- `hybrid_search(...)` runs BM25 + vector search against the filter index (`top=10`, vector `weight=0.5`), optionally filtered by `publicationTitle` and `latestData`.
- `multi_index_search(...)` groups filter hits by `fileId`, keeps the `max @search.score` per dataset, then fetches each dataset doc via `dataset_client.get_document(...)`. Returns `(query, datasets, max_scores, grouped_filters)`.

### `reranker.py` - rerank + requirement extraction
Sends the query plus trimmed dataset metadata `(fileId, title, content, filters, timePeriodRange)` to the LLM. Returns a typed `RerankingAgentResult` used downstream:
`grouped_filters`, `grouped_indicators`, `reranker_response`, and `total_tokens_used`. The LLM output schema remains:
`queryRequirements{filters[], geography[], timePeriod}`, `shortlistedDatasets[{fileId, title, relevanceReason, relevantFilters[]}]`, `confidence`.

### `filter_selection.py` / `indicator_selection.py` / `time_period_selection.py` - selection agents
One LLM call per reranked dataset, all gathered concurrently. Each returns a list of raw JSON strings plus a token total.
- Filter output: `{"<fileId>": { "filterItems": { "<filter label>|||<filter item group ID>|||<filter item label>": {relevant(Yes/No), reasoning} } } }`
- Indicator output: `{"<fileId>" { "<indicators>": {relevant(Yes/No), reasoning} } }`

### `data_utils.py`
- `retrieve_and_transform_filter_data(...)` pulls full filter values from the filter index and flattens them per dataset.
- `combine_final_dataset_responses(...)` keeps only values marked `relevant: true`, resolves ids from subject meta, attaches `geographicLevels` and a `relevanceReason`, and flattens to a list of `{fileId, ...}`.
- `rrf_to_percentage(score)` scales an RRF score to 0-100

### `geography_levels_utils.py`
- `hybrid_scorer` only accepts a perfect `token_set_ratio` (100) when >= 2 tokens overlap and the candidate isn't much shorter than they query; otherwise falls back to `WRatio`

### `openai_client.py`
`generate_answer(...)` calls Azure OpenAI chat completions with `temperature=0, top_p=1, seed=42` (deterministic-ish) and returns the full response object

---

## API Reference

### `GET /health_check`
Returns `{ message: "API working" }`.

### `POST /api/vectorizer_middleware`
Generates embeddings for Azure Search skillset/indexer integration. Uses `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` and `EMBEDDING_DIMENSIONS` (default 1536).
```json
//request
{ "values": [ { "recordId": "1", "data": { "text": "text to embed" } } ] }
//response
{ "values": [ { "recordId": "1", "data": { "embedding": [0.12, ...] } } ] }
```

### `POST /api/natural_language_search_function`

Replace `publicationId` with the ID of the publication you want to search.

```json
{
  "userQuery": "pupil attendance in London secondary schools in 2023",
  "publicationId": "00000000-0000-0000-0000-000000000000"
}
```
The response is returned as `text/event-stream`.

---

## Local Development

**Prerequisites:** Python (CI pipeline targets **3.14**), [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local), and access to the Azure Search  / OpneAI / Storage resources.

```powershell
pip install -r requirements.txt
Copy-Item local.settings.example.json local.settings.json  # then fill in values
func start                                                 # serves on http://localhost:7071
```

Test:

Replace `publicationId` with the ID of the publication you want to search.

```powershell
curl -X POST https://localhost:7071/api/natural_language_search_function `
    -H "Content-Type: application/json" `
    -d '{"userQuery": "Show me the percentage of pupils reported as on holiday in the last 4 weeks", "publicationId": "00000000-0000-0000-0000-000000000000"}'
```

`core/config.py` loads `local.settings.json` into environment locally if you plan on running it with uvicorn

---