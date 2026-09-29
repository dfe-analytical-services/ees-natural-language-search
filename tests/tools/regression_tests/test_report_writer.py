"""Tests for writing reports in `tools.regression_tests.report_writer`."""

from datetime import UTC, datetime

from schemas.shared.token_usage import TokenUsage
from tools.regression_tests.report_models import RegressionReport, RunMetadata
from tools.regression_tests.report_writer import write_json_report
from tools.regression_tests.summaries import summarise_queries


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
