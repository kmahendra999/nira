"""End-to-end tests for the Claude Agent SDK sidecar (``index.mjs``).

Every other test of this agent mocks ``subprocess.run``, so the sidecar's own
message-handling logic was never executed by the suite. That is how it shipped
assigning ``content = block.text`` instead of appending: a reply made of several
text blocks, or an agentic run that spoke across several turns, kept only the
final fragment.

These run the real file under Node against a stubbed ``@anthropic-ai/claude-agent-sdk``
that yields a scripted message stream, then parse the sentinel-delimited output
the Python side consumes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RUNNER_DIR = Path(__file__).resolve().parents[2] / "src/nira/agents/claude_code_runner"
OUTPUT_START = "---NIRA_OUTPUT_START---"
OUTPUT_END = "---NIRA_OUTPUT_END---"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="requires Node to run the sidecar"
)


def _build_sandbox(tmp_path: Path, messages: list[dict]) -> Path:
    """Copy the sidecar next to a stub SDK that replays *messages*."""
    shutil.copy(RUNNER_DIR / "index.mjs", tmp_path / "index.mjs")

    stub_pkg = tmp_path / "node_modules" / "@anthropic-ai" / "claude-agent-sdk"
    stub_pkg.mkdir(parents=True)
    (stub_pkg / "package.json").write_text(
        json.dumps(
            {
                "name": "@anthropic-ai/claude-agent-sdk",
                "type": "module",
                "version": "0.0.0-stub",
                "main": "index.mjs",
            }
        ),
        encoding="utf-8",
    )
    (stub_pkg / "index.mjs").write_text(
        "export const MESSAGES = "
        + json.dumps(messages)
        + ";\nexport async function* query() { for (const m of MESSAGES) yield m; }\n",
        encoding="utf-8",
    )
    return tmp_path


def _run(sandbox: Path, request: dict) -> dict:
    proc = subprocess.run(
        ["node", "index.mjs"],
        cwd=str(sandbox),
        input=json.dumps(request),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert OUTPUT_START in proc.stdout, (
        f"no sentinel in output: {proc.stdout!r} {proc.stderr!r}"
    )
    body = proc.stdout.split(OUTPUT_START, 1)[1].split(OUTPUT_END, 1)[0]
    return json.loads(body)


def _assistant(*texts: str) -> dict:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": t} for t in texts]},
    }


class TestTextAccumulation:
    def test_multiple_text_blocks_in_one_message_are_all_kept(self, tmp_path):
        sandbox = _build_sandbox(tmp_path, [_assistant("first part", "second part")])

        result = _run(sandbox, {"prompt": "hi"})

        assert "first part" in result["content"]
        assert "second part" in result["content"]

    def test_text_across_several_turns_is_all_kept(self, tmp_path):
        sandbox = _build_sandbox(
            tmp_path,
            [
                _assistant("Let me check the config."),
                _assistant("The timeout is 30 seconds."),
            ],
        )

        result = _run(sandbox, {"prompt": "what is the timeout?"})

        assert "Let me check the config." in result["content"]
        assert "The timeout is 30 seconds." in result["content"]

    def test_order_is_preserved(self, tmp_path):
        sandbox = _build_sandbox(
            tmp_path, [_assistant("alpha"), _assistant("beta"), _assistant("gamma")]
        )

        content = _run(sandbox, {"prompt": "go"})["content"]

        assert content.index("alpha") < content.index("beta") < content.index("gamma")

    def test_result_message_still_wins_when_present(self, tmp_path):
        """The SDK's final result is authoritative; accumulation is the fallback."""
        sandbox = _build_sandbox(
            tmp_path,
            [
                _assistant("thinking out loud"),
                {"type": "result", "subtype": "success", "result": "the final answer"},
            ],
        )

        assert _run(sandbox, {"prompt": "go"})["content"] == "the final answer"

    def test_falls_back_to_accumulated_text_when_result_is_empty(self, tmp_path):
        sandbox = _build_sandbox(
            tmp_path,
            [
                _assistant("everything the model said"),
                {"type": "result", "subtype": "success", "result": ""},
            ],
        )

        assert _run(sandbox, {"prompt": "go"})["content"] == "everything the model said"

    def test_empty_text_blocks_do_not_introduce_blank_padding(self, tmp_path):
        sandbox = _build_sandbox(tmp_path, [_assistant("", "real text", "")])

        assert _run(sandbox, {"prompt": "go"})["content"] == "real text"


