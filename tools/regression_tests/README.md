# Regression Tests (Manual Process)

A script that runs a set of gold standard queries against the natural language search API, and writes a
report of how each query was executed, e.g. its status, duration, token usage, cost and dataset validation
issues, and of how accurate its results were compared with the expected results. It's used to measure the
accuracy and consistency of the service, and to catch regressions before releasing changes.

The API is tested as a black box over HTTP, so it can be run against a deployed environment without any
Azure credentials.

> [!IMPORTANT]
> Every query calls Azure OpenAI and costs money, so this is run manually and **not** as part of the CI
> pipeline. See [Cost](#cost) before running a large number of queries or iterations, and use
> [Replay](#replay) to develop the script without using any tokens.

## Requirements

- Python (the CI pipeline targets **3.14**)
- Network access to the environment's function app, and to its EES Data API

Install the dependencies from the **repository root**:

```bash
pip install -r tools/regression_tests/requirements.txt
```

## Environments

The environments are configured in `environments.json`, keyed by the name given to `--env`:

```json
{
  "dev": {
    "baseUrl": "https://s101d01-ees-fa-nlsearch.azurewebsites.net",
    "eesDataApiUrl": "https://data.dev.explore-education-statistics.service.gov.uk"
  }
}
```

- `baseUrl` - the function app's host, without any path. The search and health check paths are added to it.
- `eesDataApiUrl` - the environment's `EES_URL_API_DATA` setting, without `/api`, as the Data API client adds it.
  It's used to look up the subject meta of dataset results when comparing them with the expected results, so it
  must match the setting of the function app. Without it, filters aren't compared, and the expected labels aren't
  checked. Looking up subject meta doesn't use any Azure OpenAI tokens.

The `local` environment is for running against `func start` on http://localhost:7071.

## Usage

Run from the **repository root**, as the script imports the service's response schemas from `schemas/`:

```bash
# Check the gold standard queries file, without running any queries
python -m tools.regression_tests --validate

# Run every query once against dev
python -m tools.regression_tests --env dev

# Run two queries three times each, stopping once the cost reaches 0.50
python -m tools.regression_tests --env dev --query attendance-holiday-last-4-weeks --query absence-pupil-referral-units-by-region --iterations 3 --max-cost 0.5

# Run the queries tagged 'attendance'
python -m tools.regression_tests --env dev --tag attendance

# Replay a previous report, without calling the service or using any tokens
python -m tools.regression_tests --replay tools/regression_tests/reports/regression-report-dev-20260929T142944Z.json
```

| Option | Default | Description |
|---|---|---|
| `--env` | | The environment to run against, from `environments.json`. Either this or `--replay` is required, unless `--validate` is given. |
| `--replay` | | Replay the streams recorded in a previous report instead of calling the service. See [Replay](#replay). |
| `--input` | `gold_standard/queries.json` | The gold standard queries file. |
| `--query` | | Only run the query with this id. Can be repeated. |
| `--tag` | | Only run queries with this tag. Can be repeated. A query is run if it matches any `--query` or `--tag`. |
| `--iterations` | `1`, or every recorded iteration when replaying | How many times to run each query, to measure consistency. Iterations run one after another. |
| `--concurrency` | `2` | How many queries to run at once. Keep it low, as higher concurrency skews durations and risks Azure OpenAI rate limiting. |
| `--timeout` | `180` | Seconds to wait for each query to complete. |
| `--max-cost` | | Stops starting new queries once the run's cost reaches this. |
| `--out` | `reports/` | The directory to write the report to. It is ignored by git. |
| `--validate` | | Only validate the gold standard queries file. |

The exit code is `0` when every selected query completed the pipeline in every iteration, `1` when any
didn't, or the health check failed, and `2` for invalid arguments, an invalid gold standard file, or a report
that can't be replayed.

## Replay

`--replay <report>` serves the SSE streams recorded in a previous report's `rawEvents` instead of calling the
service, so no Azure OpenAI tokens are used. Everything after the network runs exactly as it does against a real
environment, e.g. parsing the streams, classifying each query's status and summarising the results. Use it to:

- develop and test changes to the script against real output from an environment, without any cost.
- re-examine a previous run's results with the current version of the script.

Replaying also compares the results with the current expected results, so it's how to re-score a previous run
after changing the expected results, or the comparison itself.

How recordings are matched and replayed:

- A recording is matched to a query by its query text and publication id, not its query id, so a query whose text
  has changed since it was recorded isn't replayed with events that no longer correspond to it.
- Each iteration replays the streams recorded in the same iteration of the report. By default every recorded
  iteration is replayed, and `--iterations` can't exceed the number recorded.
- Without `--query` or `--tag`, only the queries recorded in the report are replayed. Queries selected explicitly
  that weren't recorded, or whose recorded request failed without a stream, are reported as an `http_error`.
- Recordings of queries that timed out replay as an `incomplete_stream`, as only the events received before the
  timeout were recorded.

The new report's environment is `replay`, and `run.replayedFrom` records which report was replayed and which
environment it was recorded against. Its token usage and cost are the recorded ones, and its durations are
meaningless, as the streams are replayed without any delay.

## Gold standard queries file

`gold_standard/queries.json` currently contains starter queries against publications in dev, without any
expected results, until the gold standard queries are supplied. Each query has:

| Field | Required | Description |
|---|---|---|
| `id` | Yes | A unique id, used to select the query with `--query` and to identify it in the report. |
| `description` | | Why the query is in the gold standard. |
| `userQuery` | Yes | The query sent to the API. |
| `publicationId` | Yes | The publication sent to the API. |
| `tags` | | Used to select queries with `--tag`. |
| `expected` | | The expected results. Leave unset to only report on how the query was executed. |

`expected` can have:

- `author` - who wrote the expected results, either `developer` or `product-owner`, so that the accuracy against
  each can be reported separately. The starter queries have expected results written by a developer.
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

## Accuracy

After the queries have run, the results of each query with expected results are compared with them. A selection
passes only on an **exact match** with what's expected, and precision and recall are reported alongside, to show
how close a selection that doesn't pass is.

- **Datasets** are matched by `dataSetFileId`. A dataset fails if it isn't found, or is found below its `maxRank`.
- **Filters** are compared filter by filter, and only for the expected filters, as every filter of a dataset always
  has a selection. The selected filter items don't say which filter they belong to, so that's looked up in the
  dataset's subject meta. A filter expected to be `"*"` accepts any selection.
- **Indicators** are compared by label.
- **Time periods** must match the expected start and end code and year exactly.
- **Locations** are compared by location code, across every geographic level, so a location selected at a level
  that isn't expected is unexpected. Levels without any selected locations are ignored.

| Result | Meaning |
|---|---|
| `pass` | Every expected dataset was found, and everything expected of it matched. |
| `partial` | The required datasets were found, but something expected of them didn't match, or too few datasets were returned. |
| `fail` | A required dataset wasn't found, or too few datasets were returned and none of the expected ones were found. |
| `not_evaluated` | The pipeline didn't complete. An expected dataset is also `not_evaluated` if its filters couldn't be compared without the subject meta, which makes the query `partial`. |

Expected values that don't exist in the dataset's subject meta, e.g. because they're misspelt, or they changed with
a new release, can never be selected, so they're reported as `problems`.

Accuracy is separate from the execution status, so a query can be a `success` with a `fail` accuracy.

## Report

Each run writes a JSON report, `reports/regression-report-<env>-<timestamp>.json`, and renders it as Markdown for
reading, in a `.md` file with the same name. The JSON report is structured as:

- `run` - when the run started and finished, the environment name and URL, the input file and its SHA-256
  hash, the git commit, and the options it was run with.
- `summary` - aggregates how every query in every iteration was executed.
- `accuracySummary` - aggregates the accuracy of every query with expected results: the result counts, overall and
  by `author`, the pass rate of each check, the mean reciprocal rank, and the number of problems.
- `iterations` - each with its own `summary` and `accuracySummary`, duration, any queries skipped because the
  maximum cost was reached, and `queries`. Each query result has:
  - `status` - see below. `errorMessage` and `lastStage` explain any failure.
  - `durationSeconds`, and `stageTimings` with the time from sending the request to receiving each stage's event.
  - `confidence` and `queryRequirements` from the reranker.
  - `datasetCount`, `tokenUsage`, `cost` and `costIsPartial`.
  - `datasetSummary` and `datasets`, each dataset with its rank, relevance score, selections, validation errors and
    warnings.
  - `accuracy` - see [Accuracy](#accuracy). Unset if the query has no expected results.
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

The status only describes how the query was executed. Whether the results match the expected results is
described by `accuracy`.

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
