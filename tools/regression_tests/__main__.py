"""Runs the gold standard queries against the natural language search API and writes a report.

Run from the repository root, e.g. `python -m tools.regression_tests --env dev`. See `README.md` for all options.
"""

import argparse
import asyncio
import hashlib
import logging
import subprocess
import sys
from pathlib import Path

from tools.regression_tests.environments import load_environments
from tools.regression_tests.input_models import GoldStandardFileError, load_gold_standard
from tools.regression_tests.report_models import COMPLETED_STATUSES, RegressionReport
from tools.regression_tests.report_writer import write_json_report
from tools.regression_tests.runner import HealthCheckError, RunOptions, run_regression_tests

logger = logging.getLogger("tools.regression_tests")

PACKAGE_DIR = Path(__file__).parent
REPOSITORY_ROOT = PACKAGE_DIR.parent.parent
DEFAULT_INPUT_FILE = PACKAGE_DIR / "gold_standard" / "queries.json"
DEFAULT_OUT_DIR = PACKAGE_DIR / "reports"

EXIT_OK = 0
EXIT_QUERIES_NOT_COMPLETED = 1
EXIT_INVALID_ARGUMENTS = 2


def main(argv: list[str] | None = None) -> int:
    environments = load_environments()
    args = _parse_args(argv, environment_names=sorted(environments))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx logs every request at INFO, which duplicates the per-query logging
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        gold_standard = load_gold_standard(args.input)
        queries = gold_standard.select(query_ids=args.query, tags=args.tag)
    except (GoldStandardFileError, ValueError) as e:
        logger.error("%s", e)
        return EXIT_INVALID_ARGUMENTS

    if args.validate:
        logger.info("%s is valid, with %d selected queries", args.input, len(queries))
        return EXIT_OK

    options = RunOptions(
        environment_name=args.env,
        environment=environments[args.env],
        input_file=_display_path(args.input),
        input_file_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
        git_commit=_get_git_commit(),
        iterations=args.iterations,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout,
        max_cost=args.max_cost,
    )
    logger.info(
        "Running %d queries x %d iterations against '%s' (%s)",
        len(queries),
        options.iterations,
        options.environment_name,
        options.environment.base_url,
    )

    try:
        report = asyncio.run(run_regression_tests(queries, options))
    except HealthCheckError as e:
        logger.error("%s", e)
        return EXIT_QUERIES_NOT_COMPLETED

    report_path = write_json_report(report, args.out)
    _log_run_summary(report, report_path)
    return EXIT_OK if _all_queries_completed(report) else EXIT_QUERIES_NOT_COMPLETED


def _parse_args(argv: list[str] | None, environment_names: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.regression_tests",
        description="Runs gold standard queries against the natural language search API and writes a JSON report.",
    )
    parser.add_argument("--env", choices=environment_names, help="The environment to run against, from environments.json.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_FILE, help="The gold standard queries file. Default: %(default)s")
    parser.add_argument("--query", action="append", default=[], metavar="QUERY_ID", help="Only run this query. Can be repeated.")
    parser.add_argument("--tag", action="append", default=[], help="Only run queries with this tag. Can be repeated.")
    parser.add_argument("--iterations", type=_positive_int, default=1, help="How many times to run each query. Default: %(default)s")
    parser.add_argument("--concurrency", type=_positive_int, default=2, help="How many queries to run at once. Default: %(default)s")
    parser.add_argument("--timeout", type=_positive_float, default=180, help="Seconds to wait for each query to complete. Default: %(default)s")
    parser.add_argument("--max-cost", type=_positive_float, help="Stop starting new queries once the run's cost reaches this.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="The directory to write the report to. Default: %(default)s")
    parser.add_argument("--validate", action="store_true", help="Only validate the gold standard queries file, without running any queries.")

    args = parser.parse_args(argv)
    if not args.validate and args.env is None:
        parser.error("--env is required, unless --validate is given")
    return args


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return number


def _display_path(path: Path) -> str:
    """The path relative to the repository root where possible, so that reports don't depend on where it's cloned."""
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return str(path)


def _get_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=PACKAGE_DIR,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _all_queries_completed(report: RegressionReport) -> bool:
    # Reaching the maximum cost only matters if it stopped queries from running
    return (
        len(report.iterations) == report.run.iterations
        and all(
            not iteration.skipped_query_ids
            and all(result.status in COMPLETED_STATUSES for result in iteration.queries)
            for iteration in report.iterations
        )
    )


def _log_run_summary(report: RegressionReport, report_path: Path) -> None:
    summary = report.summary
    status_counts = ", ".join(
        f"{status}: {count}" for status, count in summary.status_counts.items() if count
    )
    logger.info("Ran %d queries (%s)", summary.query_count, status_counts or "none")
    logger.info(
        "Total tokens %d input / %d output, cost %.6f%s",
        summary.token_usage.input,
        summary.token_usage.output,
        summary.cost,
        f" ({summary.queries_with_partial_cost} queries with partial cost)"
        if summary.queries_with_partial_cost
        else "",
    )
    logger.info("Report written to %s", report_path)


if __name__ == "__main__":
    sys.exit(main())
