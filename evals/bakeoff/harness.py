"""Bake-off harness — runs the same questions through Claude twice.

Run A: BASELINE — file tools only (read_file, glob_files, grep_files).
Run B: WITH_UNITYGRAPH — same file tools + the v1.6 MCP query library.

Same model, same temperature, same system prompt, same questions.
Only the tool list differs.

Outputs `runs.json` with the model's final answer + tool-call trace per
question per configuration.
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from anthropic import Anthropic

from unitygraph.build.graph import Graph
from unitygraph.mcp import queries

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path("D:/PR/Unity/clash.io")
GRAPH_PATH = PROJECT_ROOT / "graph-out" / "graph.json"
MODEL = "claude-haiku-4-5-20251001"
MAX_TURNS = 12
SYSTEM_PROMPT = (
    "You are an assistant helping a Unity game developer answer questions "
    "about the project at the specified root. Use the tools provided to "
    "investigate the codebase. When you are confident in your answer, "
    "respond with a final answer in your text. Do not invent file paths "
    "or values — only state things you have verified through a tool call. "
    "If a question cannot be answered with your tools, say so explicitly "
    "rather than guessing.\n\n"
    f"Project root: {PROJECT_ROOT}"
)

# ---------------------------------------------------------------------------
# Tool implementations — file primitives (both configurations)
# ---------------------------------------------------------------------------


def _safe_path(rel_or_abs: str) -> Path | None:
    """Resolve a path under PROJECT_ROOT. Reject anything outside."""
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    try:
        p = p.resolve()
        p.relative_to(PROJECT_ROOT.resolve())
    except (OSError, ValueError):
        return None
    return p


def tool_read_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
    target = _safe_path(path)
    if target is None or not target.exists() or not target.is_file():
        return f"ERROR: file not found: {path}"
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"ERROR: {exc}"
    end = min(end_line, len(lines))
    chunk = lines[start_line - 1 : end]
    numbered = "\n".join(f"{i+start_line:5}| {line}" for i, line in enumerate(chunk))
    return f"{path} (lines {start_line}-{end} of {len(lines)}):\n{numbered}"


def tool_glob_files(pattern: str, max_results: int = 50) -> str:
    matches = []
    for p in PROJECT_ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(p.name, pattern):
            matches.append(rel)
            if len(matches) >= max_results:
                break
    if not matches:
        return f"no files match {pattern}"
    return f"matched {len(matches)} files (capped at {max_results}):\n" + "\n".join(matches)


def tool_grep_files(pattern: str, glob: str = "*.cs", max_results: int = 30) -> str:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"ERROR: bad regex: {exc}"
    out = []
    for p in PROJECT_ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(PROJECT_ROOT).as_posix()
        if not (fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(p.name, glob)):
            continue
        if any(skip in rel for skip in ("/Library/", "/Temp/", "/obj/", "/Build/")):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                out.append(f"{rel}:{i}: {line.strip()[:200]}")
                if len(out) >= max_results:
                    break
        if len(out) >= max_results:
            break
    if not out:
        return f"no matches for {pattern} in {glob}"
    return "\n".join(out)


# ---------------------------------------------------------------------------
# UnityGraph tools — only present in run B
# ---------------------------------------------------------------------------

_GRAPH = None


def _graph() -> Graph:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = Graph.load(GRAPH_PATH)
    return _GRAPH


def tool_who_uses(script_name: str) -> str:
    return json.dumps(queries.who_uses(_graph(), script_name), indent=2, default=str)[:6000]


def tool_inspector_overrides_for(script_name: str) -> str:
    return json.dumps(
        queries.inspector_overrides_for(_graph(), script_name), indent=2, default=str
    )[:6000]


def tool_event_listeners(script_name: str) -> str:
    return json.dumps(
        queries.event_listeners(_graph(), script_name), indent=2, default=str
    )[:6000]


def tool_find_missing_scripts(min_attachments: int = 1) -> str:
    return json.dumps(
        queries.find_missing_scripts(_graph(), min_attachments=min_attachments),
        indent=2,
        default=str,
    )[:6000]


def tool_field_wiring(script_name: str, field_name: str) -> str:
    return json.dumps(
        queries.field_wiring(_graph(), script_name, field_name), indent=2, default=str
    )[:6000]


def tool_find_singletons(min_attachments: int = 2) -> str:
    return json.dumps(
        queries.find_singletons(_graph(), min_attachments=min_attachments),
        indent=2,
        default=str,
    )[:6000]


# ---------------------------------------------------------------------------
# Tool schemas (Anthropic format)
# ---------------------------------------------------------------------------

FILE_TOOLS = [
    {
        "name": "read_file",
        "description": "Read a project-relative file with optional line range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project-relative path"},
                "start_line": {"type": "integer", "default": 1},
                "end_line": {"type": "integer", "default": 200},
            },
            "required": ["path"],
        },
    },
    {
        "name": "glob_files",
        "description": "List project files matching a glob pattern (e.g., '**/*.cs').",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "max_results": {"type": "integer", "default": 50},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_files",
        "description": "Search a regex through files matching a glob.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python regex"},
                "glob": {"type": "string", "default": "*.cs"},
                "max_results": {"type": "integer", "default": 30},
            },
            "required": ["pattern"],
        },
    },
]

UNITYGRAPH_TOOLS = [
    {
        "name": "who_uses",
        "description": "Every inbound reference to a script: attachments, GetComponent/method callers, subclasses, UnityEvent listeners. Each carries evidence sites (file:line).",
        "input_schema": {
            "type": "object",
            "properties": {"script_name": {"type": "string"}},
            "required": ["script_name"],
        },
    },
    {
        "name": "inspector_overrides_for",
        "description": "Every Inspector-tuned field for a script across every scene/prefab attachment, with the code default for comparison.",
        "input_schema": {
            "type": "object",
            "properties": {"script_name": {"type": "string"}},
            "required": ["script_name"],
        },
    },
    {
        "name": "event_listeners",
        "description": "All UnityEvent callbacks bound to methods of a script (scene-YAML wirings — invisible to source-only readers).",
        "input_schema": {
            "type": "object",
            "properties": {"script_name": {"type": "string"}},
            "required": ["script_name"],
        },
    },
    {
        "name": "find_missing_scripts",
        "description": "Placeholder Script nodes — scene/prefab references to a script_guid that doesn't resolve.",
        "input_schema": {
            "type": "object",
            "properties": {"min_attachments": {"type": "integer", "default": 1}},
        },
    },
    {
        "name": "field_wiring",
        "description": "Every place a serialized field is wired in scenes/prefabs as a UnityEvent listener.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script_name": {"type": "string"},
                "field_name": {"type": "string"},
            },
            "required": ["script_name", "field_name"],
        },
    },
    {
        "name": "find_singletons",
        "description": "User-owned scripts attached to N+ GameObjects.",
        "input_schema": {
            "type": "object",
            "properties": {"min_attachments": {"type": "integer", "default": 2}},
        },
    },
]


def dispatch_tool(name: str, args: dict[str, Any]) -> str:
    fns = {
        "read_file": tool_read_file,
        "glob_files": tool_glob_files,
        "grep_files": tool_grep_files,
        "who_uses": tool_who_uses,
        "inspector_overrides_for": tool_inspector_overrides_for,
        "event_listeners": tool_event_listeners,
        "find_missing_scripts": tool_find_missing_scripts,
        "field_wiring": tool_field_wiring,
        "find_singletons": tool_find_singletons,
    }
    fn = fns.get(name)
    if fn is None:
        return f"ERROR: unknown tool {name}"
    try:
        return str(fn(**args))
    except Exception as exc:
        return f"ERROR: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


def run_agent(client: Anthropic, question: str, tools: list, label: str) -> dict:
    """Run a question through the agent loop, return final-answer + trace."""
    messages: list[dict] = [{"role": "user", "content": question}]
    trace: list[dict] = []
    final_text = ""
    for turn in range(MAX_TURNS):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )
        # Collect text + tool_use blocks
        tool_uses = []
        text_parts = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        if text_parts:
            final_text = "\n".join(text_parts)

        if resp.stop_reason == "end_turn" or not tool_uses:
            break

        # Append assistant response to message history
        messages.append({"role": "assistant", "content": resp.content})

        # Execute tools and add tool_result message
        tool_results = []
        for tu in tool_uses:
            t0 = time.time()
            output = dispatch_tool(tu.name, dict(tu.input))
            elapsed_ms = int((time.time() - t0) * 1000)
            trace.append(
                {
                    "turn": turn,
                    "tool": tu.name,
                    "input": dict(tu.input),
                    "output_len": len(output),
                    "elapsed_ms": elapsed_ms,
                }
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": output[:8000],
                }
            )
        messages.append({"role": "user", "content": tool_results})
    return {
        "label": label,
        "final_answer": final_text.strip(),
        "trace": trace,
        "n_turns": len(trace) + 1,
        "n_tool_calls": len(trace),
    }


def main() -> None:
    client = Anthropic()
    questions = json.loads(
        (Path(__file__).parent / "groundtruth.json").read_text(encoding="utf-8")
    )
    out: list[dict] = []
    for q in questions:
        print(f"\n=== {q['id']} (Tier {q['tier']}) ===", flush=True)
        print(q["question"], flush=True)

        baseline = run_agent(client, q["question"], FILE_TOOLS, "baseline")
        print(
            f"  [baseline] turns={baseline['n_turns']} tools={baseline['n_tool_calls']}",
            flush=True,
        )

        with_ug = run_agent(
            client, q["question"], FILE_TOOLS + UNITYGRAPH_TOOLS, "with_unitygraph"
        )
        print(
            f"  [with_unitygraph] turns={with_ug['n_turns']} tools={with_ug['n_tool_calls']}",
            flush=True,
        )

        out.append({"question": q, "baseline": baseline, "with_unitygraph": with_ug})

    out_path = Path(__file__).parent / "runs.json"
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
