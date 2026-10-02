"""Build the submission PDF for the Week 7 lab.

Assembles the 9 deliverable sections into one print-styled HTML file, then
prints it to submission.pdf with headless Edge.

    uv run python app/scripts/build_submission.py
"""

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
    return (ROOT / rel).read_text(encoding="utf-8").rstrip()


def highlight_python(code: str) -> str:
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
    body = highlight_python(source) if lang == "py" else html.escape(source)
    return f'<pre class="code">{body}</pre>'


def term_block(source: str) -> str:
    return f'<pre class="term">{html.escape(source)}</pre>'


def doc_block(source: str) -> str:
    return f'<pre class="doc">{html.escape(source)}</pre>'


def file_label(rel: str) -> str:
    return f'<div class="file">{html.escape(rel)}</div>'


def item(kind: str, rel: str) -> str:
    text = read(rel)
    lang = rel.rsplit(".", 1)[-1]
    label = file_label(rel)
    if kind == "term":
        return label + term_block(text)
    if kind == "doc":
        return label + doc_block(text)
    return label + code_block(text, lang)


def section(num: int, title: str, body: str) -> str:
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
    text = read(DEMO_FILE[key])
    tail = text.split("=== FINAL RESPONSE ===", 1)[1].strip()
    return term_block(tail)


def reflection_evidence_block() -> str:
    parts = []
    for key, note in (
        ("deny", "Draft was a meta-note; the Reflector rewrote it into a real refusal:"),
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
"""


def build_html() -> str:
    p = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"]

    p.append(
        '<div class="cover"><h1>IT Equipment Request Handler</h1>'
        '<div class="sub">Week 7 Lab &middot; MCP Server + ReAct Agent &middot; Submission</div>'
        "<table>"
        "<tr><td>Repo</td><td>github.com/kenmann01/it-service-mcp, branch feat/agent-react</td></tr>"
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
    )
    p.append(section(2, "Minimal one-tool server and client connection", body2))

    # 3 MCP server code
    body3 = (
        item("code", "app/src/server.py")
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

    p.append("</body></html>")
    return "".join(p)


def main() -> None:
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
