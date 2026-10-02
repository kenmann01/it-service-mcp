"""Host app: run one natural-language request through the agent.

From the repo root:
    uv run python app/scripts/agent.py "I need a replacement, my headphones broke"
    uv run python app/scripts/agent.py "<request>" --model qwen3:8b
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.llm_client import OllamaClient
from agent.react import run_agent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IT equipment request agent (Planner -> TAO -> Reflector)"
    )
    parser.add_argument("request", help="natural-language equipment request")
    parser.add_argument("--host", default=None, help="Ollama host (default OLLAMA_HOST)")
    parser.add_argument("--model", default=None, help="Ollama model (default OLLAMA_MODEL)")
    args = parser.parse_args()

    env_client = OllamaClient.from_env()
    llm = OllamaClient(host=args.host or env_client.host, model=args.model or env_client.model)

    result = run_agent(args.request, llm=llm)

    print()
    print("=== FINAL RESPONSE ===")
    print(result.final_response)
    summary = f"=== decision={result.decision} rule={result.rule}"
    if result.review_id:
        summary += f" review_id={result.review_id}"
    print(summary + " ===")


if __name__ == "__main__":
    main()
