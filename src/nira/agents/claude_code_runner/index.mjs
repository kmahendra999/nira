/**
 * Nira Claude Agent SDK runner.
 *
 * Reads one JSON request from stdin and writes one sentinel-delimited JSON
 * response to stdout.
 */

import { query } from "@anthropic-ai/claude-agent-sdk";

const OUTPUT_START = "---NIRA_OUTPUT_START---";
const OUTPUT_END = "---NIRA_OUTPUT_END---";

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

  const options = { maxTurns: 30 };
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
    options.sessionId = request.session_id;
  }

  // Every text block the assistant emits, in order. Accumulated rather than
  // overwritten: a turn can carry several text blocks, and an agentic run emits
  // text across many turns ("Let me check X" ... tool call ... "That shows Y").
  // Assigning instead of appending kept only the final block, so the fallback
  // below could silently drop the entire body of a reply.
  const textParts = [];
  let content = "";
  let messageCount = 0;
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
            }
          } else if (block.type === "tool_use") {
            toolUseIndexes.set(block.id, toolResults.length);
            toolResults.push({
              tool_name: block.name,
              content: serializeContent(block.input),
              success: true,
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
      }
    }

    emitResult({
      // A run can end without a result message (the stream simply finishes);
      // fall back to everything the assistant actually said.
      content: content || textParts.join("\n\n"),
      tool_results: toolResults,
      metadata: {
        message_count: messageCount,
        session_id: request.session_id || undefined,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    emitError(`Claude Agent SDK error: ${message}`);
    process.exitCode = 1;
  }
}

await main();
