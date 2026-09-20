/**
 * Nira Claude Agent SDK runner.
 *
 * Reads one JSON request from stdin, streams progress events as they happen,
 * and finishes with one sentinel-delimited JSON response.
 *
 * The streaming half matters more than it looks. The SDK hands us messages as
 * the agent works, and Nira has an event bus, an authenticated WebSocket and a
 * live trace UI all waiting for exactly those events — but this file used to
 * accumulate everything into locals and print a single blob at exit. During a
 * five-minute run the user saw nothing at all, then everything at once.
 *
 * Each event is one line, prefixed so the Python side can tell it apart from
 * whatever else a tool might print to stdout. The final sentinel block is
 * unchanged, so a caller that only reads the result still works.
 */

import { query } from "@anthropic-ai/claude-agent-sdk";

const OUTPUT_START = "---NIRA_OUTPUT_START---";
const OUTPUT_END = "---NIRA_OUTPUT_END---";
const EVENT_PREFIX = "---NIRA_EVENT---";

function emitEvent(event) {
  // One line, no pretty-printing: the reader splits on newlines.
  console.log(EVENT_PREFIX + JSON.stringify(event));
}

function emitResult(response) {
  console.log(OUTPUT_START);
  console.log(JSON.stringify(response));
  console.log(OUTPUT_END);
}

function emitError(message) {
  emitResult({ content: message, tool_results: [], metadata: { error: true } });
  console.error(message);
}

async function readStdin() {
  let data = "";
  process.stdin.setEncoding("utf-8");
  for await (const chunk of process.stdin) {
    data += chunk;
  }
  return data;
}

function serializeContent(content) {
  return typeof content === "string" ? content : JSON.stringify(content ?? "");
}

async function main() {
  let request;
  try {
    request = JSON.parse(await readStdin());
  } catch (error) {
    emitError(`Failed to parse input: ${error}`);
    process.exitCode = 1;
    return;
  }

  if (request.api_key) {
    process.env.ANTHROPIC_API_KEY = request.api_key;
  }

  // maxTurns was hardcoded to 30, which is low for "work on this project
  // until it is done" and not something the caller could change.
  const options = { maxTurns: request.max_turns ?? 30 };
  if (request.workspace) {
    options.cwd = request.workspace;
  }
  if (request.system_prompt) {
    options.systemPrompt = request.system_prompt;
  }
  if (request.allowed_tools?.length) {
    options.allowedTools = request.allowed_tools;
  }
  if (request.session_id) {
    // `resume`, not `sessionId`. The latter *assigns* an id to a new session;
    // it does not continue an existing one, so every follow-up was a cold
    // start that had forgotten the conversation it was supposedly part of.
    options.resume = request.session_id;
  }
  if (request.permission_mode) {
    options.permissionMode = request.permission_mode;
  }

  // Every text block the assistant emits, in order. Accumulated rather than
  // overwritten: a turn can carry several text blocks, and an agentic run emits
  // text across many turns ("Let me check X" ... tool call ... "That shows Y").
  // Assigning instead of appending kept only the final block, so the fallback
  // below could silently drop the entire body of a reply.
  const textParts = [];
  let content = "";
  let messageCount = 0;
  // The SDK's own session id, read off the result message. Echoing back the
  // caller's id told them nothing they did not already know, and left no way
  // to resume a session they had not invented an id for themselves.
  let sessionId = request.session_id || "";
  let turns = 0;
  const toolResults = [];
  const toolUseIndexes = new Map();

  try {
    for await (const message of query({ prompt: request.prompt, options })) {
      messageCount += 1;

      if (message.type === "assistant") {
        const blocks = Array.isArray(message.message?.content)
          ? message.message.content
          : [];
        for (const block of blocks) {
          if (block.type === "text") {
            if (block.text) {
              textParts.push(block.text);
              emitEvent({ type: "text", text: block.text });
            }
          } else if (block.type === "tool_use") {
            toolUseIndexes.set(block.id, toolResults.length);
            toolResults.push({
              tool_name: block.name,
              content: serializeContent(block.input),
              success: true,
            });
            emitEvent({
              type: "tool_start",
              id: block.id,
              tool: block.name,
              input: block.input ?? {},
            });
          }
        }
      } else if (message.type === "user") {
        const blocks = Array.isArray(message.message?.content)
          ? message.message.content
          : [];
        for (const block of blocks) {
          if (block.type !== "tool_result") {
            continue;
          }
          const index = toolUseIndexes.get(block.tool_use_id);
          if (index !== undefined) {
            toolResults[index].content = serializeContent(block.content);
            toolResults[index].success = !block.is_error;
            emitEvent({
              type: "tool_end",
              id: block.tool_use_id,
              tool: toolResults[index].tool_name,
              success: !block.is_error,
              result: serializeContent(block.content),
            });
          }
        }
      } else if (message.type === "result") {
        if (message.is_error || message.subtype !== "success") {
          const errorMessage =
            message.subtype === "success"
              ? message.result
              : message.errors?.join("\n");
          throw new Error(errorMessage || "Claude query failed");
        }
        content = message.result || textParts.join("\n\n");
        if (message.session_id) {
          sessionId = message.session_id;
        }
        if (typeof message.num_turns === "number") {
          turns = message.num_turns;
        }
      }
    }

    emitResult({
      // A run can end without a result message (the stream simply finishes);
      // fall back to everything the assistant actually said.
      content: content || textParts.join("\n\n"),
      tool_results: toolResults,
      metadata: {
        message_count: messageCount,
        session_id: sessionId || undefined,
        turns: turns || undefined,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    emitError(`Claude Agent SDK error: ${message}`);
    process.exitCode = 1;
  }
}

await main();