class TestToolResults:
    def test_tool_use_is_backfilled_by_its_result(self, tmp_path):
        sandbox = _build_sandbox(
            tmp_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Reading the file."},
                            {
                                "type": "tool_use",
                                "id": "tu_1",
                                "name": "Read",
                                "input": {"path": "/tmp/x"},
                            },
                        ]
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tu_1",
                                "content": "file contents",
                                "is_error": False,
                            }
                        ]
                    },
                },
            ],
        )

        result = _run(sandbox, {"prompt": "read it"})

        assert "Reading the file." in result["content"]
        assert len(result["tool_results"]) == 1
        tool = result["tool_results"][0]
        assert tool["tool_name"] == "Read"
        assert tool["content"] == "file contents"
        assert tool["success"] is True

    def test_failed_tool_result_is_marked_unsuccessful(self, tmp_path):
        sandbox = _build_sandbox(
            tmp_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_1",
                                "name": "Read",
                                "input": {"path": "/nope"},
                            }
                        ]
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tu_1",
                                "content": "ENOENT",
                                "is_error": True,
                            }
                        ]
                    },
                },
            ],
        )

        tool = _run(sandbox, {"prompt": "read it"})["tool_results"][0]
        assert tool["success"] is False
        assert tool["content"] == "ENOENT"


class TestErrors:
    def test_error_result_is_reported(self, tmp_path):
        sandbox = _build_sandbox(
            tmp_path,
            [{"type": "result", "subtype": "error", "errors": ["quota exceeded"]}],
        )

        result = _run(sandbox, {"prompt": "go"})

        assert result["metadata"].get("error") is True
        assert "quota exceeded" in result["content"]

    def test_unparseable_stdin_is_reported(self, tmp_path):
        sandbox = _build_sandbox(tmp_path, [])
        proc = subprocess.run(
            ["node", "index.mjs"],
            cwd=str(sandbox),
            input="not json {{{",
            capture_output=True,
            text=True,
            timeout=60,
        )
        body = proc.stdout.split(OUTPUT_START, 1)[1].split(OUTPUT_END, 1)[0]
        result = json.loads(body)

        assert result["metadata"].get("error") is True
        assert "Failed to parse input" in result["content"]


# ---------------------------------------------------------------------------
# Permission prompts
# ---------------------------------------------------------------------------

EVENT_PREFIX = "---NIRA_EVENT---"


def _build_asking_sandbox(tmp_path: Path, tool: str = "Bash") -> Path:
    """A stub SDK that asks permission for one tool and reports the answer.

    Exercises the half of the sidecar that a replayed message list cannot: the
    SDK calling back into ``canUseTool`` and waiting on the host, which is what
    makes the approval queue reachable at all.
    """
    shutil.copy(RUNNER_DIR / "index.mjs", tmp_path / "index.mjs")
    stub_pkg = tmp_path / "node_modules" / "@anthropic-ai" / "claude-agent-sdk"
    stub_pkg.mkdir(parents=True)
    (stub_pkg / "package.json").write_text(
        json.dumps(
            {
                "name": "@anthropic-ai/claude-agent-sdk",
                "type": "module",
                "version": "0.0.0-stub",
                "main": "index.mjs",
            }
        ),
        encoding="utf-8",
    )
    (stub_pkg / "index.mjs").write_text(
        f"""
export async function* query({{ options }}) {{
  if (!options.canUseTool) {{
    yield {{ type: "assistant", message: {{ content: [
      {{ type: "text", text: "NO_CALLBACK" }} ] }} }};
    return;
  }}
  const verdict = await options.canUseTool(
    {json.dumps(tool)},
    {{ command: "rm -rf build" }},
    {{
      signal: new AbortController().signal,
      toolUseID: "tu_1",
      requestId: "rq_1",
      title: "Claude wants to run rm -rf build",
      displayName: "Run command",
    }},
  );
  yield {{ type: "assistant", message: {{ content: [
    {{ type: "text", text: "DECISION:" + JSON.stringify(verdict) }} ] }} }};
}}
""",
        encoding="utf-8",
    )
    return tmp_path


