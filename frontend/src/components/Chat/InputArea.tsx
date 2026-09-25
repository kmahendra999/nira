import { useState, useRef, useCallback, useEffect } from 'react';
import {
  Send,
  Square,
  Paperclip,
  Search,
  Brain,
  Zap,
  X,
  FileText,
  Image as ImageIcon,
} from 'lucide-react';
import { toast } from 'sonner';
import { useAppStore, generateId } from '../../lib/store';
import { streamChat, streamResearch } from '../../lib/sse';
import {
  fetchSavings,
  getBase,
  apiFetch,
  uploadChatAttachment,
  discardChatAttachment,
} from '../../lib/api';
import type { MessageAttachment } from '../../types';
import { listConnectors, getSyncStatus } from '../../lib/connectors-api';
import { serializeToolCallArguments } from '../../lib/tool-call';
import {
  engineFromCompletionChunk,
  resolveChatEngine,
} from '../../lib/chat-telemetry';
import { MicButton } from './MicButton';
import { useSpeech } from '../../hooks/useSpeech';
import type {
  ChatMessage,
  MessageTelemetry,
  ResearchSearchTrace,
  ResearchSource,
  TokenUsage,
  ToolCallInfo,
} from '../../types';

// While Deep Research is toggled on, poll connected sources for sync
// progress so we can surface "Searching over N items — sync in progress"
// next to the toggle. Polling is gated on `enabled` so toggling DR off
// stops the network chatter immediately.
function useResearchCorpusSync(enabled: boolean): {
  syncing: boolean;
  itemsSynced: number;
} {
  const [state, setState] = useState({ syncing: false, itemsSynced: 0 });

  useEffect(() => {
    if (!enabled) {
      setState({ syncing: false, itemsSynced: 0 });
      return;
    }
    let cancelled = false;

    const poll = async () => {
      try {
        const list = await listConnectors();
        const connected = list.filter((c) => c.connected);
        if (connected.length === 0) {
          if (!cancelled) setState({ syncing: false, itemsSynced: 0 });
          return;
        }
        const results = await Promise.all(
          connected.map(async (c) => {
            try {
              return await getSyncStatus(c.connector_id);
            } catch {
              return null;
            }
          }),
        );
        let syncing = false;
        let itemsSynced = 0;
        for (const r of results) {
          if (!r) continue;
          if (r.state === 'syncing') syncing = true;
          itemsSynced += r.items_synced ?? 0;
        }
        if (!cancelled) setState({ syncing, itemsSynced });
      } catch {
        // Network blip — leave previous state intact.
      }
    };

    poll();
    const interval = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [enabled]);

  return state;
}

export function InputArea() {
  const [input, setInput] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const activeId = useAppStore((s) => s.activeId);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const modelsLoading = useAppStore((s) => s.modelsLoading);
  const streamState = useAppStore((s) => s.streamState);
  const messages = useAppStore((s) => s.messages);
  const speechEnabled = useAppStore((s) => s.settings.speechEnabled);
  const maxTokens = useAppStore((s) => s.settings.maxTokens);
  const temperature = useAppStore((s) => s.settings.temperature);
  const createConversation = useAppStore((s) => s.createConversation);
  const addMessage = useAppStore((s) => s.addMessage);
  const updateLastAssistant = useAppStore((s) => s.updateLastAssistant);
  const setStreamState = useAppStore((s) => s.setStreamState);
  const resetStream = useAppStore((s) => s.resetStream);
  const modelLoading = useAppStore((s) => s.modelLoading);
  const deepResearch = useAppStore((s) => s.deepResearch);
  const agentMode = useAppStore((s) => s.agentMode);
  const setAgentMode = useAppStore((s) => s.setAgentMode);
  const models = useAppStore((s) => s.models);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const setDeepResearch = useAppStore((s) => s.setDeepResearch);
  const corpusSync = useResearchCorpusSync(deepResearch);
  const isCurrentChatStreaming = streamState.isStreaming && streamState.conversationId === activeId;

  const {
    state: speechState,
    error: speechError,
    available: speechAvailable,
    startRecording,
    stopRecording,
  } = useSpeech();

  // Abort in-flight stream when the user switches models mid-generation.
  // This prevents errors from trying to continue a stream with a stale model.
  const prevModelRef = useRef(selectedModel);
  useEffect(() => {
    if (prevModelRef.current !== selectedModel && streamState.isStreaming) {
      abortRef.current?.abort();
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      resetStream();
      abortRef.current = null;
    }
    prevModelRef.current = selectedModel;
  }, [selectedModel, streamState.isStreaming, resetStream]);

  const micDisabled = !speechEnabled || !speechAvailable || streamState.isStreaming;
  const micReason: 'not-enabled' | 'no-backend' | 'streaming' | undefined =
    !speechEnabled ? 'not-enabled'
    : !speechAvailable ? 'no-backend'
    : streamState.isStreaming ? 'streaming'
    : undefined;

  useEffect(() => {
    if (speechError) {
      toast.error(speechError, { duration: 8000 });
    }
  }, [speechError]);

  const handleMicClick = useCallback(async () => {
    if (speechState === 'recording') {
      try {
        const text = await stopRecording();
        if (text) {
          setInput((prev) => (prev ? prev + ' ' + text : text));
        }
      } catch {
        // Error is captured in useSpeech
      }
    } else {
      await startRecording();
    }
  }, [speechState, startRecording, stopRecording]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }, [input]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    resetStream();
  }, [resetStream]);

  // Files staged for the next message. Not persisted: they are a draft, and
  // the bytes live on the server behind these ids anyway.
  const [pending, setPending] = useState<MessageAttachment[]>([]);
  const [uploading, setUploading] = useState(0);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const attachFiles = useCallback(async (files: FileList | File[]) => {
    const chosen = Array.from(files);
    if (!chosen.length) return;
    setUploading((n) => n + chosen.length);
    for (const file of chosen) {
      try {
        const attachment = await uploadChatAttachment(file);
        setPending((current) => [...current, attachment]);
        if (attachment.truncated && attachment.notes?.length) {
          // Say what was cut at the moment it is cut, rather than letting the
          // model answer confidently about a document it half read.
          toast.warning(`${attachment.filename} was shortened`, {
            description: attachment.notes.join(' '),
            duration: 8000,
          });
        }
      } catch (err: any) {
        toast.error(err?.message ?? `Could not attach ${file.name}`, {
          duration: 8000,
        });
      } finally {
        setUploading((n) => Math.max(0, n - 1));
      }
    }
  }, []);

  const removeAttachment = useCallback((id: string) => {
    setPending((current) => current.filter((a) => a.id !== id));
    void discardChatAttachment(id);
  }, []);

  const sendMessage = useCallback(async () => {
    const content = input.trim();
    // An attachment on its own is a complete message: "read this" is the
    // whole request. Requiring text would mean typing a word to send a file.
    if ((!content && pending.length === 0) || streamState.isStreaming) return;
    if (uploading > 0) {
      toast.error('Still uploading — one moment');
      return;
    }
    if (!selectedModel) {
      toast.error('Pick a model first (⌘K)');
      return;
    }

    setInput('');

    let convId = activeId;
    if (!convId) {
      convId = createConversation(selectedModel);
    }

    // Snapshot and clear now: the request is in flight for a while, and a
    // second send must not re-attach the same files.
    const sending = pending;
    setPending([]);

    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content,
      timestamp: Date.now(),
      attachments: sending.length ? sending : undefined,
    };
    addMessage(convId, userMsg);

    // Build API messages before adding assistant placeholder
    const currentMessages = useAppStore.getState().messages;
    const apiMessages = currentMessages.map((m, index) => ({
      role: m.role,
      content: m.content,
      // Only the message being sent carries ids. Re-sending them on every
      // turn would re-resolve the same files and append their text again,
      // growing the prompt each turn and re-billing a vision model for an
      // image it already saw. The server folds the text into content, so
      // earlier turns keep their attachments as ordinary words.
      ...(index === currentMessages.length - 1 && sending.length
        ? { attachment_ids: sending.map((a) => a.id) }
        : {}),
    }));

    const assistantMsg: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      isResearch: deepResearch || undefined,
    };
    addMessage(convId, assistantMsg);

    // Start streaming
    const startTime = Date.now();
    const timer = setInterval(() => {
      setStreamState({ elapsedMs: Date.now() - startTime });
    }, 100);
    timerRef.current = timer;

    const controller = new AbortController();
    abortRef.current = controller;

    let accumulatedContent = '';
    let usage: TokenUsage | undefined;
    let complexity: { score: number; tier: string; suggested_max_tokens: number } | undefined;
    let routedEngine: string | undefined;
    const toolCalls: ToolCallInfo[] = [];
    const researchTraces: ResearchSearchTrace[] = [];
    const researchSourcesByRef = new Map<number, ResearchSource>();
    const flushSources = () =>
      Array.from(researchSourcesByRef.values()).sort((a, b) => a.ref - b.ref);
    let lastFlush = 0;
    let ttftMs: number | undefined;

    setStreamState({
      conversationId: convId,
      isStreaming: true,
      phase: deepResearch ? 'Researching...' : 'Generating...',
      elapsedMs: 0,
      activeToolCalls: [],
      content: '',
    });
    useAppStore.getState().addLogEntry({
      timestamp: Date.now(),
      level: 'info',
      category: 'chat',
      message: deepResearch
        ? `Research: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}"`
        : `Request: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}" → ${selectedModel}`,
    });

    try {
      if (deepResearch) {
        for await (const ev of streamResearch(
          content,
          selectedModel,
          controller.signal,
        )) {
          if (ev.type === 'search_call') {
            const trace: ResearchSearchTrace = {
              id: generateId(),
              query: ev.arguments?.query ?? '',
              person: ev.arguments?.person,
              timeRange: ev.arguments?.time_range,
              status: 'pending',
            };
            researchTraces.push(trace);
            setStreamState({ phase: `Searching: ${trace.query}` });
            updateLastAssistant(
              convId,
              accumulatedContent,
              undefined,
              undefined,
              undefined,
              undefined,
              [...researchTraces],
              flushSources(),
            );
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(),
              level: 'info',
              category: 'tool',
              message: `Search: "${trace.query}"${trace.person ? ` (person: ${trace.person})` : ''}`,
            });
          } else if (ev.type === 'search_result') {
            const pending = [...researchTraces].reverse().find((t) => t.status === 'pending');
            if (pending) {
              pending.status = 'complete';
              pending.numHits = ev.num_hits;
              pending.topTitles = ev.top_titles;
            }
            if (ev.sources) {
              for (const src of ev.sources) {
                if (src && typeof src.ref === 'number' && !researchSourcesByRef.has(src.ref)) {
                  researchSourcesByRef.set(src.ref, src);
                }
              }
            }
            updateLastAssistant(
              convId,
              accumulatedContent,
              undefined,
              undefined,
              undefined,
              undefined,
              [...researchTraces],
              flushSources(),
            );
          } else if (ev.type === 'synthesis') {
            if (!ttftMs) ttftMs = Date.now() - startTime;
            accumulatedContent += ev.text;
            setStreamState({ content: accumulatedContent, phase: '' });
            const now = Date.now();
            if (now - lastFlush >= 80) {
              updateLastAssistant(
                convId,
                accumulatedContent,
                undefined,
                undefined,
                undefined,
                undefined,
                [...researchTraces],
                flushSources(),
              );
              lastFlush = now;
            }
          } else if (ev.type === 'system_metrics') {
            // Live GPU sample — feed straight to the System panel so Power
            // (W) and Energy (kJ) tick up in real time as the agent runs.
            useAppStore.getState().setLiveEnergy({
              power_w: ev.power_w,
              energy_j: ev.energy_j,
              duration_s: ev.duration_s,
            });
          } else if (ev.type === 'error') {
            // Backend setup/worker failure (Ollama down, planner model
            // missing, KnowledgeStore locked, etc.). Without surfacing the
            // message, the user sees only the generic "No response was
            // generated" fallback and has no way to self-diagnose.
            const msg = ev.message || 'Research failed (no detail provided)';
            accumulatedContent = accumulatedContent
              ? `${accumulatedContent}\n\n**Research stopped:** ${msg}`
              : `**Research failed:** ${msg}`;
            setStreamState({ content: accumulatedContent, phase: '' });
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(),
              level: 'error',
              category: 'chat',
              message: `Deep Research error: ${msg}`,
            });
            toast.error(msg, { duration: 8000 });
          } else if (ev.type === 'done') {
            if (ev.usage) {
              usage = {
                prompt_tokens: ev.usage.prompt_tokens ?? 0,
                completion_tokens: ev.usage.completion_tokens ?? 0,
                total_tokens:
                  ev.usage.total_tokens ??
                  (ev.usage.prompt_tokens ?? 0) +
                    (ev.usage.completion_tokens ?? 0),
              };
              // Optimistically roll this research turn into the session
              // counters so the Session panel updates the moment the
              // stream finishes, regardless of how /v1/savings aggregates
              // research telemetry server-side.
              useAppStore.getState().incrementSavings(usage);
            }
            // Hold the final live numbers visible for a beat so the panel
            // doesn't flash to 0 between the SSE close and the next
            // /v1/telemetry/energy poll picking up the persisted record.
            window.setTimeout(() => {
              useAppStore.getState().setLiveEnergy(null);
            }, 1500);
            break;
          }
        }
      } else {
      for await (const sseEvent of streamChat(
        {
          model: selectedModel,
          messages: apiMessages,
          stream: true,
          temperature,
          max_tokens: maxTokens,
          use_agent: agentMode,
        },
        controller.signal,
      )) {
        const eventName = sseEvent.event;

        if (eventName === 'agent_turn_start') {
          setStreamState({ phase: 'Agent thinking...' });
        } else if (eventName === 'inference_start') {
          setStreamState({ phase: 'Generating...' });
          useAppStore.getState().addLogEntry({
            timestamp: Date.now(), level: 'info', category: 'chat',
            message: `Generating with ${selectedModel}...`,
          });
        } else if (eventName === 'tool_call_start') {
          try {
            const data = JSON.parse(sseEvent.data);
            const tc: ToolCallInfo = {
              id: generateId(),
              tool: data.tool,
              arguments: serializeToolCallArguments(data.arguments),
              status: 'running',
            };
            toolCalls.push(tc);
            setStreamState({
              phase: `Calling ${data.tool}...`,
              activeToolCalls: [...toolCalls],
            });
            updateLastAssistant(convId, accumulatedContent, [...toolCalls]);
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(), level: 'info', category: 'tool',
              message: `Calling ${data.tool}(${serializeToolCallArguments(data.arguments)})`,
            });
          } catch {}
        } else if (eventName === 'tool_call_end') {
          try {
            const data = JSON.parse(sseEvent.data);
            const tc = toolCalls.find(
              (t) => t.tool === data.tool && t.status === 'running',
            );
            if (tc) {
              tc.status = data.success ? 'success' : 'error';
              tc.latency = data.latency;
              tc.result = data.result;
            }
            setStreamState({
              phase: 'Generating...',
              activeToolCalls: [...toolCalls],
            });
            updateLastAssistant(convId, accumulatedContent, [...toolCalls]);
          } catch {}
        } else {
          try {
            const data = JSON.parse(sseEvent.data);
            const delta = data.choices?.[0]?.delta;
            if (data.usage) usage = data.usage;
            if (data.complexity) complexity = data.complexity;
            routedEngine = engineFromCompletionChunk(data) ?? routedEngine;
            if (delta?.content) {
              if (!ttftMs) ttftMs = Date.now() - startTime;
              accumulatedContent += delta.content;
              setStreamState({ content: accumulatedContent, phase: '' });

              const now = Date.now();
              if (now - lastFlush >= 80) {
                updateLastAssistant(
                  convId,
                  accumulatedContent,
                  toolCalls.length > 0 ? [...toolCalls] : undefined,
                );
                lastFlush = now;
              }
            }
            if (data.choices?.[0]?.finish_reason === 'stop') break;
          } catch {}
        }
      }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        // User cancelled or model switch — keep whatever was accumulated
        if (!accumulatedContent) accumulatedContent = '(Generation stopped)';
      } else {
        const errMsg = err?.message || String(err);
        accumulatedContent =
          accumulatedContent || `Error: ${errMsg}`;
        useAppStore.getState().addLogEntry({
          timestamp: Date.now(), level: 'error', category: 'chat',
          message: `Stream error: ${errMsg}`,
        });
      }
      // If we tore out mid-research, make sure the live System panel
      // numbers don't get stuck on the last sample.
      useAppStore.getState().setLiveEnergy(null);
    } finally {
      if (!accumulatedContent) {
        accumulatedContent = 'No response was generated. Please try again.';
      }
      const totalMs = Date.now() - startTime;
      const appState = useAppStore.getState();
      const selectedOwner = appState.models.find((m) => m.id === selectedModel)?.owned_by;
      const engineLabel = resolveChatEngine({
        routedEngine,
        serverEngine: appState.serverInfo?.engine,
        selectedModel,
        selectedOwner,
      });
      const telemetry: MessageTelemetry = {
        engine: engineLabel,
        model_id: selectedModel,
        total_ms: totalMs,
        ttft_ms: ttftMs,
        tokens_per_sec: usage?.completion_tokens
          ? usage.completion_tokens / (totalMs / 1000)
          : undefined,
        complexity_score: complexity?.score,
        complexity_tier: complexity?.tier,
        suggested_max_tokens: complexity?.suggested_max_tokens,
      };
      // Check if the response has digest audio available
      let audioMeta: { url: string } | undefined;
      try {
        const digestRes = await apiFetch(`/api/digest`);
        if (digestRes.ok) {
          const digest = await digestRes.json();
          if (digest.audio_available) {
            audioMeta = { url: `${getBase()}/api/digest/audio` };
          }
        }
      } catch {
        // Not a digest response or server unavailable — skip
      }

      updateLastAssistant(
        convId,
        accumulatedContent,
        toolCalls.length > 0 ? toolCalls : undefined,
        usage,
        telemetry,
        audioMeta,
        researchTraces.length > 0 ? researchTraces : undefined,
        researchSourcesByRef.size > 0 ? flushSources() : undefined,
      );
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      resetStream();
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'chat',
        message: `Response: ${accumulatedContent.length} chars`,
      });
      abortRef.current = null;

      // Research path updates session counters optimistically from the
      // `done` event's usage payload — re-fetching here would overwrite
      // it with a potentially stale snapshot if the server's research
      // telemetry hasn't been merged into /v1/savings yet.
      if (!deepResearch) {
        fetchSavings()
          .then((data) => useAppStore.getState().setSavings(data))
          .catch(() => {});
      }
    }
  }, [
    input,
    activeId,
    selectedModel,
    streamState.isStreaming,
    createConversation,
    addMessage,
    updateLastAssistant,
    setStreamState,
    resetStream,
    deepResearch,
    temperature,
    maxTokens,
  ]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="px-4 pb-4 pt-2" style={{ maxWidth: 'var(--chat-max-width)', margin: '0 auto', width: '100%' }}>
      <div className="mb-2 flex flex-col gap-1">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Model, where the message is written rather than behind ⌘K.
              A native select on purpose: it is keyboard accessible, it opens
              above the fold on a short window, and its popup is drawn by the
              browser so no ancestor can clip it. */}
          <label className="sr-only" htmlFor="chat-model">
            Model
          </label>
          <select
            id="chat-model"
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            disabled={streamState.isStreaming}
            className="hud-focusable readout px-2.5 py-1 rounded-full text-xs cursor-pointer disabled:cursor-default disabled:opacity-50"
            style={{
              background: 'transparent',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-secondary)',
              maxWidth: 180,
            }}
            title="Which model answers"
          >
            {/* A selection that outlived a failed fetch still has no
                matching <option>, and a <select> whose value matches
                nothing renders its first option instead — so the model
                that would actually answer displayed as "No models".
                Keep an option for it. */}
            {models.length === 0 && selectedModel && (
              <option value={selectedModel}>{selectedModel}</option>
            )}
            {models.length === 0 && !selectedModel && (
              <option value="">
                {modelsLoading ? 'Loading models…' : 'No models'}
              </option>
            )}
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}
              </option>
            ))}
          </select>

          {/* Agent vs a straight answer. Named for what the reader gets, not
              for the flag: "Learning" is the one that uses tools, writes to
              memory and feeds the learning loop. */}
          <button
            type="button"
            onClick={() => setAgentMode(!agentMode)}
            disabled={streamState.isStreaming}
            aria-pressed={agentMode}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-colors cursor-pointer disabled:cursor-default disabled:opacity-50"
            style={{
              background: agentMode ? 'var(--color-accent-subtle)' : 'transparent',
              border: `1px solid ${agentMode ? 'var(--color-accent)' : 'var(--color-border)'}`,
              color: agentMode ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
            }}
            title={
              agentMode
                ? 'Learning: uses tools and memory, and remembers the outcome'
                : 'Just answer: straight from the model, nothing recorded'
            }
          >
            {agentMode ? <Brain size={12} /> : <Zap size={12} />}
            {agentMode ? 'Learning' : 'Just answer'}
          </button>

          <button
            type="button"
            onClick={() => setDeepResearch(!deepResearch)}
            disabled={streamState.isStreaming}
            aria-pressed={deepResearch}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-colors cursor-pointer disabled:cursor-default disabled:opacity-50"
            style={{
              background: deepResearch ? 'var(--color-accent-subtle)' : 'transparent',
              border: `1px solid ${deepResearch ? 'var(--color-accent)' : 'var(--color-border)'}`,
              color: deepResearch ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
            }}
            title={deepResearch ? 'Deep Research: on' : 'Deep Research: off'}
          >
            <Search size={12} />
            Deep Research
          </button>
        </div>
        {deepResearch && corpusSync.syncing && corpusSync.itemsSynced > 0 && (
          <div
            className="text-[11px] leading-snug"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            Searching over{' '}
            <span key={corpusSync.itemsSynced} className="sync-bump" style={{ color: 'var(--color-text-secondary)' }}>
              {corpusSync.itemsSynced.toLocaleString()}
            </span>{' '}
            items — sync in progress, results will improve as more data is indexed.
          </div>
        )}
      </div>
      <div
        className="flex flex-col gap-2 rounded-2xl px-4 py-3 transition-shadow
          border focus-within:border-accent"
        style={{
          background: 'var(--color-input-bg)',
          boxShadow: 'var(--shadow-sm)',
          borderColor: dragging ? 'var(--color-accent)' : 'var(--color-input-border)',
        }}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes('Files')) return;
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={(e) => {
          // Only when the pointer actually left the box, not when it crossed
          // onto a child element.
          if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false);
        }}
        onDrop={(e) => {
          if (!e.dataTransfer.files?.length) return;
          e.preventDefault();
          setDragging(false);
          void attachFiles(e.dataTransfer.files);
        }}
      >
        {(pending.length > 0 || uploading > 0) && (
          <div className="flex flex-wrap gap-1.5">
            {pending.map((attachment) => (
              <span
                key={attachment.id}
                className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px]"
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-secondary)',
                }}
                title={
                  attachment.notes?.length
                    ? attachment.notes.join(' ')
                    : `${(attachment.size / 1024).toFixed(0)} KB`
                }
              >
                {attachment.kind === 'image' ? (
                  <ImageIcon size={11} style={{ color: 'var(--color-accent)' }} />
                ) : (
                  <FileText size={11} style={{ color: 'var(--color-accent)' }} />
                )}
                <span className="max-w-[160px] truncate">{attachment.filename}</span>
                {attachment.truncated && (
                  <span style={{ color: 'var(--color-warning, var(--color-text-tertiary))' }}>
                    shortened
                  </span>
                )}
                <button
                  onClick={() => removeAttachment(attachment.id)}
                  className="cursor-pointer"
                  style={{ color: 'var(--color-text-tertiary)' }}
                  title={`Remove ${attachment.filename}`}
                >
                  <X size={11} />
                </button>
              </span>
            ))}
            {uploading > 0 && (
              <span
                className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px]"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                Reading {uploading} file{uploading === 1 ? '' : 's'}…
              </span>
            )}
          </div>
        )}
        <div className="flex items-center gap-2">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files) void attachFiles(e.target.files);
            // Reset so choosing the same file twice still fires onChange.
            e.target.value = '';
          }}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={streamState.isStreaming}
          className="p-1.5 rounded-lg transition-colors shrink-0 cursor-pointer disabled:opacity-50"
          style={{ color: 'var(--color-text-tertiary)' }}
          title="Attach a file — images, PDF, Word, Excel, CSV, text"
        >
          <Paperclip size={16} />
        </button>
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={selectedModel ? 'Message Nira...' : 'Pick a model first (⌘K)...'}
          rows={1}
          className="flex-1 bg-transparent outline-none resize-none text-sm leading-relaxed"
          style={{ color: 'var(--color-text)', maxHeight: '200px' }}
          disabled={streamState.isStreaming || modelLoading}
        />
        {isCurrentChatStreaming ? (
          <button
            onClick={stopStreaming}
            className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer"
            style={{ background: 'var(--color-error)', color: 'var(--color-on-accent)' }}
            title="Stop generating"
          >
            <Square size={16} />
          </button>
        ) : (
          <div className="flex items-center gap-1">
            <MicButton
              state={speechState}
              onClick={handleMicClick}
              disabled={micDisabled}
              reason={micReason}
            />
            <button
              onClick={sendMessage}
              disabled={
                streamState.isStreaming ||
                (!input.trim() && pending.length === 0) ||
                uploading > 0 ||
                modelLoading ||
                !selectedModel
              }
              title={selectedModel ? 'Send message' : 'Pick a model first (⌘K)'}
              className="p-2 rounded-xl transition-colors shrink-0 cursor-pointer disabled:opacity-30 disabled:cursor-default"
              style={{
                background:
                  input.trim() || pending.length
                    ? 'var(--color-accent)'
                    : 'var(--color-bg-tertiary)',
                color:
                  input.trim() || pending.length ? 'white' : 'var(--color-text-tertiary)',
              }}
            >
              <Send size={16} />
            </button>
          </div>
        )}
        </div>
      </div>
      <div className="flex items-center justify-center mt-2 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>
          <kbd className="font-mono">Enter</kbd> to send &middot;{' '}
          <kbd className="font-mono">Shift+Enter</kbd> for new line
        </span>
      </div>
    </div>
  );
}
