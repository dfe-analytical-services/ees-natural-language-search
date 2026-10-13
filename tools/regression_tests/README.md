# Regression Tests (Manual Process)

A script that runs a set of gold standard queries against the natural language search API, and reports how each
query was executed (status, duration, token usage, cost and dataset validation issues) and how accurate its results
were compared with the expected results. It's used to measure the accuracy and consistency of the service, and to
catch regressions before releasing changes.

The API is tested as a black box over HTTP, so no Azure credentials are needed.

> [!IMPORTANT]
> Every query calls Azure OpenAI and costs money, so this is run manually and **not** as part of the CI
> pipeline. See [Cost](#cost) before running a large number of queries or iterations, and use
> [Replay](#replay) to develop the script without using any tokens.

## Requirements

- Python (the CI pipeline targets **3.14**)
- Network access to the environment's function app, and to its EES Data API

The script imports the service's `schemas` and `clients` packages, so it's run from the **repository root**, but it
has its own `requirements.txt`, so create a separate virtual environment for it:

```bash
python -m venv tools/regression_tests/.venv
source tools/regression_tests/.venv/Scripts/activate
pip install -r tools/regression_tests/requirements.txt
```

Any service module the script imports must only depend on packages listed in this requirements file.

## Environments

Environments are configured in `environments.json`, keyed by the name given to `--env`. It's git ignored so that
server URLs aren't committed. Create it by copying `environments.json.example` and filling in the URLs you need:

```json
{
  "dev": {
    "baseUrl": "https://<function app name>.azurewebsites.net",
    "eesDataApiUrl": "https://<EES Data API URL>"
  }
}
```

- `baseUrl` - the function app's host, without any path.
- `eesDataApiUrl` - the environment's `EES_URL_API_DATA` setting, without `/api`. It's used to look up subject meta
  when comparing results with the expected results. Without it, filters aren't compared and expected labels aren't
  checked.

The `local` environment is for running against `func start` on http://localhost:7071. An empty value is treated as
unset. Each environment needs its own gold standard queries file, as dataset and publication ids differ between
environments. Keep `--concurrency` low against `prod`, as the service depends on the Content API.

## Usage

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

# Run every query three times against dev, and compare the results with a previous run
python -m tools.regression_tests --env dev --iterations 3 --baseline tools/regression_tests/reports/regression-report-dev-20260929T142944Z.json
```

| Option | Default | Description |
|---|---|---|
| `--env` | | The environment to run against. Either this or `--replay` is required, unless `--validate` is given. |
| `--replay` | | Replay a previous report instead of calling the service. See [Replay](#replay). |
| `--baseline` | | Compare the results with a previous report. See [Baseline](#baseline). |
| `--input` | `gold_standard/queries.json` | The gold standard queries file. |
| `--query` | | Only run the query with this id. Can be repeated. |
| `--tag` | | Only run queries with this tag. Can be repeated. A query is run if it matches any `--query` or `--tag`. |
| `--iterations` | `1`, or every recorded iteration when replaying | How many times to run each query. Iterations run one after another. |
| `--concurrency` | `2` | How many queries to run at once. Higher concurrency skews durations and risks rate limiting. |
| `--timeout` | `180` | Seconds to wait for each query to complete. |
| `--max-cost` | | Stops starting new queries once the run's cost reaches this. |
| `--out` | `reports/` | The directory to write the report to. It is ignored by git. |
| `--validate` | | Only validate the gold standard queries file. |

| Exit code | Meaning |
|---|---|
| `0` | Every selected query completed the pipeline in every iteration, and none regressed from the baseline. |
| `1` | A query didn't complete the pipeline in every iteration, or the health check failed. |
| `2` | Invalid arguments, an invalid gold standard file, or a report that can't be replayed or used as a baseline. |
| `3` | A query is `regressed` or `mixed` compared with the baseline. This takes precedence over `1`. |

Accuracy only affects the exit code through a comparison with the baseline.

## Replay

`--replay <report>` replays the SSE streams recorded in a previous report's `rawEvents` instead of calling the
service, so no tokens are used. Use it to develop the script against real output, or to re-score a previous run after
changing the expected results.

- Recordings are matched to queries by query text and publication id, so a query whose text has changed isn't
  replayed.
- Each iteration replays the same iteration of the report. `--iterations` can't exceed the number recorded.
- Without `--query` or `--tag`, only the queries recorded in the report are replayed. A selected query without a
  recorded stream is reported as an `http_error`.
- A recording of a query that timed out replays as an `incomplete_stream`.

The new report's environment is `replay`, and `run.replayedFrom` records the report it came from. Token usage and cost
are the recorded ones, and durations are meaningless.

## Gold standard queries file

`gold_standard/queries.json` currently contains starter queries against publications in dev, with expected results
written by a developer, until the gold standard queries are supplied. It's validated strictly, so a misspelt field is
an error. Each query has:

| Field | Required | Description |
|---|---|---|
| `id` | Yes | A unique id, used with `--query` and in the report. |
| `description` | | Why the query is in the gold standard. |
| `userQuery` | Yes | The query sent to the API. |
| `publicationId` | Yes | The publication sent to the API. |
| `tags` | | Used to select queries with `--tag`. |
| `expected` | | The expected results. Leave unset to only report on how the query was executed. |

`expected` can have:

- `author` - `developer` or `product-owner`, so that accuracy against each can be reported separately.
- `minDatasets` - the minimum number of datasets the query should return.
- `datasets` - the datasets the query should return, each identified by its `dataSetFileId`, with:
  - `title` - for readability only, not compared.
  - `maxRank` - the lowest acceptable position in the results, where 1 is the first result.
  - `required` - whether the query fails when the dataset is missing. Defaults to `true`.
  - `filters` - expected filter item labels keyed by filter label, or `"*"` if any selection is acceptable.
  - `indicators` - expected indicator labels.
  - `timePeriod` - expected `start` and `end`, each with a `code` and `year`.
  - `locations` - expected location codes keyed by geographic level label.

Anything left unset is not compared. Labels and codes are used rather than ids, because file ids, filter item ids and
indicator ids change with every release version, whereas data set file ids, labels and location codes don't.

## Accuracy

A selection passes only on an **exact match**. Precision and recall show how close a selection that doesn't pass is.

- **Datasets** are matched by `dataSetFileId`, and fail if not found or found below `maxRank`.
- **Filters** are compared only for the expected filters, as every filter always has a selection.
- **Indicators** are compared by label, and **time periods** by start and end code and year.
- **Locations** are compared by code across every geographic level, so a location at an unexpected level is
  unexpected.

| Result | Meaning |
|---|---|
| `pass` | Every expected dataset was found, and everything expected of it matched. |
| `partial` | The required datasets were found, but something didn't match, or too few datasets were returned. |
| `fail` | A required dataset wasn't found, or too few datasets were returned and none of the expected ones were. |
| `not_evaluated` | The pipeline didn't complete, or (for a dataset) its filters couldn't be compared without subject meta. |

Expected values that don't exist in the dataset's subject meta, e.g. misspelt or changed in a new release, are
reported as `problems`. Accuracy is separate from the execution status, so a `success` can have a `fail` accuracy.

## Consistency

Azure OpenAI isn't fully deterministic, even with a temperature of 0 and a fixed seed. When a run has more than one
iteration, each query is checked for whether its status, accuracy, datasets and selections were the same in every
iteration where the pipeline completed.

## Baseline

`--baseline <report>` compares the run with a previous report, e.g. before and after deploying a change to the
service. The baseline is re-scored against the **current** expected results, so differences come from the service
rather than from changes to the expected results. Combine it with `--replay` to see how changes to the expected
results affect a previous run, without using any tokens.

Each query is compared by its worst status and accuracy in any iteration, and by whether each check passed in every
iteration, so a query that only sometimes fails is treated as failing.

| Change | Meaning |
|---|---|
| `regressed` | Something got worse, and nothing got better. |
| `improved` | Something got better, and nothing got worse. |
| `mixed` | Some things got better, and some got worse. |
| `changed` | Different datasets or selections, but no check got better or worse. |
| `unchanged` | The results are the same. |
| `new` | The query isn't in the baseline, e.g. because it's new, or its text has changed. |

Metrics of the run and the baseline, e.g. pass rates, mean cost and duration, are also compared side by side over the
queries in both.

## Report

Each run writes `reports/regression-report-<env>-<timestamp>.json`, and a `.md` file with the same name for reading.
The JSON has the run's options, summaries of execution, accuracy, consistency and the baseline comparison, and every
query result in every iteration, including its `rawEvents` so that it can be replayed. See `report_models.py` for
every field.

| Status | Meaning |
|---|---|
| `success` | The pipeline completed. |
| `success_with_validation_errors` | The pipeline completed, but at least one dataset has validation errors. |
| `sse_error` | The service streamed an error event. |
| `http_error` | The request failed, or the response status wasn't 200. |
| `timeout` | The query didn't complete within `--timeout`. |
| `incomplete_stream` | The stream ended without a `pipeline complete` or error event. |
| `contract_mismatch` | An event didn't match `schemas/responses`, e.g. because the environment is running a different version. |

## Cost

Each query makes one reranker call, plus filter, indicator and time period selection calls for every shortlisted
dataset, so its cost grows with the number of datasets shortlisted. Embedding tokens aren't included.

`--max-cost` stops new queries from starting once it's reached, but queries already running still complete, so a run
can exceed it by up to the cost of `--concurrency` queries.

## Tests

The unit tests are in `tests/tools/regression_tests/` and run with the rest of the test suite (`pytest` from the
repository root). They don't call the API.
