import { create } from 'zustand';
import type {
  Conversation,
  ChatMessage,
  LiveEnergyMetrics,
  LogEntry,
  ModelInfo,
  MessageTelemetry,
  ResearchSearchTrace,
  ResearchSource,
  SavingsData,
  ServerInfo,
  StreamState,
  ToolCallInfo,
  TokenUsage,
} from '../types';
import type { ManagedAgent } from './api';
import { isEmbedOnlyModel } from './model-capabilities';
import { serializeToolCallArguments } from './tool-call';

export interface CachedConnector {
  connector_id: string;
  display_name: string;
  connected: boolean;
  chunks: number;
  auth_type: string;
}

export interface AgentEvent {
  type: string;
  timestamp: number;
  data: Record<string, unknown>;
}

// ── localStorage persistence ──────────────────────────────────────────

const CONVERSATIONS_KEY = 'nira-conversations';
const SETTINGS_KEY = 'nira-settings';
const OPTIN_KEY = 'nira-optin';
const OPTIN_NAME_KEY = 'nira-display-name';
const OPTIN_EMAIL_KEY = 'nira-email';
const OPTIN_ANONID_KEY = 'nira-anon-id';
const OPTIN_SEEN_KEY = 'nira-optin-seen';

interface ConversationStore {
  version: 1;
  conversations: Record<string, Conversation>;
  activeId: string | null;
}

function generateId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function loadConversations(): ConversationStore {
  try {
    const raw = localStorage.getItem(CONVERSATIONS_KEY);
    if (!raw) return { version: 1, conversations: {}, activeId: null };
    const parsed = JSON.parse(raw);
    if (parsed.version === 1) {
      let repaired = false;
      for (const conversation of Object.values(parsed.conversations ?? {}) as Conversation[]) {
        for (const message of conversation.messages ?? []) {
          for (const toolCall of message.toolCalls ?? []) {
            const argumentsText = serializeToolCallArguments(toolCall.arguments);
            if (argumentsText !== toolCall.arguments) {
              toolCall.arguments = argumentsText;
              repaired = true;
            }
          }
        }
      }
      if (repaired) {
        try {
          localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(parsed));
        } catch {
          // Keep the repaired conversations usable in memory when storage is
          // read-only or full. A failed best-effort writeback must not make
          // otherwise readable conversation history disappear from the UI.
        }
      }
      return parsed;
    }
    return { version: 1, conversations: {}, activeId: null };
  } catch {
    return { version: 1, conversations: {}, activeId: null };
  }
}

// localStorage is finite and conversations are the thing that fills it: every
// assistant message carries its full tool-call results, and the whole store is
// rewritten on each flush. This write had no try/catch, so on
// QuotaExceededError the throw escaped saveConversations, escaped
// addMessage/updateLastAssistant, and landed in the stream loop — which
// swallows it. The visible result was a reply that stopped mid-sentence and a
// message that was never saved, with nothing anywhere saying storage was full.

export type StorageWarning =
  | { kind: 'trimmed'; conversations: number }
  | { kind: 'pruned'; removed: number }
  | { kind: 'full' }
  | { kind: 'unavailable'; detail: string };

type StorageWarningListener = (warning: StorageWarning) => void;
const storageWarningListeners = new Set<StorageWarningListener>();

export function onStorageWarning(listener: StorageWarningListener): () => void {
  storageWarningListeners.add(listener);
  return () => storageWarningListeners.delete(listener);
}

function emitStorageWarning(warning: StorageWarning): void {
  for (const listener of storageWarningListeners) {
    try {
      listener(warning);
    } catch {
      // One bad listener must not stop the others, or fail the write.
    }
  }
}

// One reply must not be able to consume the archive. See stage 2 below.
const DELETION_COOLDOWN_MS = 60_000;
let lastDeletionAt = 0;

