"""Build the submission PDF for the Week 7 lab.

Assembles the 9 deliverable sections into one print-styled HTML file, then
prints it to submission.pdf with headless Edge.

    uv run python app/scripts/build_submission.py
"""

import ast
import html
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "demo" / "outputs"

KEYWORDS = {
    "def", "class", "return", "if", "elif", "else", "for", "while", "in", "not",
    "and", "or", "import", "from", "as", "with", "async", "await", "try", "except",
    "raise", "None", "True", "False", "self", "yield", "lambda", "pass", "break",
    "continue", "is", "assert", "finally", "del",
}


def read(rel: str) -> str:
    """Read a repo-relative file and drop trailing whitespace."""
    return (ROOT / rel).read_text(encoding="utf-8").rstrip()


def highlight_python(code: str) -> str:
    """Wrap Python keywords, strings, and comments in highlight spans."""
    out = []
    for line in code.splitlines():
        escaped = html.escape(line, quote=False)
        parts = re.split(r"(#.*$)", escaped, maxsplit=1)
        tokens = []
        for i, part in enumerate(parts):
            if i == 1:
                tokens.append(f'<span class="c">{part}</span>')
                continue
            part = re.sub(r'(".*?"|\'.*?\')', r'<span class="s">\1</span>', part)
            for kw in KEYWORDS:
                part = re.sub(rf"\b({kw})\b(?![^<]*</span>)", r'<span class="k">\1</span>', part)
            tokens.append(part)
        out.append("".join(tokens))
    return "\n".join(out)


def code_block(source: str, lang: str) -> str:
    """Render source as a highlighted or escaped code block."""
    body = highlight_python(source) if lang == "py" else html.escape(source)
    return f'<pre class="code">{body}</pre>'


def term_block(source: str) -> str:
    """Render captured terminal output."""
    return f'<pre class="term">{html.escape(source)}</pre>'


def doc_block(source: str) -> str:
    """Render a Markdown document as preformatted text."""
    return f'<pre class="doc">{html.escape(source)}</pre>'


def file_label(rel: str) -> str:
    """Render the repo-relative path shown above a block."""
    return f'<div class="file">{html.escape(rel)}</div>'


COMMIT_SETUP = "dc17847"
COMMIT_TOOLS = "c3a3ad7"


def committed(rel: str, sha: str) -> str:
    """Render one file as it existed in an early commit, before the agent."""
    source = subprocess.run(
        ["git", "show", f"{sha}:{rel}"], capture_output=True, text=True, check=True, cwd=ROOT
    ).stdout.rstrip()
    lang = rel.rsplit(".", 1)[-1]
    label = f"{rel} — as first committed ({sha[:7]})"
    return f'<div class="file">{html.escape(label)}</div>' + code_block(source, lang)


def docstring_count() -> tuple[int, int]:
    """Count documented modules, classes, and functions across the package."""
    total = documented = 0
    for root in ("app/src", "app/scripts", "app/tests", "examples"):
        for py in (ROOT / root).rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    total += 1
                    if ast.get_docstring(node):
                        documented += 1
    return documented, total


def item(kind: str, rel: str) -> str:
    """Load one file and render it as code, a document, or terminal output."""
    text = read(rel)
    lang = rel.rsplit(".", 1)[-1]
    label = file_label(rel)
    if kind == "term":
        return label + term_block(text)
    if kind == "doc":
        return label + doc_block(text)
    return label + code_block(text, lang)


def section(num: int, title: str, body: str) -> str:
    """Wrap one numbered deliverable section."""
    return f"<section><h2>{num}. {html.escape(title)}</h2>{body}</section>"


DEMO_FILE = {
    "approve": "demo/outputs/demo-approve.txt",
    "deny": "demo/outputs/demo-deny.txt",
    "week-overlap": "demo/outputs/demo-escalate-week-overlap.txt",
    "unclear": "demo/outputs/demo-escalate-unclear.txt",
}
DEMO_REQUEST = {
    "approve": "Hi, I'm Grace Hopper (E001). My headphones broke, so I need a replacement.",
    "deny": "Hi, I'm Linus Torvalds (E010). I need a laptop for my work.",
    "week-overlap": "Hi, I'm Ada Lovelace (E009). I'm replacing my laptop and will keep both for a week before returning the old one to IT.",
    "unclear": "Hi, I'm Radia Perlman (E005). I need a second phone since I don't have one right now.",
}


def final_response_block(key: str) -> str:
    """Extract the final response from one captured demo trace."""
    text = read(DEMO_FILE[key])
    tail = text.split("=== FINAL RESPONSE ===", 1)[1].strip()
    return term_block(tail)


