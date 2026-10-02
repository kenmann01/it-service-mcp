"""Batch-run the agent over demo/request_pool.json.

For every case: run the full Planner/TAO/Reflector pipeline against the live
MCP server and Ollama, save the trace to demo/traces/<id>.txt, and compare the
routed decision with the expected one. Ends with a results table.

From the repo root:
    uv run python app/scripts/run_pool.py
    uv run python app/scripts/run_pool.py --ids approve-01-headphones-replacement
    uv run python app/scripts/run_pool.py --model qwen3:8b --out demo/traces
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.llm_client import OllamaClient
from agent.react import run_agent


def main() -> None:
    """Run the request pool and print how each case compared to its expected decision."""
    parser = argparse.ArgumentParser(description="Run the agent over the request pool")
    parser.add_argument("--pool", default=str(ROOT / "demo" / "request_pool.json"))
    parser.add_argument("--out", default=str(ROOT / "demo" / "traces"))
    parser.add_argument("--ids", nargs="*", default=None, help="run only these case ids")
    parser.add_argument("--host", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    pool = json.loads(Path(args.pool).read_text(encoding="utf-8"))
    cases = pool["cases"]
    if args.ids:
        wanted = set(args.ids)
        cases = [case for case in cases if case["id"] in wanted]

    env_client = OllamaClient.from_env()
    llm = OllamaClient(host=args.host or env_client.host, model=args.model or env_client.model)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for case in cases:
        print(f"\n{'=' * 72}")
        print(f"[{case['id']}] bucket={case['bucket']}")
        print(f"REQUEST: {case['request']}")
        print("=" * 72, flush=True)

        started = time.time()
        result = run_agent(case["request"], llm=llm)
        elapsed = time.time() - started

        (out_dir / f"{case['id']}.txt").write_text(
            f"REQUEST: {case['request']}\n\n"
            + result.trace.to_text()
            + f"\n\nFINAL RESPONSE:\n{result.final_response}\n",
            encoding="utf-8",
        )

        status = "OK" if result.decision == case["expected_decision"] else "MISMATCH"
        rows.append(
            {
                "id": case["id"],
                "bucket": case["bucket"],
                "expected": case["expected_decision"],
                "got": result.decision or "-",
                "rule": result.rule or "-",
                "status": status,
                "seconds": f"{elapsed:.0f}",
            }
        )
        print(f"\n>>> [{case['id']}] {status}: expected={case['expected_decision']} got={result.decision} rule={result.rule}")

    print(f"\n\n{'=' * 72}\nRESULTS ({len(rows)} cases)\n{'=' * 72}")
    header = f"{'id':<44} {'expected':<9} {'got':<9} {'rule':<28} {'status':<9} {'sec':>4}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['id']:<44} {row['expected']:<9} {row['got']:<9} {row['rule']:<28} {row['status']:<9} {row['seconds']:>4}"
        )

    ok = sum(1 for row in rows if row["status"] == "OK")
    print("-" * len(header))
    print(f"matched expectations: {ok}/{len(rows)}")
    by_bucket: dict[str, list[str]] = {}
    for row in rows:
        by_bucket.setdefault(row["bucket"], []).append(row["status"])
    for bucket, statuses in by_bucket.items():
        print(f"  {bucket}: {statuses.count('OK')}/{len(statuses)} OK")


if __name__ == "__main__":
    main()
