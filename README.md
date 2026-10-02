# IT Service MCP

Week 7 lab: an internal IT equipment request handler exposed as an MCP server,
and a ReAct agent that uses the server's tools to draft responses and escalate
ambiguous cases instead of guessing.

The agent pipeline is Planner -> TAO -> Reflector:

- **Planner**: the system prompt; the model states its plan before acting.
- **TAO**: the Thought / Action / Observation loop over the MCP tools, with an
  explicit `[ROUTE]` step after the decision tool returns.
- **Reflector**: a second LLM pass that confirms or corrects the final draft.

## Policy

Requests are decided by the 16-rule first-match procedure in
[docs/requirements.md](docs/requirements.md), restated in plain language in
[docs/policy.md](docs/policy.md). Three outcomes:

- `approve` when the policy clearly covers the request.
- `deny` when the policy clearly does not cover it.
- `escalate` when the request is ambiguous or missing information; those go to
  `flag_for_human_review` and a human decides.

The procedure is implemented deterministically in `evaluate_request`
(`app/src/tools/decision.py`); the LLM never decides policy, it extracts the
four request fields, calls the tools, routes, and drafts.

## Layout

```
app/src/server.py        MCP server: registers the five tools
app/src/tools/           plain functions (tested directly), one per tool + decision engine
app/src/mcp_client.py    stdio MCP client (one-shot helpers + persistent session)
app/src/agent/           Planner/TAO/Reflector: react.py, llm_client.py, reflection.py, trace.py
app/scripts/agent.py     host app CLI: one request -> decision + trace
app/scripts/run_pool.py  batch runner over demo/request_pool.json
app/tests/               unit tests (no LLM, no live server needed)
examples/                minimal one-tool server + client (plumbing proof)
demo/                    24-request pool, captured traces and outputs
fixtures/                10 structured request cases with expected decisions
docs/                    requirements.md (the spec) and policy.md
```

## Tools

| Tool | What it does |
|---|---|
| `get_employee_info(employee_id)` | role, tenure, equipment on file |
| `get_policy_limits(role)` | what the role is eligible for and how often |
| `check_request_eligibility(employee_id, item)` | static role/item coverage check |
| `evaluate_request(employee, role, item_requested, reason)` | applies the full 16-rule policy, returns `{decision, rule}` |
| `flag_for_human_review(employee_id, request, reason)` | side-effecting escalation to the review queue |

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). The agent also
needs [Ollama](https://ollama.com) running locally with a model pulled
(tests and CI never do):

```bash
uv sync
ollama pull qwen3:8b
```

Copy `.env.example` to `.env` to override `OLLAMA_HOST` / `OLLAMA_MODEL`.

## Run

```bash
# tests (no LLM, no live server)
uv run pytest -q

# minimal one-tool server + client proof
uv run python examples/minimal_client.py

# one hardcoded tool call through the MCP client
uv run python app/scripts/agent_step7.py

# one natural-language request through the full agent
uv run python app/scripts/agent.py "Hi, I'm Grace Hopper (E001). My headphones broke, so I need a replacement."

# the whole 24-request pool, traces saved to demo/traces/
uv run python app/scripts/run_pool.py
```

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |
| `OLLAMA_MODEL` | `qwen3:8b` | chat model used by the agent |