/** Exported for tests; forgets the deletion rate limit. */
export function resetStorageReclaimThrottle(): void {
  lastDeletionAt = 0;
}

/** Whether an exception is the browser saying "out of room". */
function isQuotaError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  // Chrome/WebKit name it; Firefox uses its own name; older Safari reports
  // only a numeric code. A DOMException carries `code`, a plain Error does not.
  const code = (err as unknown as { code?: number }).code;
  return (
    err.name === 'QuotaExceededError' ||
    err.name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
    code === 22 ||
    code === 1014
  );
}

/**
 * Persist conversations, reclaiming room if the write does not fit.
 *
 * `protectId` is the conversation this write is about — it is never touched,
 * because deleting the thing being saved to make room to save it is absurd.
 * It defaults to the active conversation, but callers that write to a
 * different one (the overlay import) must say so.
 *
 * Reclaims in two stages, because the two costs are very different:
 *
 *   1. Strip the heavy attachments — tool-call results, research traces and
 *      sources — from the oldest conversations. This is where the bytes
 *      actually are: a single tool result can dwarf an entire conversation's
 *      text. The messages stay readable, which is what people came for.
 *   2. Only if that is not enough, delete whole conversations, oldest first.
 *
 * Returns false when nothing could be written. Callers keep their in-memory
 * state either way — losing the running conversation because the disk is full
 * would be strictly worse than a stale file.
 */
function saveConversations(
  store: ConversationStore,
  protectId?: string | null,
): boolean {
  const write = (): boolean => {
    localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(store));
    return true;
  };

  try {
    return write();
  } catch (err) {
    if (!isQuotaError(err)) {
      // Private browsing, blocked site data, a disabled storage API: nothing
      // to reclaim our way out of.
      emitStorageWarning({
        kind: 'unavailable',
        detail: err instanceof Error ? err.message : String(err),
      });
      return false;
    }
  }

  const keepId = protectId ?? store.activeId;
  const oldestFirst = () =>
    Object.values(store.conversations)
      .filter((c) => c.id !== keepId)
      .sort((a, b) => a.updatedAt - b.updatedAt);

  // Stage 1 — drop attachments, keep the words.
  let trimmed = 0;
  for (const conversation of oldestFirst()) {
    let changed = false;
    for (const message of conversation.messages ?? []) {
      if (message.toolCalls || message.researchTraces || message.researchSources) {
        delete message.toolCalls;
        delete message.researchTraces;
        delete message.researchSources;
        changed = true;
      }
    }
    if (!changed) continue;
    trimmed += 1;
    try {
      write();
      emitStorageWarning({ kind: 'trimmed', conversations: trimmed });
      return true;
    } catch (err) {
      if (!isQuotaError(err)) {
        emitStorageWarning({
          kind: 'unavailable',
          detail: err instanceof Error ? err.message : String(err),
        });
        return false;
      }
    }
  }

  // Stage 2 — the text alone still does not fit. Delete, oldest first.
  //
  // Rate-limited, and that limit is the important part. saveConversations is
  // called on every stream flush, throttled to 80ms, so without a bound a
  // single long reply on a full disk deletes a conversation per flush: a
  // measured run destroyed 19 of 21 conversations while one reply streamed.
  // The archive is irreplaceable and the reply is on screen and exportable,
  // so when the choice is between them, history wins. Past the limit this
  // reports 'full' instead — the conversation stops persisting, which is a
  // loss the user is told about rather than one taken from them silently.
  if (Date.now() - lastDeletionAt < DELETION_COOLDOWN_MS) {
    emitStorageWarning({ kind: 'full' });
    return false;
  }

  // At most one per event, as well as one per cooldown. The loop used to
  // keep deleting until the write fit, so a single call could take many —
  // which is how the measured run still lost 13 conversations even with the
  // cooldown gating entry. If freeing one is not enough, stop and say so;
  // the next attempt, a minute later, frees one more. Converging slowly is
  // the right direction to be wrong in.
  const oldest = oldestFirst()[0];
  if (oldest) {
    delete store.conversations[oldest.id];
    try {
      write();
      lastDeletionAt = Date.now();
      emitStorageWarning({ kind: 'pruned', removed: 1 });
      return true;
    } catch (err) {
      if (!isQuotaError(err)) {
        emitStorageWarning({
          kind: 'unavailable',
          detail: err instanceof Error ? err.message : String(err),
        });
        return false;
      }
      // Still does not fit. Put it back rather than losing it for nothing.
      store.conversations[oldest.id] = oldest;
      lastDeletionAt = Date.now();
    }
  }

  // Even alone, the protected conversation does not fit. Say so rather than
  // failing silently; it is the only honest thing left.
  emitStorageWarning({ kind: 'full' });
  return false;
}