def reflection_evidence_block() -> str:
    """Show drafts the reflector rewrote, with the corrected text."""
    parts = []
    for key, note in (
        ("approve", "The Reflector confirmed the draft against the tool observations:"),
        ("week-overlap", "Draft omitted the escalation reason; the Reflector added it:"),
    ):
        text = read(DEMO_FILE[key])
        segment = text.split("[DRAFT]", 1)[1].split("=== FINAL RESPONSE ===", 1)[0].strip()
        parts.append(f'<div class="note"><b>{html.escape(key)} request</b> &mdash; {note}</div>')
        parts.append(term_block("[DRAFT]" + segment))
    return "".join(parts)


CSS = """
@page { size: A4; margin: 16mm 15mm; }
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', Arial, sans-serif; color: #111; margin: 0; }
.cover { height: 252mm; display: flex; flex-direction: column; justify-content: center; }
.cover h1 { font-size: 29pt; margin: 0 0 8px; }
.cover .sub { font-size: 13pt; color: #555; margin-bottom: 34px; }
.cover table { border-collapse: collapse; font-size: 11pt; }
.cover td { padding: 4px 14px 4px 0; vertical-align: top; }
.cover td:first-child { color: #777; white-space: nowrap; }
h2 { font-size: 15.5pt; border-bottom: 2.5px solid #1f6feb; padding-bottom: 5px; margin: 0 0 14px; }
section { page-break-before: always; }
pre { margin: 8px 0 14px; padding: 10px 12px; border-radius: 6px; font-size: 8.1pt; line-height: 1.38; }
pre.term { background: #0d1117; color: #e6edf3; white-space: pre-wrap; word-break: break-word; font-family: Consolas, 'Courier New', monospace; }
pre.code { background: #f6f8fa; border: 1px solid #d0d7de; white-space: pre-wrap; word-break: break-word; font-family: Consolas, 'Courier New', monospace; }
pre.doc { background: #fffdf5; border: 1px solid #e3dcc3; white-space: pre-wrap; word-break: break-word; font-family: Consolas, 'Courier New', monospace; font-size: 8.4pt; }
pre.code .k { color: #cf222e; font-weight: 600; }
pre.code .s { color: #0a3069; }
pre.code .c { color: #6e7781; font-style: italic; }
.file { font-family: Consolas, monospace; font-size: 9pt; color: #1f6feb; margin: 12px 0 0; page-break-after: avoid; break-after: avoid; }
.note { font-size: 10pt; color: #444; margin: 8px 0 2px; }
img.shot { display: block; width: 100%; margin: 10px 0 4px; border: 1px solid #d0d7de; border-radius: 6px; }
.shot-caption { font-family: Consolas, monospace; font-size: 9pt; color: #1f6feb; }
"""


def screenshot_block() -> str:
    """Embed the local desk screenshot as the closing exhibit."""
    return (
        '<div class="note">The local desk (app/scripts/web.py serving app/web/index.html): one filed '
        'request running live against the same agent and MCP server, with the streamed trace rail '
        'and the returned decision.</div>'
        '<img class="shot" src="demo/outputs/Screenshot.png" alt="local desk screenshot">'
        '<div class="shot-caption">demo/outputs/Screenshot.png</div>'
    )


