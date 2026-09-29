"""Tests for writing reports in `tools.regression_tests.report_writer`."""

from datetime import UTC, datetime

from schemas.responses.final_dataset_response import DatasetValidationError, DatasetValidationErrorCode
from schemas.shared.token_usage import TokenUsage
from tools.regression_tests.report_models import (
    AccuracyResult,
    ConsistencyAspect,
    ConsistencySummary,
    DatasetResult,
    ExecutionStatus,
    ExpectedDatasetAccuracy,
    IterationReport,
    QueryAccuracy,
    QueryConsistency,
    QueryResult,
    RegressionReport,
    ReplaySource,
    RunConsistency,
    RunMetadata,
    SelectionAccuracy,
)
from tools.regression_tests.report_writer import (
    render_markdown_report,
    write_json_report,
    write_markdown_report,
)
from tools.regression_tests.summaries import summarise_accuracy, summarise_queries


def _report() -> RegressionReport:
    started_at = datetime(2026, 9, 29, 14, 29, 44, tzinfo=UTC)
    return RegressionReport(
        run=RunMetadata(
            started_at=started_at,
            finished_at=started_at,
            environment_name="dev",
            base_url="https://dev",
            input_file="queries.json",
            input_file_sha256="test-sha256",
            query_ids=[],
            iterations=1,
            concurrency=1,
            timeout_seconds=5,
            budget_exceeded=False,
        ),
        summary=summarise_queries([]),
    )


def test_report_is_named_after_the_environment_and_start_time(tmp_path):
    path = write_json_report(_report(), tmp_path)

    assert path.name == "regression-report-dev-20260929T142944Z.json"
    assert RegressionReport.model_validate_json(path.read_bytes()).summary.token_usage == TokenUsage()


def test_reports_starting_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    paths = [write_json_report(_report(), tmp_path) for _ in range(3)]

    assert [path.name for path in paths] == [
        "regression-report-dev-20260929T142944Z.json",
        "regression-report-dev-20260929T142944Z-2.json",
        "regression-report-dev-20260929T142944Z-3.json",
    ]


def _report_with_query(accuracy: QueryAccuracy | None) -> RegressionReport:
    result = QueryResult(
        query_id="query-1",
        user_query="absence | attendance",
        publication_id="test-publication-id",
        status=ExecutionStatus.SUCCESS,
        duration_seconds=2.5,
        dataset_count=1,
        cost=0.0025,
        cost_is_partial=False,
        accuracy=accuracy,
        datasets=[
            DatasetResult(
                rank=1,
                file_id="file-1",
                data_set_file_id="data-set-file-1",
                subject_id="subject-1",
                title="Absence by characteristic",
                relevance_score=75.8,
                is_valid_for_table_generation=False,
                validation_errors=[DatasetValidationError(code=DatasetValidationErrorCode.NO_INDICATORS, message="No indicators")],
            )
        ],
    )
    report = _report()
    report.run.query_ids = ["query-1"]
    report.iterations = [
        IterationReport(iteration=1, duration_seconds=2.5, summary=summarise_queries([result]), queries=[result])
    ]
    report.summary = summarise_queries([result])
    report.accuracy_summary = summarise_accuracy([result])
    return report


def test_markdown_report_is_written_next_to_the_json_report(tmp_path):
    report = _report_with_query(None)
    json_path = write_json_report(report, tmp_path)

    markdown_path = write_markdown_report(report, json_path)

    assert markdown_path == json_path.with_suffix(".md")
    assert markdown_path.read_text(encoding="utf-8").startswith("# Regression test report\n")


def test_markdown_report_without_expected_results():
    markdown = render_markdown_report(_report_with_query(None))

    assert "None of the queries have expected results." in markdown
    assert "| [query-1](#iteration-1-query-1) | `success` | - | 1 | 2.5s | 0.002500 |" in markdown
    assert "**not valid for table generation**" in markdown
    assert "- Error `no_indicators`: No indicators" in markdown


def test_markdown_report_describes_the_accuracy_of_each_expected_dataset():
    accuracy = QueryAccuracy(
        result=AccuracyResult.PARTIAL,
        author="developer",
        min_datasets=1,
        min_datasets_passed=True,
        datasets=[
            ExpectedDatasetAccuracy(
                data_set_file_id="data-set-file-1",
                title="Absence by characteristic",
                required=True,
                result=AccuracyResult.PARTIAL,
                found=True,
                rank=1,
                max_rank=1,
                rank_passed=True,
                indicators=SelectionAccuracy(
                    passed=False,
                    expected=["Overall absence rate"],
                    selected=["Overall absence rate", "Number of sessions"],
                    unexpected=["Number of sessions"],
                    precision=0.5,
                    recall=1.0,
                ),
                problems=["The expected filter 'Region' doesn't exist in the subject meta"],
            ),
            ExpectedDatasetAccuracy(
                data_set_file_id="data-set-file-2", required=False, result=AccuracyResult.FAIL, found=False
            ),
        ],
    )

    markdown = render_markdown_report(_report_with_query(accuracy))

    assert "| `partial` | 1 | 1 |" in markdown
    assert "- Accuracy: `partial`, against expected results by developer" in markdown
    assert "  - At least 1 dataset: passed" in markdown
    assert (
        "  - Expected dataset 'Absence by characteristic': `partial` - found at rank 1 (expected at most 1: passed)"
        in markdown
    )
    assert (
        "    - Indicators: **failed** (precision 0.50, recall 1.00), unexpected 'Number of sessions'" in markdown
    )
    assert "    - Problem: The expected filter 'Region' doesn't exist in the subject meta" in markdown
    assert "  - Expected dataset `data-set-file-2`: `fail` - not found, but it isn't required" in markdown


def test_markdown_report_describes_a_replay():
    report = _report_with_query(None)
    report.run.replayed_from = ReplaySource(
        report_file="reports/recorded.json",
        environment_name="dev",
        base_url="https://dev",
        started_at=datetime(2026, 9, 29, 14, 0, 0, tzinfo=UTC),
    )

    markdown = render_markdown_report(report)

    assert "Replay of `dev` (https://dev), recorded at 2026-09-29 14:00:00 UTC in `reports/recorded.json`" in markdown


def test_markdown_table_cells_escape_pipes():
    report = _report_with_query(None)
    report.iterations[0].queries[0].query_id = "query|1"

    assert r"[query\|1]" in render_markdown_report(report)


def test_markdown_report_describes_inconsistent_queries():
    report = _report_with_query(None)
    report.consistency = RunConsistency(
        summary=ConsistencySummary(
            query_count=2,
            consistent_count=1,
            consistency_rate=0.5,
            inconsistent_counts={aspect: int(aspect == ConsistencyAspect.INDICATORS) for aspect in ConsistencyAspect},
        ),
        queries=[
            QueryConsistency(query_id="query-1", iterations=3, consistent=True),
            QueryConsistency(
                query_id="query-2",
                iterations=3,
                consistent=False,
                inconsistent_aspects=[ConsistencyAspect.INDICATORS],
                differences=["Iteration 2, compared with iteration 1: Indicators of 'Dataset 1': added 'Rate'"],
            ),
        ],
    )

    markdown = render_markdown_report(report)

    assert "1 of 2 queries returned the same results in every iteration." in markdown
    assert "| `indicators` | 1 |" in markdown
    assert "- **query-1**" not in markdown
    assert "- **query-2**, over 3 iterations:\n  - Iteration 2, compared with iteration 1: Indicators of 'Dataset 1': added 'Rate'" in markdown