/**
 * Write one small preference, reporting rather than throwing on failure.
 *
 * These are individually tiny, but they share a quota with the conversations
 * blob — so once that fills, every one of them starts throwing too.
 */
function persist(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch (err) {
    emitStorageWarning(
      isQuotaError(err)
        ? { kind: 'full' }
        : {
            kind: 'unavailable',
            detail: err instanceof Error ? err.message : String(err),
          },
    );
  }
}

export type ThemeMode = 'light' | 'dark' | 'system';

interface Settings {
  theme: ThemeMode;
  apiUrl: string;
  // Local server API key (NIRA_API_KEY). Sent as a Bearer token on
  // /v1 + /api requests so a key-protected `nira serve` doesn't 401 the
  // frontend (#266). Empty = no auth header (keyless local default).
  apiKey: string;
  fontSize: 'small' | 'default' | 'large';
  defaultModel: string;
  defaultAgent: string;
  temperature: number;
  maxTokens: number;
  speechEnabled: boolean;
}

function loadSettings(): Settings {
  const defaults: Settings = {
    theme: 'system',
    apiUrl: '',
    apiKey: '',
    fontSize: 'default',
    defaultModel: '',
    defaultAgent: '',
    temperature: 0.7,
    maxTokens: 4096,
    speechEnabled: false,
  };
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return defaults;
    return { ...defaults, ...JSON.parse(raw) };
  } catch {
    return defaults;
  }
}

function saveSettings(settings: Settings): void {
  // Guarded for the same reason as saveConversations, and it matters more per
  // byte: this blob is tiny but holds the API key and the default model. If a
  // conversations write has filled the quota, an unguarded throw here would
  // escape updateSettings and lose the setting the user just changed —
  // including, at the worst possible moment, the API key they were typing in
  // to fix a 401.
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (err) {
    emitStorageWarning(
      isQuotaError(err)
        ? { kind: 'full' }
        : {
            kind: 'unavailable',
            detail: err instanceof Error ? err.message : String(err),
          },
    );
  }
}

// ── Store ─────────────────────────────────────────────────────────────

const INITIAL_STREAM: StreamState = {
  conversationId: null,
  isStreaming: false,
  phase: '',
  elapsedMs: 0,
  activeToolCalls: [],
  content: '',
};

interface AppState {
  // Conversations
  conversations: Conversation[];
  activeId: string | null;
  messages: ChatMessage[];
  streamState: StreamState;

  // Models & server
  models: ModelInfo[];
  modelsLoading: boolean;
  selectedModel: string;
  /** True while the selection is a fallback rather than the reader's choice. */
  modelWasAutoPicked: boolean;
  serverInfo: ServerInfo | null;
  savings: SavingsData | null;

  // Settings
  settings: Settings;

  // Command palette
  commandPaletteOpen: boolean;

  // Sidebar
  sidebarOpen: boolean;

  // System panel
  systemPanelOpen: boolean;

  // Opt-in sharing
  optInEnabled: boolean;
  optInDisplayName: string;
  optInEmail: string;
  optInAnonId: string;
  optInModalSeen: boolean;
  optInModalOpen: boolean;

