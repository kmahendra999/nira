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

import { createInterface } from "node:readline";

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

/**
 * Decisions this process is still waiting on, by request id.
 *
 * Asking the user whether a tool may run means the answer arrives *after* the
 * request did, so stdin has to stay open and be read a line at a time. It used
 * to be drained in one go and closed, which is fine for a one-shot request and
 * makes a conversation impossible.
 */
const pendingPermissions = new Map();

/**
 * The stdin reader, kept so it can be shut down.
 *
 * readline holds the event loop open for as long as it is listening. Leaving
 * it running past the end of the run means the process never exits, its stdout
 * never reaches end-of-file, and the host waits forever for output from a
 * sidecar that finished long ago — a deadlock in every run, not only the ones
 * that ask a question.
 */
let channel = null;

function closeChannel() {
  channel?.close();
  channel = null;
}

/** Resolves with the first line on stdin — the request — and routes the rest. */
function openChannel() {
  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  channel = lines;
  return new Promise((resolve, reject) => {
    let request;
    lines.on("line", (line) => {
      const text = line.trim();
      if (!text) return;
      if (request === undefined) {
        try {
          request = JSON.parse(text);
        } catch (error) {
          reject(error);
          return;
        }
        resolve(request);
        return;
      }
      let message;
      try {
        message = JSON.parse(text);
      } catch {
        // A malformed decision must not take down a run that is working.
        return;
      }
      if (message?.type === "decision") {
        const settle = pendingPermissions.get(message.id);
        if (settle) {
          pendingPermissions.delete(message.id);
          settle(message);
        }
      }
    });
    lines.on("close", () => {
      if (request === undefined) reject(new Error("no request on stdin"));
      // Anything still waiting will never be answered now. Deny rather than
      // hang: the host has gone away, and a parked tool call would keep the
      // run alive indefinitely.
      for (const [id, settle] of pendingPermissions) {
        pendingPermissions.delete(id);
        settle({ behavior: "deny", message: "Nira stopped listening." });
      }
    });
  });
}

let permissionCounter = 0;

/** Ask the host whether a tool may run, and wait for the answer. */
function askPermission(detail, signal) {
  const id = `perm_${++permissionCounter}`;
  return new Promise((resolve) => {
    const settle = (decision) => {
      signal?.removeEventListener?.("abort", onAbort);
      resolve(decision);
    };
    function onAbort() {
      pendingPermissions.delete(id);
      settle({ behavior: "deny", message: "The run was cancelled." });
    }
    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener?.("abort", onAbort, { once: true });
    pendingPermissions.set(id, settle);
    emitEvent({ type: "permission_request", id, ...detail });
  });
}

function serializeContent(content) {
  return typeof content === "string" ? content : JSON.stringify(content ?? "");
}

async function main() {
  let request;
  try {
    request = await openChannel();
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
  } else if (request.ask_permission) {
    // "default" is the only mode that prompts for dangerous operations, and
    // prompting is the entire point of setting canUseTool below. Leaving the
    // mode unset means the SDK follows whatever the ambient settings allow,
    // and the callback is wired to something that never fires — a permission
    // prompt nobody can reach is exactly the state this phase set out to fix.
    options.permissionMode = "default";
  }

  // Route "should this be allowed?" back to the host instead of letting the
  // SDK decide alone. Without a canUseTool the SDK treats an ask as terminal,
  // so a risky step was silently refused and nobody was ever given the chance
  // to say yes — the approval queue, its endpoints and its `approve` scope all
  // existed with nothing to put in them.
  if (request.ask_permission) {
    options.canUseTool = async (toolName, input, context) => {
      const decision = await askPermission(
        {
          tool: toolName,
          input: input ?? {},
          // The SDK renders the prompt sentence itself. Reconstructing one
          // from the tool name and its arguments would be a worse version of
          // a string it already handed us.
          title: context?.title ?? "",
          display_name: context?.displayName ?? "",
          description: context?.description ?? "",
          reason: context?.decisionReason ?? "",
          blocked_path: context?.blockedPath ?? "",
          tool_use_id: context?.toolUseID ?? "",
        },
        context?.signal,
      );
      if (decision.behavior === "allow") {
        return { behavior: "allow", updatedInput: input ?? {} };
      }
      return {
        behavior: "deny",
        message: decision.message || "Refused by the user.",
      };
    };
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

    closeChannel();
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
    closeChannel();
    const message = error instanceof Error ? error.message : String(error);
    emitError(`Claude Agent SDK error: ${message}`);
    process.exitCode = 1;
  }
}

await main();