def build_html() -> str:
    """Assemble the nine deliverable sections into one HTML document."""
    p = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"]

    p.append(
        '<div class="cover"><h1>IT Equipment Request Handler</h1>'
        '<div class="sub">Week 7 Lab &middot; MCP Server + ReAct Agent &middot; Submission</div>'
        "<table>"
        "<tr><td>Repo</td><td>github.com/kenmann01/it-service-mcp, branch master</td></tr>"
        "<tr><td>Stack</td><td>Python 3.12+, MCP Python SDK v2 (stdio), Ollama qwen3:8b, uv, pytest</td></tr>"
        "<tr><td>Policy</td><td>16-rule deterministic procedure in evaluate_request: approve / deny / escalate</td></tr>"
        "<tr><td>Agent</td><td>Planner &rarr; TAO (Thought / Action / Observation) &rarr; Reflector, with explicit routing</td></tr>"
        "</table></div>"
    )

    # 1 requirements
    p.append(section(1, "Requirements doc and policy rules", item("doc", "docs/requirements.md") + item("doc", "docs/policy.md")))

    # 2 minimal server + client
    body2 = (
        '<div class="note">The simplest possible server (one trivial tool), then a client that connects, lists tools, and calls it. Captured terminal output below the sources.</div>'
        + item("code", "examples/minimal_server.py")
        + item("code", "examples/minimal_client.py")
        + item("term", "demo/outputs/minimal-server.txt")
        + '<div class="note">The code below is the repository as it existed in the first two commits, before the agent was built: the basic server skeleton first, then the four tools as plain functions over self-generated mock data, their unit tests, and the client used to confirm connectivity.</div>'
        + committed("app/src/server.py", COMMIT_SETUP)
        + committed("app/src/tools/data_store.py", COMMIT_TOOLS)
        + committed("app/data/employees.json", COMMIT_TOOLS)
        + committed("app/data/policy_limits.json", COMMIT_TOOLS)
        + committed("app/src/tools/employee_info.py", COMMIT_TOOLS)
        + committed("app/src/tools/policy_limits.py", COMMIT_TOOLS)
        + committed("app/src/tools/eligibility.py", COMMIT_TOOLS)
        + committed("app/src/tools/human_review.py", COMMIT_TOOLS)
        + committed("app/tests/test_tools.py", COMMIT_TOOLS)
        + committed("app/src/mcp_client.py", COMMIT_TOOLS)
        + committed("app/scripts/call_tool.py", COMMIT_TOOLS)
    )
    p.append(section(2, "Minimal one-tool server and client connection", body2))

    # 3 MCP server code
    documented, definitions = docstring_count()
    body3 = (
        f'<div class="note">Server and tool sources. Every module, class, and function carries a docstring ({documented} of {definitions} by AST count); policy lives in the deterministic evaluate_request register, never in the model.</div>'
        + item("code", "app/src/server.py")
        + item("code", "app/src/tools/employee_info.py")
        + item("code", "app/src/tools/policy_limits.py")
        + item("code", "app/src/tools/eligibility.py")
        + item("code", "app/src/tools/decision.py")
        + item("code", "app/src/tools/human_review.py")
        + item("code", "app/src/tools/data_store.py")
    )
    p.append(section(3, "MCP server code (all five tools)", body3))

    # 4 unit tests + passing output
    body4 = (
        item("code", "app/tests/test_tools.py")
        + item("code", "app/tests/test_decision.py")
        + item("code", "app/tests/test_react.py")
        + item("code", "app/tests/test_reflection.py")
        + item("term", "demo/outputs/pytest.txt")
    )
    p.append(section(4, "Unit tests and passing run", body4))

    # 5 agent code
    body5 = (
        item("code", "app/src/agent/react.py")
        + item("code", "app/src/mcp_client.py")
        + item("code", "app/src/agent/llm_client.py")
        + item("code", "app/src/agent/reflection.py")
        + item("code", "app/src/agent/trace.py")
        + item("code", "app/scripts/agent.py")
    )
    p.append(section(5, "Agent code, including the MCP client connection", body5))

    # 6 ReAct traces
    body6 = '<div class="note">Full live traces (Thought &rarr; Action &rarr; Observation &rarr; Route &rarr; Draft &rarr; Reflection) for the four test requests, run against qwen3:8b and the MCP server.</div>'
    for key in DEMO_FILE:
        body6 += f'<div class="note"><b>Test request:</b> &ldquo;{html.escape(DEMO_REQUEST[key])}&rdquo;</div>'
        body6 += item("term", DEMO_FILE[key])
    p.append(section(6, "Full ReAct traces for the 4 test requests", body6))

    # 7 final decisions
    body7 = '<div class="note">The final response returned to the requester for each of the four test requests, with the routed decision, rule id, and review id where applicable.</div>'
    for key in DEMO_FILE:
        body7 += f'<div class="note"><b>{html.escape(key)} request</b></div>'
        body7 += final_response_block(key)
    p.append(section(7, "Final decision / response for each of the 4 requests", body7))

    # 8 reflection evidence
    p.append(section(8, "Evidence of the reflection step", reflection_evidence_block()))

    # 9 pipeline
    p.append(section(9, "Passing pipeline run", item("term", "demo/outputs/ci-run.txt") + item("term", "demo/outputs/pool-results.txt")))

    # 10 local desk screenshot
    p.append(section(10, "The local desk", screenshot_block()))

    p.append("</body></html>")
    return "".join(p)


def main() -> None:
    """Write submission.html and print it to submission.pdf."""
    html_path = ROOT / "submission.html"
    html_path.write_text(build_html(), encoding="utf-8")

    pdf_path = ROOT / "submission.pdf"
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    subprocess.run(
        [
            edge,
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    print(f"wrote {pdf_path} ({pdf_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
