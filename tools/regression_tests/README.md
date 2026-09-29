# Regression Tests (Manual Process)

A script that runs a set of gold standard queries against the natural language search API, and writes a
report of how each query was executed, e.g. its status, duration, token usage, cost and dataset validation
issues. It's used to measure the accuracy and consistency of the service, and to catch regressions before
releasing changes.

The API is tested as a black box over HTTP, so it can be run against a deployed environment without any
Azure credentials.

> [!IMPORTANT]
> Every query calls Azure OpenAI and costs money, so this is run manually and **not** as part of the CI
> pipeline. See [Cost](#cost) before running a large number of queries or iterations.

Comparing results against the expected results in the gold standard file is not implemented yet. The
expected results are validated, but not scored.

## Requirements

- Python (the CI pipeline targets **3.14**)
- Network access to the environment's function app

Install the dependencies from the **repository root**:

```bash
pip install -r tools/regression_tests/requirements.txt
```

## Environments

The environments are configured in `environments.json`, keyed by the name given to `--env`:

```json
{
  "dev": { "baseUrl": "https://<function app host>" }
}
```

The `local` environment is for running against `func start` on http://localhost:7071.

## Usage

Run from the **repository root**, as the script imports the service's response schemas from `schemas/`:

```bash
# Check the gold standard queries file, without running any queries
python -m tools.regression_tests --validate

# Run every query once against dev
python -m tools.regression_tests --env dev

# Run two queries three times each, stopping once the cost reaches 0.50
python -m tools.regression_tests --env dev --query attendance-holiday-last-4-weeks --query absence-by-school-type --iterations 3 --max-cost 0.5

# Run the queries tagged 'attendance'
python -m tools.regression_tests --env dev --tag attendance
```

| Option | Default | Description |
|---|---|---|
| `--env` | | The environment to run against, from `environments.json`. Required unless `--validate` is given. |
| `--input` | `gold_standard/queries.json` | The gold standard queries file. |
| `--query` | | Only run the query with this id. Can be repeated. |
| `--tag` | | Only run queries with this tag. Can be repeated. A query is run if it matches any `--query` or `--tag`. |
| `--iterations` | `1` | How many times to run each query, to measure consistency. Iterations run one after another. |
| `--concurrency` | `2` | How many queries to run at once. Keep it low, as higher concurrency skews durations and risks Azure OpenAI rate limiting. |
| `--timeout` | `180` | Seconds to wait for each query to complete. |
| `--max-cost` | | Stops starting new queries once the run's cost reaches this. |
| `--out` | `reports/` | The directory to write the report to. It is ignored by git. |
| `--validate` | | Only validate the gold standard queries file. |

The exit code is `0` when every selected query completed the pipeline in every iteration, `1` when any
didn't, or the health check failed, and `2` for invalid arguments or an invalid gold standard file.

## Gold standard queries file

`gold_standard/queries.json` currently contains placeholder queries showing the format. Each query has:

| Field | Required | Description |
|---|---|---|
| `id` | Yes | A unique id, used to select the query with `--query` and to identify it in the report. |
| `description` | | Why the query is in the gold standard. |
| `userQuery` | Yes | The query sent to the API. |
| `publicationId` | Yes | The publication sent to the API. |
| `tags` | | Used to select queries with `--tag`. |
| `expected` | | The expected results. Leave unset to only report on how the query was executed. |

`expected` can have:

- `minDatasets` - the minimum number of datasets the query should return.
- `datasets` - the datasets the query should return. Each is identified by its `dataSetFileId` and can have:
  - `title` - for readability of the file only, not compared.
  - `maxRank` - the lowest acceptable position of the dataset in the results, where 1 is the first result.
  - `required` - whether the query fails when the dataset is missing. Defaults to `true`. Set it to `false`
    for a dataset that is acceptable, but not required.
  - `filters` - the expected filter item labels, keyed by filter label. Use `"*"` instead of a list of labels
    if any selection is acceptable for that filter.
  - `indicators` - the expected indicator labels.
  - `timePeriod` - the expected `start` and `end` time periods, each with a `code` and `year`.
  - `locations` - the expected location codes, keyed by geographic level label.

Any selection left unset is not compared.

Expected results use labels and codes rather than ids, because a dataset's file id, filter item ids and
indicator ids change with every new release version, whereas its data set file id, labels and location codes
do not.

The file is validated strictly, so a misspelt field is reported as an error rather than ignored.

## Report

Each run writes a JSON report, `reports/regression-report-<env>-<timestamp>.json`, structured as:

- `run` - when the run started and finished, the environment name and URL, the input file and its SHA-256
  hash, the git commit, and the options it was run with.
- `summary` - aggregates the results of every query in every iteration.
- `iterations` - each with its own `summary`, duration, any queries skipped because the maximum cost was
  reached, and `queries`. Each query result has:
  - `status` - see below. `errorMessage` and `lastStage` explain any failure.
  - `durationSeconds`, and `stageTimings` with the time from sending the request to receiving each stage's event.
  - `confidence` and `queryRequirements` from the reranker.
  - `datasetCount`, `tokenUsage`, `cost` and `costIsPartial`.
  - `datasetSummary` and `datasets`, each dataset with its rank, relevance score, validation errors and warnings.
  - `rawEvents` - every SSE event exactly as received, so that results can be re-examined without re-running.

| Status | Meaning |
|---|---|
| `success` | The pipeline completed. |
| `success_with_validation_errors` | The pipeline completed, but at least one dataset result has validation errors. |
| `sse_error` | The service streamed an error event. `lastStage` is the stage reached before the error. |
| `http_error` | The request failed, or the response status wasn't 200. |
| `timeout` | The query didn't complete within `--timeout`. |
| `incomplete_stream` | The stream ended without a `pipeline complete` or error event. |
| `contract_mismatch` | An event didn't match the response schemas in `schemas/responses`. The deployed service and this script have diverged, e.g. because the environment is running a different version. |

The status only describes how the query was executed. Whether the results match the expected results will
be reported separately.

## Cost

Each query makes one reranker call, plus a filter, indicator and time period selection call for every
shortlisted dataset, so its cost grows with the number of datasets shortlisted.

- Token usage and cost are taken from the `pipeline complete` event, which calculates cost from the token
  prices in `common/workflow.py`. Embedding tokens are not included.
- If the pipeline didn't complete, the token usage and cost are taken from the `reranker complete` event, if
  it was received, and `costIsPartial` is `true`, as the tokens used by any later stages are not known.
- `--max-cost` stops new queries from starting once it's reached, but queries already running still complete,
  so a run can exceed it by up to the cost of `--concurrency` queries.

## Tests

The unit tests are in `tests/tools/regression_tests/` and run with the rest of the test suite (`pytest` from the
repository root). They don't call the API.
