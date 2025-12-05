import argparse
import asyncio
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


async def simulate_eval(prompt: str, model: str, scenario: str, run_id: str, idx: int) -> dict[str, Any]:
    start = time.perf_counter()
    await asyncio.sleep(random.uniform(0.05, 0.2))  # simulate work
    latency_ms = int((time.perf_counter() - start) * 1000)
    success = random.random() > 0.1
    rating = random.choice([None, 3, 4, 5]) if success else None
    return {
        "model": model,
        "prompt_version": prompt,
        "success": success,
        "latency_ms": latency_ms,
        "user_rating": rating,
        "error_code": None if success else random.choice(["timeout", "rate_limited", "validation"]),
        "metadata": {
            "scenario": scenario,
            "run_id": run_id,
            "test_case": f"{scenario}_{idx}",
        },
    }


async def run_batch(prompt: str, model: str, limit: int, scenario: str) -> list[dict[str, Any]]:
    run_id = f"{scenario}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    tasks = [simulate_eval(prompt, model, scenario, run_id, i) for i in range(limit)]
    return await asyncio.gather(*tasks)


async def maybe_post_results(results: list[dict[str, Any]], api_base: str | None, token: str | None) -> None:
    if not api_base:
        return
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{api_base.rstrip('/')}/metrics/import", headers=headers, json=results)
        resp.raise_for_status()
        print(f"Upload response: {resp.text}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run synthetic LLM evaluations.")
    parser.add_argument("--prompt", default="latest", help="Prompt version to evaluate")
    parser.add_argument("--model", default="gpt-4.1-mini", help="Model name")
    parser.add_argument("--limit", type=int, default=10, help="Number of evals to generate")
    parser.add_argument("--scenario", default="smoke", help="Scenario tag for metadata")
    parser.add_argument("--output", default="metrics.json", help="Output file path")
    parser.add_argument("--post", action="store_true", help="Post results to the API")
    args = parser.parse_args()

    results = await run_batch(args.prompt, args.model, args.limit, args.scenario)

    output_path = Path(args.output)
    output_path.write_text(json.dumps(results, indent=2))
    print(f"Wrote {len(results)} results to {output_path}")

    if args.post:
        api_base = os.getenv("EVAL_API_BASE")
        api_token = os.getenv("EVAL_API_TOKEN")
        if not api_base:
            raise RuntimeError("EVAL_API_BASE env var required when --post is set")
        await maybe_post_results(results, api_base, api_token)


if __name__ == "__main__":
    asyncio.run(main())
