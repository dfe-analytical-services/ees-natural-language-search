# EES Natural Language Search

## Overview

An Azure-hosted API that turns plain-Englisha querise into ranked educational dataset recommendations from the DfE's Explore Educational Statistics (EES) platform. A user asks *"pupil attendance for London secondary schools 2023"*; the system returns relevant datasets, each with the specific filters and indicators worth selecting.

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
│   ├── app.py                       # Builds the FastAPI app, registers routes
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
│   └── geography_level_utils.py     # Fuzzay location matching + geographic-level grouping
│
├── routes/
│   ├── natural_language_search_function.py  # POST /api/natural_language_search_function (SSE)
│   ├── healthcheck.py                       # GET /api/health_check
│   └── vectorizer_middleware.py             # POST /api/vectorizer_middleware (embeddings for indexers)
```

---

## How a request flows
 1. `function_app.py` receives every HTTP routea and proxies it into the FastAPI ASGI app, streaming the response body back through an `asyncio.Queue`.
 2. The route handler in `natural_language_search_function.py` calls `run_workflow(...)`, whic is an **async generator** which yields plain dicts; the route serialises each one as `data: <json>\n\n` and is also where exceptions become a `{"error": ...}` SSE event.
 3. `common/workflow.py` runs the pipeline stage by stage, yielding after each.

 ```
 run_workflow(user_query, publication)
   │
   ├── 1. retrieve_datasets -> multi_index_search       (search_client.py -> Azure Search)
   │        Hybrid BM25 + vector search over the Filter index; dataset docs fetchewd by id.
   │        yields {stage:"retrieved datasets", data:{datasets:[{title, relevanceScore, rawRelevanceScore}]}}
   │
   ├── 2. run_reranking_agent                           (reranker.py -> Azure OpenAI)
   │        LLM shortlist datasets and extracts queryRequirements (filters, geography, timePeriod).
   │        yields {stage:"reranker complete, data:<reranker JSON>}
   │
   ├── 3. geography_matching                            (geography_levels_utils.py -> Blob Storage)
   │        Fuzzy-match mentioned locations, group by allowed geographic levels per dataset
   │
   ├── 4. retrieve_and_transform_filter_data            (data_utils.py -> Azure Search filter index)
   │        Fetch full filter values for shortlisted datasets, flattened for the LLM
   │
   ├── 5. filter + indicator agents in parallel         (asyncio.gather -> Azure OpenAI)
   │        Per-dataset relevance decisions for each filter value/indicator
   │
   └── 6. combine_responses                             (data_utils.py)
            Merge filters + indicators + geography + an aiSummary per dataset
            yields {stage:"pipeline complete", data:{datasets:[...], token_usage:<int>}}
```