  // Actions: conversations
  loadConversations: () => void;
  importOverlayConversation: () => Promise<void>;
  createConversation: (model?: string) => string;
  selectConversation: (id: string) => void;
  deleteConversation: (id: string) => void;
  loadMessages: (conversationId: string | null) => void;
  addMessage: (conversationId: string, message: ChatMessage) => void;
  updateLastAssistant: (
    conversationId: string,
    content: string,
    toolCalls?: ToolCallInfo[],
    usage?: TokenUsage,
    telemetry?: MessageTelemetry,
    audio?: { url: string },
    researchTraces?: ResearchSearchTrace[],
    researchSources?: ResearchSource[],
  ) => void;
  setStreamState: (state: Partial<StreamState>) => void;
  resetStream: () => void;

  // Deep Research toggle
  deepResearch: boolean;
  agentMode: boolean;
  setDeepResearch: (on: boolean) => void;
  setAgentMode: (on: boolean) => void;

  // Actions: models & server
  setModels: (models: ModelInfo[]) => void;
  setModelsLoading: (loading: boolean) => void;
  setSelectedModel: (model: string) => void;
  setServerInfo: (info: ServerInfo | null) => void;
  setSavings: (data: SavingsData | null) => void;
  incrementSavings: (usage: TokenUsage) => void;

  // Live GPU metrics — streamed from /api/research system_metrics events.
  // When non-null, the System panel renders this instead of polled values
  // so Power (W) and Energy (kJ) update in real time during a research run.
  liveEnergy: LiveEnergyMetrics | null;
  setLiveEnergy: (data: LiveEnergyMetrics | null) => void;

  // Actions: settings
  updateSettings: (partial: Partial<Settings>) => void;

  // Actions: UI
  setCommandPaletteOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  toggleSystemPanel: () => void;
  setSystemPanelOpen: (open: boolean) => void;

  // Data sources (cached between visits to avoid empty-state flicker)
  cachedConnectors: CachedConnector[] | null;
  setCachedConnectors: (list: CachedConnector[] | null) => void;

  // Agents
  managedAgents: ManagedAgent[];
  managedAgentsLoading: boolean;
  selectedAgentId: string | null;

  // Actions: agents
  setManagedAgents: (agents: ManagedAgent[]) => void;
  setManagedAgentsLoading: (loading: boolean) => void;
  setSelectedAgentId: (id: string | null) => void;

  // Agent events (live stream)
  agentEvents: AgentEvent[];
  addAgentEvent: (event: AgentEvent) => void;
  clearAgentEvents: () => void;

  // Actions: opt-in sharing
  setOptIn: (enabled: boolean, displayName: string, email: string) => void;
  setOptInModalOpen: (open: boolean) => void;
  markOptInModalSeen: () => void;

  // Logs
  logEntries: LogEntry[];
  addLogEntry: (entry: LogEntry) => void;
  clearLogs: () => void;

  // Model loading
  modelLoading: boolean;
  setModelLoading: (loading: boolean) => void;
}

