"""Writes regression test reports to disk, as JSON, and as Markdown rendered from it for reading."""

from datetime import datetime
from pathlib import Path

from schemas.responses.final_dataset_response import TimePeriodRange
from tools.regression_tests.input_models import ExpectedTimePeriodRange
from tools.regression_tests.report_models import (
    AccuracySummary,
    DatasetResult,
    ExecutionSummary,
    ExpectedDatasetAccuracy,
    GroupedSelectionAccuracy,
    IterationReport,
    PassRate,
    QueryResult,
    RegressionReport,
    SelectionAccuracy,
)


def write_json_report(report: RegressionReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = report.run.started_at.strftime("%Y%m%dT%H%M%SZ")
    path = _get_unused_path(out_dir, f"regression-report-{report.run.environment_name}-{timestamp}")
    path.write_text(report.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    return path


def write_markdown_report(report: RegressionReport, json_report_path: Path) -> Path:
    """Written next to the JSON report, with the same name."""
    path = json_report_path.with_suffix(".md")
    path.write_text(render_markdown_report(report), encoding="utf-8")
    return path


def _get_unused_path(out_dir: Path, stem: str) -> Path:
    """Replays complete in well under a second, so two reports can start within the same second."""
    path = out_dir / f"{stem}.json"
    suffix = 2
    while path.exists():
        path = out_dir / f"{stem}-{suffix}.json"
        suffix += 1
    return path


def render_markdown_report(report: RegressionReport) -> str:
    lines = ["# Regression test report", ""]
    lines += _render_run(report)
    lines += ["## Summary", ""]
    lines += _render_execution_summary(report.summary)
    lines += _render_accuracy_summary(report.accuracy_summary)
    for iteration in report.iterations:
        lines += _render_iteration(iteration, len(report.iterations))
    return "\n".join(lines).rstrip("\n") + "\n"


def _render_run(report: RegressionReport) -> list[str]:
    run = report.run
    if run.replayed_from:
        source = run.replayed_from
        environment = (
            f"Replay of `{source.environment_name}` ({source.base_url}), recorded at {_format_datetime(source.started_at)} "
            f"in `{source.report_file}`. No tokens were used, and durations are meaningless."
        )
    else:
        environment = f"`{run.environment_name}` ({run.base_url})"

    max_cost = "none"
    if run.max_cost is not None:
        max_cost = f"{run.max_cost} ({'reached' if run.budget_exceeded else 'not reached'})"

    rows = [
        ("Started", _format_datetime(run.started_at)),
        ("Environment", environment),
        ("Input file", f"`{run.input_file}` (SHA-256 `{run.input_file_sha256[:12]}`)"),
        ("Git commit", f"`{run.git_commit}`" if run.git_commit else "unknown"),
        ("Queries", f"{_plural(len(run.query_ids), 'query', 'queries')} x {_plural(run.iterations, 'iteration')}, {run.concurrency} at a time"),
        ("Maximum cost", max_cost),
    ]
    return _table(["Run", ""], rows) + [""]


def _render_execution_summary(summary: ExecutionSummary) -> list[str]:
    lines = ["### Execution", ""]
    lines += _table(
        ["Status", "Queries"],
        [(f"`{status}`", count) for status, count in summary.status_counts.items() if count],
    )

    durations = summary.completed_query_durations
    lines += [
        "",
        f"- Tokens: {summary.token_usage.input} input, {summary.token_usage.output} output. "
        f"Cost: {summary.cost:.6f}"
        + (f" ({summary.queries_with_partial_cost} queries with partial cost)" if summary.queries_with_partial_cost else ""),
        (
            f"- Duration of completed queries: mean {durations.mean_seconds:.1f}s, "
            f"p95 {durations.p95_seconds:.1f}s, max {durations.max_seconds:.1f}s"
            if durations
            else "- No queries completed"
        ),
        f"- Datasets: {summary.datasets.dataset_count} returned, "
        f"{summary.datasets.valid_for_table_generation_count} valid for table generation, "
        f"{summary.datasets.with_validation_warnings_count} with warnings",
    ]
    if summary.datasets.validation_error_counts:
        lines.append(f"- Validation errors: {_format_counts(summary.datasets.validation_error_counts)}")
    if summary.datasets.validation_warning_counts:
        lines.append(f"- Validation warnings: {_format_counts(summary.datasets.validation_warning_counts)}")
    return lines + [""]


def _render_accuracy_summary(summary: AccuracySummary | None) -> list[str]:
    lines = ["### Accuracy", ""]
    if summary is None:
        return lines + ["None of the queries have expected results.", ""]

    authors = list(summary.result_counts_by_author)
    lines += _table(
        ["Result", "Queries", *(f"Expected by {author}" for author in authors)],
        [
            (
                f"`{result}`",
                count,
                *(summary.result_counts_by_author[author][result] for author in authors),
            )
            for result, count in summary.result_counts.items()
        ],
    )
    lines.append("")
    lines += _table(
        ["Check", "Passed", "Evaluated", "Pass rate"],
        [
            (name, rate.passed, rate.evaluated, _format_rate(rate))
            for name, rate in (
                ("Required datasets found", summary.required_datasets_found),
                ("Rank", summary.rank),
                ("Filters", summary.filters),
                ("Indicators", summary.indicators),
                ("Time period", summary.time_period),
                ("Locations", summary.locations),
            )
        ],
    )
    lines += [
        "",
        f"- Mean reciprocal rank: {summary.mean_reciprocal_rank if summary.mean_reciprocal_rank is not None else '-'}",
        f"- Problems comparing datasets: {summary.problem_count}",
        "",
    ]
    return lines


def _render_iteration(iteration: IterationReport, iteration_count: int) -> list[str]:
    lines = [f"## Iteration {iteration.iteration} of {iteration_count}", ""]
    lines += _table(
        ["Query", "Status", "Accuracy", "Datasets", "Duration", "Cost"],
        [
            (
                f"[{result.query_id}](#{_anchor(iteration.iteration, result.query_id)})",
                f"`{result.status}`",
                f"`{result.accuracy.result}`" if result.accuracy else "-",
                "-" if result.dataset_count is None else result.dataset_count,
                f"{result.duration_seconds:.1f}s",
                "-" if result.cost is None else f"{result.cost:.6f}" + (" (partial)" if result.cost_is_partial else ""),
            )
            for result in iteration.queries
        ],
    )
    if iteration.skipped_query_ids:
        lines += ["", f"Skipped, as the maximum cost was reached: {', '.join(iteration.skipped_query_ids)}"]
    lines.append("")

    for result in iteration.queries:
        lines += _render_query(iteration.iteration, result)
    return lines


def _render_query(iteration: int, result: QueryResult) -> list[str]:
    lines = [
        f'<a id="{_anchor(iteration, result.query_id)}"></a>',
        f"### {result.query_id} (iteration {iteration})",
        "",
        f"> {result.user_query}",
        "",
        f"- Status: `{result.status}`" + (f" - {result.error_message}" if result.error_message else ""),
    ]
    if result.query_requirements:
        requirements = result.query_requirements
        lines.append(
            f"- Query requirements: filters {_format_list(requirements.filters)}, "
            f"geography {_format_list(requirements.geography)}, time period {requirements.time_period or '-'}"
        )

    accuracy = result.accuracy
    if accuracy:
        lines.append(
            f"- Accuracy: `{accuracy.result}`"
            + (f", against expected results by {accuracy.author}" if accuracy.author else "")
            + (f" - {accuracy.reason}" if accuracy.reason else "")
        )
        if accuracy.min_datasets is not None and accuracy.min_datasets_passed is not None:
            lines.append(
                f"  - At least {_plural(accuracy.min_datasets, 'dataset')}: {_format_passed(accuracy.min_datasets_passed)}"
            )
        for dataset in accuracy.datasets:
            lines += _render_expected_dataset(dataset)

    if result.datasets:
        lines.append("- Datasets returned:")
        for dataset in result.datasets:
            lines += _render_dataset(dataset)
    return lines + [""]


def _render_expected_dataset(dataset: ExpectedDatasetAccuracy) -> list[str]:
    name = f"'{dataset.title}'" if dataset.title else f"`{dataset.data_set_file_id}`"
    if not dataset.found:
        return [
            f"  - Expected dataset {name}: `{dataset.result}` - not found"
            + ("" if dataset.required else ", but it isn't required")
        ]

    rank = f"rank {dataset.rank}"
    if dataset.max_rank is not None:
        rank += f" (expected at most {dataset.max_rank}: {_format_passed(dataset.rank_passed)})"
    lines = [f"  - Expected dataset {name}: `{dataset.result}` - found at {rank}"]

    if dataset.filters is not None:
        lines += _render_grouped_selection("Filters", dataset.filters)
    if dataset.indicators is not None:
        lines.append(f"    - Indicators: {_format_selection(dataset.indicators)}")
    if dataset.time_period is not None:
        lines.append(
            f"    - Time period: {_format_passed(dataset.time_period.passed)} - expected "
            f"{_format_time_period(dataset.time_period.expected)}, selected {_format_time_period(dataset.time_period.selected)}"
        )
    if dataset.locations is not None:
        lines += _render_grouped_selection("Locations", dataset.locations)
    for problem in dataset.problems:
        lines.append(f"    - Problem: {problem}")
    return lines


def _render_grouped_selection(name: str, accuracy: GroupedSelectionAccuracy) -> list[str]:
    lines = [f"    - {name}: {_format_passed(accuracy.passed)}{_format_precision_recall(accuracy.precision, accuracy.recall)}"]
    for label, group in accuracy.groups.items():
        lines.append(f"      - {label}: {_format_selection(group)}")
    return lines


def _render_dataset(dataset: DatasetResult) -> list[str]:
    score = "-" if dataset.relevance_score is None else dataset.relevance_score
    lines = [
        f"  {dataset.rank}. {dataset.title} (`{dataset.data_set_file_id}`), relevance score {score}, "
        + ("valid for table generation" if dataset.is_valid_for_table_generation else "**not valid for table generation**")
    ]
    for error in dataset.validation_errors:
        lines.append(f"     - Error `{error.code}`: {error.message}")
    for warning in dataset.validation_warnings:
        lines.append(f"     - Warning `{warning.code}`: {warning.message}")
    return lines


def _format_selection(accuracy: SelectionAccuracy) -> str:
    text = _format_passed(accuracy.passed) + _format_precision_recall(accuracy.precision, accuracy.recall)
    if accuracy.expected == ["*"]:
        return f"{text} - any selection expected, selected {_format_list(accuracy.selected)}"
    if accuracy.missing:
        text += f", missing {_format_list(accuracy.missing)}"
    if accuracy.unexpected:
        text += f", unexpected {_format_list(accuracy.unexpected)}"
    if accuracy.passed:
        text += f", selected {_format_list(accuracy.selected)}"
    return text


def _format_precision_recall(precision: float | None, recall: float | None) -> str:
    if precision is None and recall is None:
        return ""
    return f" (precision {_format_ratio(precision)}, recall {_format_ratio(recall)})"


def _format_time_period(time_period: TimePeriodRange | ExpectedTimePeriodRange | None) -> str:
    if time_period is None:
        return "none"
    start = f"{time_period.start.code} {time_period.start.year}"
    end = f"{time_period.end.code} {time_period.end.year}"
    return start if start == end else f"{start} to {end}"


def _format_passed(passed: bool | None) -> str:
    return "passed" if passed else "**failed**"


def _format_rate(rate: PassRate) -> str:
    return "-" if rate.pass_rate is None else f"{rate.pass_rate:.0%}"


def _format_ratio(ratio: float | None) -> str:
    return "-" if ratio is None else f"{ratio:.2f}"


def _format_list(values: list[str]) -> str:
    return ", ".join(f"'{value}'" for value in values) if values else "none"


def _format_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"`{code}` ({count})" for code, count in counts.items())


def _format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S %Z")


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def _anchor(iteration: int, query_id: str) -> str:
    return f"iteration-{iteration}-{query_id}"


def _table(headers: list[str], rows: list[tuple]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "---|" * len(headers),
        *("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows),
    ]


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
