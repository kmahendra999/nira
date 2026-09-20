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
