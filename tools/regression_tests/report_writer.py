"""Writes regression test reports to disk."""

from pathlib import Path

from tools.regression_tests.report_models import RegressionReport


def write_json_report(report: RegressionReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = report.run.started_at.strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"regression-report-{report.run.environment_name}-{timestamp}.json"
    path.write_text(report.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    return path