def _run_interactive(sandbox: Path, request: dict, answer=None, timeout: float = 30.0):
    """Run the sidecar keeping stdin open, answering any permission request.

    *answer* receives the request event and returns the decision to write back,
    or ``None`` to stay silent.
    """
    proc = subprocess.Popen(
        ["node", "index.mjs"],
        cwd=str(sandbox),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()

    asked: list[dict] = []
    collected: list[str] = []
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.startswith(EVENT_PREFIX):
                event = json.loads(line[len(EVENT_PREFIX) :])
                if event.get("type") == "permission_request":
                    asked.append(event)
                    decision = answer(event) if answer else None
                    if decision is not None:
                        for item in (
                            decision if isinstance(decision, list) else [decision]
                        ):
                            # A raw string goes down the pipe as-is, so a test
                            # can send something that is not JSON at all.
                            text = item if isinstance(item, str) else json.dumps(item)
                            proc.stdin.write(text + "\n")
                        proc.stdin.flush()
                    else:
                        # Nothing more is coming; closing is how the host says
                        # "you will not get an answer".
                        proc.stdin.close()
            else:
                collected.append(line)
    finally:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        proc.wait(timeout=timeout)

    stdout = "\n".join(collected)
    assert OUTPUT_START in stdout, f"no sentinel: {stdout!r} {proc.stderr.read()!r}"
    body = stdout.split(OUTPUT_START, 1)[1].split(OUTPUT_END, 1)[0]
    return asked, json.loads(body)


def _prefix_with_junk(answer):
    """Send an unparseable line before the real decision."""

    def wrapped(event):
        return ["this is not json", answer(event)]

    return wrapped


class TestPermissionPrompts:
    def test_nothing_is_asked_unless_the_host_asked_for_it(self, tmp_path):
        sandbox = _build_asking_sandbox(tmp_path)

        asked, result = _run_interactive(sandbox, {"prompt": "hi"})

        # A scheduled run with nobody watching must not stall on a question.
        assert asked == []
        assert "NO_CALLBACK" in result["content"]

    def test_a_tool_call_asks_the_host(self, tmp_path):
        sandbox = _build_asking_sandbox(tmp_path)

        asked, _ = _run_interactive(
            sandbox,
            {"prompt": "hi", "ask_permission": True},
            answer=lambda e: {"type": "decision", "id": e["id"], "behavior": "allow"},
        )

        assert len(asked) == 1
        assert asked[0]["tool"] == "Bash"
        assert asked[0]["input"] == {"command": "rm -rf build"}

    def test_the_question_carries_the_sentence_the_sdk_rendered(self, tmp_path):
        sandbox = _build_asking_sandbox(tmp_path)

        asked, _ = _run_interactive(
            sandbox,
            {"prompt": "hi", "ask_permission": True},
            answer=lambda e: {"type": "decision", "id": e["id"], "behavior": "allow"},
        )

        # Reconstructing a prompt from the tool name and its arguments would
        # be a worse version of a string the SDK already handed over.
        assert asked[0]["title"] == "Claude wants to run rm -rf build"
        assert asked[0]["display_name"] == "Run command"
        assert asked[0]["tool_use_id"] == "tu_1"

    def test_allowing_passes_the_input_through(self, tmp_path):
        sandbox = _build_asking_sandbox(tmp_path)

        _, result = _run_interactive(
            sandbox,
            {"prompt": "hi", "ask_permission": True},
            answer=lambda e: {"type": "decision", "id": e["id"], "behavior": "allow"},
        )

        verdict = json.loads(result["content"].split("DECISION:", 1)[1])
        assert verdict["behavior"] == "allow"
        assert verdict["updatedInput"] == {"command": "rm -rf build"}

    def test_denying_carries_the_reason_back_to_the_model(self, tmp_path):
        sandbox = _build_asking_sandbox(tmp_path)

        _, result = _run_interactive(
            sandbox,
            {"prompt": "hi", "ask_permission": True},
            answer=lambda e: {
                "type": "decision",
                "id": e["id"],
                "behavior": "deny",
                "message": "Not on this machine.",
            },
        )

        verdict = json.loads(result["content"].split("DECISION:", 1)[1])
        assert verdict["behavior"] == "deny"
        # The model sees this, so it has to read as a refusal rather than as a
        # tool failure worth retrying.
        assert verdict["message"] == "Not on this machine."

    def test_a_host_that_stops_listening_denies(self, tmp_path):
        sandbox = _build_asking_sandbox(tmp_path)

        _, result = _run_interactive(
            sandbox, {"prompt": "hi", "ask_permission": True}, answer=lambda e: None
        )

        # Closing stdin is how a dying host says nothing is coming. Parking
        # the tool call forever would keep the run alive indefinitely.
        verdict = json.loads(result["content"].split("DECISION:", 1)[1])
        assert verdict["behavior"] == "deny"

    def test_a_malformed_decision_does_not_break_the_run(self, tmp_path):
        sandbox = _build_asking_sandbox(tmp_path)
        junk_first = _prefix_with_junk(
            lambda e: {"type": "decision", "id": e["id"], "behavior": "allow"}
        )

        _, result = _run_interactive(
            sandbox, {"prompt": "hi", "ask_permission": True}, answer=junk_first
        )

        # A garbled line on the control channel must be skipped, not fatal: it
        # would take down a run that is otherwise working fine.
        decision = json.loads(result["content"].split("DECISION:", 1)[1])
        assert decision["behavior"] == "allow"

    def test_a_decision_for_an_unknown_request_is_ignored(self, tmp_path):
        sandbox = _build_asking_sandbox(tmp_path)

        def stale_then_real(event):
            return [
                {"type": "decision", "id": "perm_999", "behavior": "deny"},
                {"type": "decision", "id": event["id"], "behavior": "allow"},
            ]

        _, result = _run_interactive(
            sandbox, {"prompt": "hi", "ask_permission": True}, answer=stale_then_real
        )

        # An answer to a question this process never asked — a stale reply, or
        # one meant for another run — must not resolve the live one.
        decision = json.loads(result["content"].split("DECISION:", 1)[1])
        assert decision["behavior"] == "allow"
