"""Runs the selected gold standard queries against an environment for a number of iterations."""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from tools.regression_tests.environments import Environment
from tools.regression_tests.input_models import GoldStandardQuery
from tools.regression_tests.report_models import (
    IterationReport,
    QueryResult,
    RegressionReport,
    RunMetadata,
)
from tools.regression_tests.run_result import build_query_result
from tools.regression_tests.sse_client import run_search
from tools.regression_tests.summaries import summarise_queries

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 10


@dataclass
class RunOptions:
    environment_name: str
    environment: Environment
    input_file: str
    input_file_sha256: str
    git_commit: str | None
    iterations: int
    concurrency: int
    timeout_seconds: float
    max_cost: float | None


class HealthCheckError(Exception):
    pass


class _CostBudget:
    """Tracks the cost of the run against its maximum cost.

    Queries already in flight when the maximum is reached still complete, so a run can exceed its maximum
    cost by up to the cost of `concurrency` queries."""

    def __init__(self, max_cost: float | None):
        self.max_cost = max_cost
        self.spent = 0.0

    @property
    def is_exceeded(self) -> bool:
        return self.max_cost is not None and self.spent >= self.max_cost

    def add(self, cost: float | None) -> None:
        self.spent += cost or 0


async def run_regression_tests(
    queries: list[GoldStandardQuery],
    options: RunOptions,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RegressionReport:
    """`transport` is only for replacing the HTTP transport in tests."""
    started_at = datetime.now(UTC)
    budget = _CostBudget(options.max_cost)
    iteration_reports: list[IterationReport] = []

    async with httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(options.timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS),
    ) as client:
        # Also warms up the function app, so that a cold start doesn't skew the first query's duration
        await _check_health(client, options.environment.health_check_url)

        for iteration in range(1, options.iterations + 1):
            iteration_reports.append(
                await _run_iteration(client, queries, iteration, options, budget)
            )
            if budget.is_exceeded:
                logger.warning(
                    "Stopping after iteration %d, as the maximum cost of %s has been reached (spent %.6f)",
                    iteration,
                    options.max_cost,
                    budget.spent,
                )
                break

    return RegressionReport(
        run=RunMetadata(
            started_at=started_at,
            finished_at=datetime.now(UTC),
            environment_name=options.environment_name,
            base_url=options.environment.base_url,
            input_file=options.input_file,
            input_file_sha256=options.input_file_sha256,
            git_commit=options.git_commit,
            query_ids=[query.id for query in queries],
            iterations=options.iterations,
            concurrency=options.concurrency,
            timeout_seconds=options.timeout_seconds,
            max_cost=options.max_cost,
            budget_exceeded=budget.is_exceeded,
        ),
        summary=summarise_queries(
            [result for report in iteration_reports for result in report.queries]
        ),
        iterations=iteration_reports,
    )


async def _check_health(client: httpx.AsyncClient, url: str) -> None:
    logger.info("Checking the health of %s", url)
    try:
        response = await client.get(url)
    except httpx.HTTPError as e:
        raise HealthCheckError(
            f"The health check request to {url} failed: {type(e).__name__}: {e}"
        ) from e

    if response.status_code != 200:
        raise HealthCheckError(
            f"The health check at {url} returned HTTP {response.status_code}"
        )


async def _run_iteration(
    client: httpx.AsyncClient,
    queries: list[GoldStandardQuery],
    iteration: int,
    options: RunOptions,
    budget: _CostBudget,
) -> IterationReport:
    logger.info("Starting iteration %d of %d", iteration, options.iterations)
    semaphore = asyncio.Semaphore(options.concurrency)
    started = time.perf_counter()

    async def run_query(query: GoldStandardQuery) -> QueryResult | None:
        async with semaphore:
            if budget.is_exceeded:
                return None

            execution = await run_search(
                client=client,
                search_url=options.environment.search_url,
                user_query=query.user_query,
                publication_id=query.publication_id,
                timeout_seconds=options.timeout_seconds,
            )
            result = build_query_result(query, execution)
            budget.add(result.cost)
            _log_query_result(iteration, result)
            return result

    # Results are kept in the order of the input file, whatever order the queries complete in
    outcomes = await asyncio.gather(*(run_query(query) for query in queries))
    results = [outcome for outcome in outcomes if outcome is not None]
    skipped_query_ids = [
        query.id for query, outcome in zip(queries, outcomes) if outcome is None
    ]
    if skipped_query_ids:
        logger.warning(
            "Skipped %d queries in iteration %d, as the maximum cost has been reached",
            len(skipped_query_ids),
            iteration,
        )

    return IterationReport(
        iteration=iteration,
        duration_seconds=round(time.perf_counter() - started, 3),
        summary=summarise_queries(results),
        skipped_query_ids=skipped_query_ids,
        queries=results,
    )


def _log_query_result(iteration: int, result: QueryResult) -> None:
    logger.info(
        "[iteration %d] %s: %s in %.1fs, %s datasets, cost %s%s",
        iteration,
        result.query_id,
        result.status,
        result.duration_seconds,
        "-" if result.dataset_count is None else result.dataset_count,
        "-" if result.cost is None else f"{result.cost:.6f}",
        " (partial)" if result.cost_is_partial and result.cost is not None else "",
    )
    if result.error_message:
        logger.warning("[iteration %d] %s: %s", iteration, result.query_id, result.error_message)