export const useAppStore = create<AppState>((set, get) => {
  const initial = loadConversations();
  const convList = Object.values(initial.conversations).sort(
    (a, b) => b.updatedAt - a.updatedAt,
  );

  return {
    conversations: convList,
    activeId: initial.activeId,
    messages:
      initial.activeId && initial.conversations[initial.activeId]
        ? initial.conversations[initial.activeId].messages
        : [],
    streamState: INITIAL_STREAM,

    models: [],
    modelsLoading: true,
    // Seeded from the persisted setting, not empty.
    //
    // `settings.defaultModel` has been a saved field the whole time and
    // nothing ever wrote to it, so this started blank on every launch and the
    // selection fell through to "whatever the server or Ollama listed first".
    // That is the model apparently vanishing between sessions: it was never
    // stored, so there was nothing to come back to.
    selectedModel: loadSettings().defaultModel || '',
    modelWasAutoPicked: !loadSettings().defaultModel,
    serverInfo: null,
    savings: null,

    settings: loadSettings(),

    commandPaletteOpen: false,
    sidebarOpen: true,
    systemPanelOpen: true,

    optInEnabled: localStorage.getItem(OPTIN_KEY) === 'true',
    optInDisplayName: localStorage.getItem(OPTIN_NAME_KEY) || '',
    optInEmail: localStorage.getItem(OPTIN_EMAIL_KEY) || '',
    optInAnonId: localStorage.getItem(OPTIN_ANONID_KEY) || crypto.randomUUID(),
    optInModalSeen: localStorage.getItem(OPTIN_SEEN_KEY) === 'true',
    optInModalOpen: false,

    // ── Conversations ───────────────────────────────────────────────

    loadConversations: () => {
      const store = loadConversations();
      set({
        conversations: Object.values(store.conversations).sort(
          (a, b) => b.updatedAt - a.updatedAt,
        ),
        activeId: store.activeId,
      });
    },

    importOverlayConversation: async () => {
      try {
        const { invoke } = await import('@tauri-apps/api/core');
        const raw = await invoke<string>('get_overlay_conversation');
        if (!raw || raw === '[]') return;
        const overlay = JSON.parse(raw);
        if (!overlay.id || !overlay.messages?.length) return;
        const store = loadConversations();
        const existing = store.conversations[overlay.id];
        // Only update if the overlay has newer/more messages
        if (existing && existing.messages.length >= overlay.messages.length) return;
        // Track first use of overlay for this conversation
        if (!existing) {
          import('../lib/analytics').then(({ track }) => {
            track('feature_used', { feature_name: 'overlay' });
          });
        }
        store.conversations[overlay.id] = {
          id: overlay.id,
          title: overlay.title || 'Overlay chat',
          createdAt: overlay.createdAt || Date.now(),
          updatedAt: overlay.updatedAt || Date.now(),
          model: overlay.model || 'default',
          messages: overlay.messages,
        };
        // overlay.id, not activeId: this write is about the overlay's
        // conversation, and the reclaim must not consider it expendable.
        saveConversations(store, overlay.id);
        set({
          conversations: Object.values(store.conversations).sort(
            (a, b) => b.updatedAt - a.updatedAt,
          ),
        });
      } catch {
        // Overlay command unavailable (non-Tauri or no overlay data)
      }
    },

    createConversation: (model?: string) => {
      const store = loadConversations();
      const conv: Conversation = {
        id: generateId(),
        title: 'New chat',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        model: model || get().selectedModel || 'default',
        messages: [],
      };
      store.conversations[conv.id] = conv;
      store.activeId = conv.id;
      saveConversations(store);
      set({
        conversations: Object.values(store.conversations).sort(
          (a, b) => b.updatedAt - a.updatedAt,
        ),
        activeId: conv.id,
        messages: [],
      });
      return conv.id;
    },

    selectConversation: (id: string) => {
      const store = loadConversations();
      store.activeId = id;
      saveConversations(store);
      const conv = store.conversations[id];
      set({
        activeId: id,
        messages: conv ? conv.messages : [],
        // Re-read the list from what is actually stored. Reclaiming room can
        // remove conversations while the sidebar still lists them, and the
        // first thing a user does with a stale entry is click it — which
        // showed an empty chat and no reason for it. Refreshing here means
        // that click is also the repair.
        conversations: Object.values(store.conversations).sort(
          (a, b) => b.updatedAt - a.updatedAt,
        ),
      });
    },

    deleteConversation: (id: string) => {
      const streamState = get().streamState;
      if (streamState.isStreaming && streamState.conversationId === id) return;

      const store = loadConversations();
      delete store.conversations[id];
      if (store.activeId === id) {
        const remaining = Object.keys(store.conversations);
        store.activeId = remaining.length > 0 ? remaining[0] : null;
      }
      saveConversations(store);
      const convList = Object.values(store.conversations).sort(
        (a, b) => b.updatedAt - a.updatedAt,
      );
      const activeConv = store.activeId
        ? store.conversations[store.activeId]
        : null;
      set({
        conversations: convList,
        activeId: store.activeId,
        messages: activeConv ? activeConv.messages : [],
      });
    },

    loadMessages: (conversationId: string | null) => {
      if (!conversationId) {
        set({ messages: [] });
        return;
      }
      const store = loadConversations();
      const conv = store.conversations[conversationId];
      set({ messages: conv ? conv.messages : [] });
    },

    addMessage: (conversationId: string, message: ChatMessage) => {
      const store = loadConversations();
      const conv = store.conversations[conversationId];
      if (!conv) return;
      conv.messages.push(message);
      conv.updatedAt = Date.now();
      if (message.role === 'user' && conv.title === 'New chat') {
        conv.title =
          message.content.slice(0, 50) +
          (message.content.length > 50 ? '...' : '');
      }
      // conversationId, not activeId. They are the same in the chat flow
      // today, but this signature takes an explicit id and nothing enforces
      // the match — so name the conversation this write is about rather than
      // letting the reclaim decide it is expendable.
      saveConversations(store, conversationId);
      const conversations = Object.values(store.conversations).sort(
        (a, b) => b.updatedAt - a.updatedAt,
      );
      if (get().activeId === conversationId) {
        set({ messages: [...conv.messages], conversations });
      } else {
        set({ conversations });
      }
    },

    updateLastAssistant: (
      conversationId: string,
      content: string,
      toolCalls?: ToolCallInfo[],
      usage?: TokenUsage,
      telemetry?: MessageTelemetry,
      audio?: { url: string },
      researchTraces?: ResearchSearchTrace[],
      researchSources?: ResearchSource[],
    ) => {
      const store = loadConversations();
      const conv = store.conversations[conversationId];
      if (!conv) return;
      const lastMsg = conv.messages[conv.messages.length - 1];
      if (lastMsg && lastMsg.role === 'assistant') {
        lastMsg.content = content;
        if (toolCalls) lastMsg.toolCalls = toolCalls;
        if (usage) lastMsg.usage = usage;
        if (telemetry) lastMsg.telemetry = telemetry;
        if (audio) lastMsg.audio = audio;
        if (researchTraces) lastMsg.researchTraces = researchTraces;
        if (researchSources) lastMsg.researchSources = researchSources;
        conv.updatedAt = Date.now();
        const wrote = saveConversations(store, conversationId);
        if (get().activeId === conversationId) {
          set({ messages: [...conv.messages] });
        }
        // A reclaim during streaming can drop conversations out from under
        // the sidebar. Rebuilding the list on every flush would sort it 12
        // times a second for nothing, so do it only when the store we just
        // wrote no longer matches the one on screen.
        if (wrote && Object.keys(store.conversations).length !== get().conversations.length) {
          set({
            conversations: Object.values(store.conversations).sort(
              (a, b) => b.updatedAt - a.updatedAt,
            ),
          });
        }
      }
    },

    setStreamState: (partial: Partial<StreamState>) => {
      set((s) => ({ streamState: { ...s.streamState, ...partial } }));
    },

    resetStream: () => {
      set({ streamState: INITIAL_STREAM });
    },

    // ── Deep Research ─────────────────────────────────────────────
    deepResearch: false,
    setDeepResearch: (on: boolean) => set({ deepResearch: on }),

    // Agent mode: tools, memory and the learning loop. Off is a straight
    // model answer, which is markedly faster and leaves no trace behind —
    // the right default for "just tell me" and the wrong one for anything
    // the assistant should get better at.
    agentMode: true,
    setAgentMode: (on: boolean) => set({ agentMode: on }),

    // ── Models & server ────────────────────────────────────────────

    setModels: (models: ModelInfo[]) =>
      set((state) => {
        // Ollama returns embed-only models (e.g. nomic-embed-text) in the
        // same list as chat models. Auto-picking models[0] selected the
        // embedder and every chat failed with HTTP 400 "does not support
        // chat". Prefer a real chat model for selection / fallback.
        const chatModels = models.filter((m) => !isEmbedOnlyModel(m.id));
        // The server's model, before the first thing in an arbitrary list.
        //
        // `nira init` detects the hardware and writes a default the machine
        // can actually run; the server reports it at /v1/info, and the UI
        // fetched that and then ignored it — falling through to
        // `chatModels[0]`, which is whatever order Ollama happened to return.
        // On a CPU-only box that picked qwen3.5:27b: 18 GB, 100% CPU, minutes
        // per reply, and a chat that looks hung rather than slow.
        const serverModel =
          state.serverInfo?.model &&
          chatModels.some((m) => m.id === state.serverInfo?.model)
            ? state.serverInfo.model
            : '';
        const preferred =
          (state.settings.defaultModel &&
            chatModels.some((m) => m.id === state.settings.defaultModel) &&
            state.settings.defaultModel) ||
          serverModel ||
          chatModels[0]?.id ||
          models.find((m) => !isEmbedOnlyModel(m.id))?.id ||
          '';

        const currentIsBad =
          !!state.selectedModel && isEmbedOnlyModel(state.selectedModel);
        // An empty list is not evidence that a particular model is absent.
        //
        // Callers pass `[]` when the *fetch* failed — App.tsx did it from a
        // `.catch()` — and this then read as "the user has zero models", so
        // it cleared `selectedModel` and set modelWasAutoPicked. Every
        // transient 401 or server restart wiped the choice, the selector fell
        // to "No models", and when the next poll succeeded it came back:
        // exactly the "it reverts automatically and is not stable" the user
        // reported after downloading one. Only a list we actually received
        // can prove a model is gone.
        const currentMissing =
          !!state.selectedModel &&
          models.length > 0 &&
          !models.some((m) => m.id === state.selectedModel);

        if (models.length === 0 && state.selectedModel && !currentIsBad) {
          // Keep the selection and say nothing about it. `settings.defaultModel`
          // still holds it, so a later successful fetch re-confirms rather than
          // re-picks.
          return { models };
        }

        if (!state.selectedModel || currentIsBad || currentMissing) {
          // Auto-picked, so a later /v1/info may still correct it.
          // Prefer a real chat model. If none exist, clear a bad/missing
          // selection rather than keeping an embed-only id that 400s on chat.
          return {
            models,
            selectedModel: preferred,
            modelWasAutoPicked: true,
          };
        }
        return { models };
      }),
    setModelsLoading: (loading: boolean) => set({ modelsLoading: loading }),
    // An explicit choice is never overridden by a later server response.
    setSelectedModel: (model: string) =>
      set((state) => {
        // Persist it. Choosing a model is a preference, not view state, and
        // the reader expects the next launch to open on what they picked.
        const settings = { ...state.settings, defaultModel: model };
        try {
          saveSettings(settings);
        } catch {
          // Storage full or read-only: keep the choice for this session
          // rather than refusing to switch models over it.
        }
        return { selectedModel: model, settings, modelWasAutoPicked: false };
      }),
    setServerInfo: (info: ServerInfo | null) =>
      set((state) => {
        // /v1/info and /v1/models race. If the list landed first we picked a
        // fallback; now that the server has said which model it is configured
        // for, correct it — but only if the reader has not chosen one.
        const shouldAdopt =
          !!info?.model &&
          state.modelWasAutoPicked &&
          state.models.some((m) => m.id === info.model) &&
          state.selectedModel !== info.model;
        return shouldAdopt
          ? { serverInfo: info, selectedModel: info!.model }
          : { serverInfo: info };
      }),
    setSavings: (data: SavingsData | null) => set({ savings: data }),
    incrementSavings: (usage: TokenUsage) => {
      const cur = get().savings;
      const prompt = usage.prompt_tokens ?? 0;
      const completion = usage.completion_tokens ?? 0;
      const total = usage.total_tokens ?? prompt + completion;
      set({
        savings: {
          total_calls: (cur?.total_calls ?? 0) + 1,
          total_prompt_tokens: (cur?.total_prompt_tokens ?? 0) + prompt,
          total_completion_tokens: (cur?.total_completion_tokens ?? 0) + completion,
          total_tokens: (cur?.total_tokens ?? 0) + total,
          local_cost: cur?.local_cost ?? 0,
          per_provider: cur?.per_provider ?? [],
          token_counting_version: cur?.token_counting_version,
        },
      });
    },

    liveEnergy: null,
    setLiveEnergy: (data: LiveEnergyMetrics | null) => set({ liveEnergy: data }),

    cachedConnectors: null,
    setCachedConnectors: (list) => set({ cachedConnectors: list }),

    // ── Settings ───────────────────────────────────────────────────

    updateSettings: (partial: Partial<Settings>) => {
      const updated = { ...get().settings, ...partial };
      saveSettings(updated);
      set({ settings: updated });
    },

    // ── UI ──────────────────────────────────────────────────────────

    setCommandPaletteOpen: (open: boolean) => set({ commandPaletteOpen: open }),
    toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
    setSidebarOpen: (open: boolean) => set({ sidebarOpen: open }),
    toggleSystemPanel: () => set((s) => ({ systemPanelOpen: !s.systemPanelOpen })),
    setSystemPanelOpen: (open: boolean) => set({ systemPanelOpen: open }),

    // ── Agents ─────────────────────────────────────────────────────

    managedAgents: [],
    managedAgentsLoading: false,
    selectedAgentId: null,

    setManagedAgents: (agents) => set({ managedAgents: agents }),
    setManagedAgentsLoading: (loading) => set({ managedAgentsLoading: loading }),
    setSelectedAgentId: (id) => set({ selectedAgentId: id }),

    agentEvents: [],
    addAgentEvent: (event) => set((s) => ({
      agentEvents: [...s.agentEvents.slice(-99), event],
    })),
    clearAgentEvents: () => set({ agentEvents: [] }),

    // ── Logs ────────────────────────────────────────────────────────
    logEntries: [],
    addLogEntry: (entry) => set((s) => ({
      logEntries: [...s.logEntries.slice(-499), entry],
    })),
    clearLogs: () => set({ logEntries: [] }),

    // ── Model loading ───────────────────────────────────────────────
    modelLoading: false,
    setModelLoading: (loading) => set({ modelLoading: loading }),

    // ── Opt-in sharing ──────────────────────────────────────────────

    setOptIn: (enabled: boolean, displayName: string, email: string) => {
      const anonId = get().optInAnonId;
      // Four unguarded writes in a row: a throw on the first left the last
      // three unwritten and the in-memory state unset, so the modal reopened
      // and the user re-entered everything. Persist what we can, and keep the
      // choice for the session regardless.
      persist(OPTIN_KEY, String(enabled));
      persist(OPTIN_NAME_KEY, displayName);
      persist(OPTIN_EMAIL_KEY, email);
      persist(OPTIN_ANONID_KEY, anonId);
      set({ optInEnabled: enabled, optInDisplayName: displayName, optInEmail: email });
    },
    setOptInModalOpen: (open: boolean) => set({ optInModalOpen: open }),
    markOptInModalSeen: () => {
      persist(OPTIN_SEEN_KEY, 'true');
      set({ optInModalSeen: true });
    },
  };
});

export { generateId };
