# EES Natural Language Search

## Overview

An Azure-hosted API that turns plain-Englisha querise into ranked educational dataset recommendations from the DfE's Explore Educational Statistics (EES) platform. A user asks *"pupil attendance for London secondary schools 2023"*; the system returns relevant datasets, each with the specific filters and indicators worth selecting.

It combines **Azure Cognitive Search** (hybrid BM25 + vector) with a multi-stage **Azure OpenAI** pipeline (GPT-4.1-mini by default). Results stream back to the client as **Server-Sent Events (SSE)** so partial results appear progressively.

**Stack** Python - Azure Functions - FastAPI (mounted as ASGI) - Azure Cognitive Search - Azure OpenAI

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

