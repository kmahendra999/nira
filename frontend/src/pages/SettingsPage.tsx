import { useState, useEffect, useCallback } from 'react';
import {
  Palette,
  Globe,
  Cpu,
  Database,
  Info,
  Check,
  Sun,
  Moon,
  Monitor,
  Download,
  Upload,
  Trash2,
  Mic,
  Key,
  Search,
  Brain,
  RefreshCw,
  Wifi,
} from 'lucide-react';
import { useAppStore, type ThemeMode } from '../lib/store';
import { toast } from 'sonner';
import {
  checkHealth,
  fetchSpeechHealth,
  getMemoryStats,
  getMemoryConfig,
  updateMemoryConfig,
  getInferenceSource,
  setInferenceSource,
  getCloudKeyStatus,
  saveCloudKey,
  fetchToolCredentialStatus,
  saveToolCredentials,
  deleteToolCredential,
  isTauri,
  type InferenceSource,
  type MemoryStats,
  type MemoryConfigUpdate,
  type MemoryBackendInfo,
  getNetworkConfig,
  isAutostartEnabled,
  setAutostartEnabled,
  updateNetworkConfig,
  type NetworkConfig,
} from '../lib/api';
import { isAutoUpdateDisabled, setAutoUpdateDisabled } from '../components/Desktop/UpdateChecker';

const CLOUD_KEY_STATUS_CHANGED = 'nira-cloud-key-status-changed';

function OllamaModelList() {
  const [models, setModels] = useState<Array<{ name: string; size: number }>>([]);
  useEffect(() => {
    fetch('http://localhost:11434/api/tags')
      .then(r => r.json())
      .then(data => setModels((data.models || []).map((m: any) => ({ name: m.name, size: m.size }))))
      .catch(() => setModels([]));
  }, []);
  if (models.length === 0) return <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>No models loaded</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {models.map(m => (
        <span key={m.name} className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px]"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-success)', display: 'inline-block' }} />
          {m.name} ({(m.size / 1e9).toFixed(1)} GB)
        </span>
      ))}
    </div>
  );
}

function ApiKeyInput({
  keyName,
  placeholder,
  toolName,
}: {
  keyName: string;
  placeholder: string;
  toolName?: string;
}) {
  const [value, setValue] = useState('');
  const [saved, setSaved] = useState(false);
  const [hasKey, setHasKey] = useState(false);
  const [error, setError] = useState('');
  const desktopKeyStorage = isTauri();
  const serverToolStorage = !desktopKeyStorage && !!toolName;
  const canManage = desktopKeyStorage || serverToolStorage;

  const refresh = useCallback(async () => {
    if (!canManage) {
      setHasKey(false);
      return;
    }
    try {
      const status = desktopKeyStorage
        ? await getCloudKeyStatus()
        : await fetchToolCredentialStatus(toolName!);
      setHasKey(!!status[keyName]);
    } catch {
      setHasKey(false);
    }
  }, [canManage, desktopKeyStorage, keyName, toolName]);

  useEffect(() => {
    void refresh();
    window.addEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
    return () => window.removeEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
  }, [refresh]);

  const save = async (v: string) => {
    const next = v.trim();
    if (!next) return;
    setError('');
    try {
      if (desktopKeyStorage) {
        await saveCloudKey(keyName, next);
      } else if (toolName) {
        await saveToolCredentials(toolName, { [keyName]: next });
      } else {
        return;
      }
      setValue('');
      setHasKey(true);
      setSaved(true);
      window.dispatchEvent(new Event(CLOUD_KEY_STATUS_CHANGED));
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e?.message || 'Failed to save API key');
    }
  };

  const remove = async () => {
    setError('');
    try {
      if (desktopKeyStorage) {
        await saveCloudKey(keyName, '');
      } else if (toolName) {
        await deleteToolCredential(toolName, keyName);
      } else {
        return;
      }
      setValue('');
      setHasKey(false);
      setSaved(true);
      window.dispatchEvent(new Event(CLOUD_KEY_STATUS_CHANGED));
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e?.message || 'Failed to remove API key');
    }
  };

  return (
    <div className="flex items-center gap-2">
      <input
        type="password"
        value={value}
        onChange={e => setValue(e.target.value)}
        onBlur={() => { if (value.trim()) void save(value); }}
        placeholder={hasKey ? (desktopKeyStorage ? 'Saved in secure storage' : 'Saved by local server') : placeholder}
        disabled={!canManage}
        className="w-48 px-2 py-1 rounded text-xs"
        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
      {hasKey && (
        <button
          onClick={() => void remove()}
          className="px-2 py-1 rounded text-[10px] cursor-pointer"
          style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}
        >
          Remove
        </button>
      )}
      {saved && <span className="text-[10px]" style={{ color: 'var(--color-success)' }}>Saved</span>}
      {error && <span className="text-[10px]" style={{ color: 'var(--color-error)' }}>{error}</span>}
    </div>
  );
}

function CloudProviderStatus({ label, keyName }: { label: string; keyName: string }) {
  const [hasKey, setHasKey] = useState(false);
  const desktopKeyStorage = isTauri();

  const refresh = useCallback(async () => {
    if (!desktopKeyStorage) {
      setHasKey(false);
      return;
    }
    try {
      const status = await getCloudKeyStatus();
      setHasKey(!!status[keyName]);
    } catch {
      setHasKey(false);
    }
  }, [desktopKeyStorage, keyName]);

  useEffect(() => {
    void refresh();
    window.addEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
    return () => window.removeEventListener(CLOUD_KEY_STATUS_CHANGED, refresh);
  }, [refresh]);

  return (
    <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
        background: hasKey ? 'var(--color-success)' : 'var(--color-text-tertiary)',
      }} />
      {label}
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-5"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <h3 className="text-sm font-semibold mb-4" style={{ color: 'var(--color-text)' }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

function SettingRow({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-3" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
      <div>
        <div className="text-sm" style={{ color: 'var(--color-text)' }}>{label}</div>
        {description && (
          <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{description}</div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}

const themeOptions: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
];

export function SettingsPage() {
  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);
  const conversations = useAppStore((s) => s.conversations);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [speechBackendAvailable, setSpeechBackendAvailable] = useState<boolean | null>(null);
  const [saved, setSaved] = useState(false);

  const [autoUpdateEnabled, setAutoUpdateEnabled] = useState(() => !isAutoUpdateDisabled());
  const [updateCheckState, setUpdateCheckState] = useState<'idle' | 'checking' | 'available' | 'latest'>('idle');

  const handleAutoUpdateToggle = useCallback((enabled: boolean) => {
    setAutoUpdateEnabled(enabled);
    setAutoUpdateDisabled(!enabled);
  }, []);

  const handleCheckNow = useCallback(async () => {
    if (!(window as any).__TAURI_INTERNALS__) return;
    setUpdateCheckState('checking');
    try {
      const { check } = await import('@tauri-apps/plugin-updater');
      const update = await check();
      setUpdateCheckState(update ? 'available' : 'latest');
      setTimeout(() => setUpdateCheckState('idle'), 4000);
    } catch {
      setUpdateCheckState('idle');
    }
  }, []);

  // Memory settings come from the server, not localStorage. They used to be
  // stored client-side only: the toggle defaulted to ON while the server had
  // `[memory] enabled = false`, so the panel described a state nobody was in
  // and moving any control changed nothing. Start from `null` — "not known
  // yet" — rather than a guess, and render the real values once they land.
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [memoryEnabled, setMemoryEnabled] = useState<boolean | null>(null);
  const [memoryBackend, setMemoryBackend] = useState('sqlite');
  const [memoryTopK, setMemoryTopK] = useState(5);
  const [memoryMinScore, setMemoryMinScore] = useState(0.1);
  const [memoryMaxTokens, setMemoryMaxTokens] = useState(2048);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoryBackends, setMemoryBackends] = useState<MemoryBackendInfo[]>([
    { id: 'sqlite', available: true, missing: [] },
  ]);

  // Which address this machine hands your other devices. Nobody's network is
  // the same, so this reports what is actually available here and lets the
  // user pin one — pairing used to fall back to http://localhost, which is
  // the phone talking to itself.
  const [network, setNetwork] = useState<NetworkConfig | null>(null);
  const [networkHost, setNetworkHost] = useState('');
  const [networkError, setNetworkError] = useState<string | null>(null);
  const [networkSaving, setNetworkSaving] = useState(false);

  // Start at login. null = not known yet / not the desktop app.
  const [autostart, setAutostart] = useState<boolean | null>(null);
  const [autostartError, setAutostartError] = useState<string | null>(null);

  const applyNetwork = useCallback((cfg: NetworkConfig) => {
    setNetwork(cfg);
    setNetworkHost(cfg.advertise_host || '');
  }, []);

  const saveNetwork = useCallback(async (update: Record<string, unknown>) => {
    setNetworkError(null);
    setNetworkSaving(true);
    try {
      applyNetwork(await updateNetworkConfig(update));
      return true;
    } catch (e: any) {
      setNetworkError(e?.message ?? 'Could not save network settings');
      return false;
    } finally {
      setNetworkSaving(false);
    }
  }, [applyNetwork]);

  // Save through the server, and only move the control once it confirms. A
  // toggle that flips on click and silently fails is exactly the lie this
  // section is being rewritten to stop telling.
  const saveMemory = useCallback(async (update: MemoryConfigUpdate) => {
    setMemoryError(null);
    try {
      const saved = await updateMemoryConfig(update);
      if (typeof saved.enabled === 'boolean') setMemoryEnabled(saved.enabled);
      if (typeof saved.context_top_k === 'number') setMemoryTopK(saved.context_top_k);
      if (typeof saved.context_min_score === 'number') setMemoryMinScore(saved.context_min_score);
      if (typeof saved.context_max_tokens === 'number') setMemoryMaxTokens(saved.context_max_tokens);
      getMemoryStats().then(setMemoryStats).catch(() => {});
      return true;
    } catch (e: any) {
      setMemoryError(e?.message ?? 'Could not save memory settings');
      return false;
    }
  }, []);

  const [srcKind, setSrcKind] = useState<InferenceSource['kind']>('ollama');
  const [customHost, setCustomHost] = useState('http://localhost:1234/v1');
  const [customModel, setCustomModel] = useState('');
  const [customEngine, setCustomEngine] = useState('lmstudio');
  const [customKey, setCustomKey] = useState('');
  const [srcMsg, setSrcMsg] = useState('');

  useEffect(() => {
    getInferenceSource().then((s) => {
      setSrcKind(s.kind);
      if (s.host) setCustomHost(s.host);
      if (s.model) setCustomModel(s.model);
      if (s.engine) setCustomEngine(s.engine);
    }).catch(() => {});
  }, []);

  const saveSource = useCallback(async () => {
    try {
      if (srcKind === 'custom') {
        await setInferenceSource({ kind: 'custom', host: customHost, model: customModel, engine: customEngine, apiKey: customKey || undefined });
      } else {
        await setInferenceSource({ kind: 'ollama' });
      }
      setSrcMsg('Saved — restart the app to apply.');
    } catch (e: any) {
      setSrcMsg(e?.message ?? 'Failed to save.');
    }
  }, [srcKind, customHost, customModel, customEngine, customKey]);

  useEffect(() => {
    checkHealth().then(setHealthy);
    fetchSpeechHealth()
      .then((h) => setSpeechBackendAvailable(h.available))
      .catch(() => setSpeechBackendAvailable(false));
    getMemoryStats()
      .then(setMemoryStats)
      .catch(() => setMemoryStats(null));
    getMemoryConfig()
      .then((cfg) => {
        setMemoryEnabled(cfg.enabled ?? false);
        setMemoryBackend(cfg.default_backend || cfg.backend_type || 'sqlite');
        if (cfg.backends?.length) setMemoryBackends(cfg.backends);
        setMemoryTopK(cfg.context_top_k);
        setMemoryMinScore(cfg.context_min_score);
        setMemoryMaxTokens(cfg.context_max_tokens);
      })
      .catch(() => setMemoryError('Could not read memory settings from the server'));
    getNetworkConfig()
      .then(applyNetwork)
      .catch(() => setNetworkError('Could not read network settings from the server'));
    if (isTauri()) {
      isAutostartEnabled().then(setAutostart).catch(() => setAutostart(false));
    }
  }, [applyNetwork]);

  const showSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const handleExport = () => {
    // Export what is on screen, not what made it to disk.
    //
    // This read localStorage directly, which is the one place the data might
    // be missing from: when storage is full, saveConversations cannot write
    // and the app tells the user to export instead — advice that would have
    // handed them a file without the conversation they were trying to save.
    // A file has no quota, so the in-memory state is both the truthful source
    // and the one worth keeping.
    const persisted = (() => {
      try {
        return JSON.parse(localStorage.getItem('nira-conversations') || '{}');
      } catch {
        return {};
      }
    })();
    const live = useAppStore.getState();
    const merged = {
      version: 1,
      activeId: live.activeId,
      conversations: {
        ...(persisted.conversations ?? {}),
        ...Object.fromEntries(live.conversations.map((c) => [c.id, c])),
      },
    };
    // The active conversation's newest messages live in `messages`; the
    // entries in `conversations` can lag it mid-stream.
    if (live.activeId && merged.conversations[live.activeId]) {
      merged.conversations[live.activeId] = {
        ...merged.conversations[live.activeId],
        messages: live.messages,
      };
    }
    const blob = new Blob([JSON.stringify(merged)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nira-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        // Every failure here used to be silent: a bare `catch {}` around an
        // unguarded setItem, and a version mismatch that simply did nothing.
        // This is the path the app tells people to use when storage is full
        // or a conversation is lost — the one place where saying nothing is
        // least acceptable.
        let data: { version?: number; conversations?: Record<string, unknown> };
        try {
          data = JSON.parse(ev.target?.result as string);
        } catch {
          toast.error('That file is not valid JSON', {
            description: 'Pick a file exported from Settings → Data.',
          });
          return;
        }

        if (data?.version !== 1) {
          toast.error('That file is not a Nira export', {
            description: `Expected version 1${
              data?.version ? `, found ${data.version}` : ''
            }.`,
          });
          return;
        }

        try {
          localStorage.setItem('nira-conversations', JSON.stringify(data));
        } catch (err: any) {
          toast.error('Could not import', {
            description:
              'There is not enough room in local storage. Clear some ' +
              'conversations first, then import again.',
            duration: 12000,
          });
          return;
        }

        useAppStore.getState().loadConversations();
        const count = Object.keys(data.conversations ?? {}).length;
        toast.success(
          `Imported ${count} conversation${count === 1 ? '' : 's'}`,
        );
      };
      reader.readAsText(file);
    };
    input.click();
  };

  const [confirmClear, setConfirmClear] = useState(false);
  const handleClear = () => {
    if (!confirmClear) {
      setConfirmClear(true);
      setTimeout(() => setConfirmClear(false), 3000);
      return;
    }
    localStorage.removeItem('nira-conversations');
    useAppStore.getState().loadConversations();
    setConfirmClear(false);
    showSaved();
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <header className="mb-6">
          <div className="flex items-center justify-between gap-3">
            <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              Settings
            </h1>
            {saved && (
              <span className="flex items-center gap-1 text-xs px-2 py-1 rounded-full" style={{
                background: 'var(--color-accent-subtle)',
                color: 'var(--color-success)',
              }}>
                <Check size={12} /> Saved
              </span>
            )}
          </div>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            App preferences — appearance, model defaults, keyboard shortcuts, and data management.
          </p>
        </header>

        <div className="flex flex-col gap-4">
          {/* Appearance */}
          <Section title="Appearance">
            <SettingRow label="Theme" description="Choose how Nira looks">
              <div className="flex gap-1 p-0.5 rounded-lg" style={{ background: 'var(--color-bg-secondary)' }}>
                {themeOptions.map((opt) => {
                  const isActive = settings.theme === opt.value;
                  return (
                    <button
                      key={opt.value}
                      onClick={() => { updateSettings({ theme: opt.value }); showSaved(); }}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                      style={{
                        background: isActive ? 'var(--color-surface)' : 'transparent',
                        color: isActive ? 'var(--color-text)' : 'var(--color-text-tertiary)',
                        boxShadow: isActive ? 'var(--shadow-sm)' : 'none',
                      }}
                    >
                      <opt.icon size={14} />
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </SettingRow>
            <SettingRow label="Font size">
              <select
                value={settings.fontSize}
                onChange={(e) => { updateSettings({ fontSize: e.target.value as any }); showSaved(); }}
                className="text-sm px-3 py-1.5 rounded-lg cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="small">Small</option>
                <option value="default">Default</option>
                <option value="large">Large</option>
              </select>
            </SettingRow>
          </Section>

          {/* Connection */}
          <Section title="Connection">
            <SettingRow label="Server status" description={serverInfo ? `${serverInfo.engine} / ${serverInfo.model}` : 'Not connected'}>
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: healthy === true ? 'var(--color-success)' : healthy === false ? 'var(--color-error)' : 'var(--color-text-tertiary)' }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {healthy === true ? 'Connected' : healthy === false ? 'Disconnected' : 'Checking...'}
                </span>
              </div>
            </SettingRow>
            <SettingRow label="API URL" description="Set if backend runs on a different port or host">
              <input
                type="text"
                value={settings.apiUrl}
                onChange={(e) => { updateSettings({ apiUrl: e.target.value }); showSaved(); }}
                placeholder="http://localhost:8000"
                className="text-sm px-3 py-1.5 rounded-lg w-56"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </SettingRow>
            <SettingRow label="API key" description="Required only if the server was started with an API key">
              <input
                type="password"
                value={settings.apiKey}
                onChange={(e) => { updateSettings({ apiKey: e.target.value }); showSaved(); }}
                placeholder="NIRA_API_KEY"
                autoComplete="off"
                className="text-sm px-3 py-1.5 rounded-lg w-56"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </SettingRow>
          </Section>

          {/* Inference source */}
          <Section title="Inference source">
            <SettingRow label="Source" description="Where the app runs models. Applies after restart.">
              <select
                value={srcKind}
                onChange={(e) => { setSrcKind(e.target.value as InferenceSource['kind']); setSrcMsg(''); }}
                className="text-sm px-3 py-1.5 rounded-lg w-56"
                style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
              >
                <option value="ollama">Bundled Ollama (default)</option>
                <option value="custom">Custom OpenAI-compatible server</option>
              </select>
            </SettingRow>
            {srcKind === 'custom' && (
              <>
                <SettingRow label="Server URL" description="e.g. LM Studio: http://localhost:1234/v1">
                  <input type="text" value={customHost} onChange={(e) => { setCustomHost(e.target.value); setSrcMsg(''); }} placeholder="http://localhost:1234/v1"
                    className="text-sm px-3 py-1.5 rounded-lg w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
                <SettingRow label="Model" description="Model id served by your endpoint">
                  <input type="text" value={customModel} onChange={(e) => { setCustomModel(e.target.value); setSrcMsg(''); }} placeholder="qwen2.5-7b-instruct"
                    className="text-sm px-3 py-1.5 rounded-lg w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
                <SettingRow label="Server type" description="OpenAI-compatible engine">
                  <select value={customEngine} onChange={(e) => { setCustomEngine(e.target.value); setSrcMsg(''); }}
                    className="text-sm px-3 py-1.5 rounded-lg w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
                    <option value="lmstudio">LM Studio</option>
                    <option value="vllm">vLLM</option>
                    <option value="sglang">SGLang</option>
                    <option value="llamacpp">llama.cpp</option>
                    <option value="mlx">MLX</option>
                  </select>
                </SettingRow>
                <SettingRow label="API key (optional)" description="Only if your server requires one">
                  <input type="password" value={customKey} onChange={(e) => { setCustomKey(e.target.value); setSrcMsg(''); }} placeholder="leave blank if none"
                    className="text-sm px-3 py-1.5 rounded-lg w-56"
                    style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' }} />
                </SettingRow>
              </>
            )}
            <SettingRow label="" description={srcMsg}>
              <button onClick={saveSource}
                className="text-sm px-3 py-1.5 rounded-lg cursor-pointer"
                style={{ background: 'var(--color-accent, var(--color-bg-tertiary))', color: 'var(--color-text)', border: '1px solid var(--color-border)' }}>
                Save inference source
              </button>
            </SettingRow>
          </Section>

          {/* Models */}
          <Section title="Models">
            <SettingRow label="Local models (Ollama)" description="Models available for local inference">
              <OllamaModelList />
            </SettingRow>
            <div className="text-xs mt-2 px-1" style={{ color: 'var(--color-text-tertiary)' }}>
              Run <code className="px-1 py-0.5 rounded text-[11px]" style={{ background: 'var(--color-bg-tertiary)' }}>ollama pull &lt;model-name&gt;</code> in your terminal to add more models
            </div>
            <SettingRow label="Cloud providers" description="Green dot means API key is configured">
              <div className="flex flex-wrap gap-3">
                <CloudProviderStatus label="OpenAI" keyName="OPENAI_API_KEY" />
                <CloudProviderStatus label="Anthropic" keyName="ANTHROPIC_API_KEY" />
                <CloudProviderStatus label="Google" keyName="GEMINI_API_KEY" />
                <CloudProviderStatus label="OpenRouter" keyName="OPENROUTER_API_KEY" />
              </div>
            </SettingRow>
          </Section>

          {/* API Keys */}
          <Section title="API Keys">
            <SettingRow label="OpenAI" description="GPT-4, GPT-3.5, etc.">
              <ApiKeyInput keyName="OPENAI_API_KEY" placeholder="sk-..." />
            </SettingRow>
            <SettingRow label="Anthropic" description="Claude models">
              <ApiKeyInput keyName="ANTHROPIC_API_KEY" placeholder="sk-ant-..." />
            </SettingRow>
            <SettingRow label="Google" description="Gemini models">
              <ApiKeyInput keyName="GEMINI_API_KEY" placeholder="AI..." />
            </SettingRow>
            <SettingRow label="OpenRouter" description="Multi-provider routing">
              <ApiKeyInput keyName="OPENROUTER_API_KEY" placeholder="sk-or-..." />
            </SettingRow>
          </Section>

          {/* Tools */}
          <Section title="Tools">
            <SettingRow label="Web Search" description="Tavily key for web search tool">
              <ApiKeyInput keyName="TAVILY_API_KEY" placeholder="tvly-..." toolName="web_search" />
            </SettingRow>
          </Section>

          {/* Memory */}
          <Section title="Memory">
            <SettingRow
              label="Memory status"
              description={
                memoryStats
                  ? `${memoryStats.backend} backend — ${memoryStats.entries} indexed document${memoryStats.entries === 1 ? '' : 's'}`
                  : 'Unable to reach memory service'
              }
            >
              <div className="flex items-center gap-2">
                <Brain size={14} style={{ color: memoryStats?.service_running ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {memoryStats == null
                    ? 'Unavailable'
                    : typeof memoryStats.facts === 'number'
                      ? `${memoryStats.facts} fact${memoryStats.facts === 1 ? '' : 's'} learned`
                      : memoryStats.enabled
                        ? 'Starting…'
                        : 'Not recording'}
                </span>
              </div>
            </SettingRow>
            {memoryError && (
              <div
                className="text-xs px-3 py-2 rounded-lg mb-2"
                style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}
              >
                {memoryError}
              </div>
            )}
            <SettingRow
              label="Remember across sessions"
              description={
                memoryEnabled === null
                  ? 'Reading current setting from the server…'
                  : memoryEnabled
                    ? 'Facts from your conversations are stored and recalled after a restart'
                    : 'Off — nothing is carried between sessions'
              }
            >
              <button
                onClick={() => { void saveMemory({ enabled: !memoryEnabled }); }}
                disabled={memoryEnabled === null}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer disabled:opacity-50"
                style={{
                  background: memoryEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: memoryEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="Memory backend" description="Which retrieval engine to use — applies on next start">
              <select
                value={memoryBackend}
                onChange={(e) => {
                  const previous = memoryBackend;
                  const next = e.target.value;
                  setMemoryBackend(next);
                  // Put the select back if the server refuses — e.g. the
                  // backend's dependency is not installed on this machine.
                  void saveMemory({ default_backend: next }).then((ok) => {
                    if (!ok) setMemoryBackend(previous);
                  });
                }}
                className="text-sm px-3 py-1.5 rounded-lg cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                {memoryBackends.map((b) => (
                  <option key={b.id} value={b.id} disabled={!b.available}>
                    {b.id}
                    {b.available ? '' : ` — needs ${b.missing.join(', ')}`}
                  </option>
                ))}
              </select>
            </SettingRow>
            <SettingRow label="Results to inject" description={`${memoryTopK}`}>
              <input
                type="range"
                min="1"
                max="20"
                step="1"
                value={memoryTopK}
                onChange={(e) => setMemoryTopK(parseInt(e.target.value))}
                onPointerUp={(e) => { void saveMemory({ context_top_k: parseInt((e.target as HTMLInputElement).value) }); }}
                onKeyUp={(e) => { void saveMemory({ context_top_k: parseInt((e.target as HTMLInputElement).value) }); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label="Min relevance score" description={`${memoryMinScore}`}>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={memoryMinScore}
                onChange={(e) => setMemoryMinScore(parseFloat(e.target.value))}
                onPointerUp={(e) => { void saveMemory({ context_min_score: parseFloat((e.target as HTMLInputElement).value) }); }}
                onKeyUp={(e) => { void saveMemory({ context_min_score: parseFloat((e.target as HTMLInputElement).value) }); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label="Max context tokens" description={`${memoryMaxTokens}`}>
              <input
                type="range"
                min="256"
                max="8192"
                step="256"
                value={memoryMaxTokens}
                onChange={(e) => setMemoryMaxTokens(parseInt(e.target.value))}
                onPointerUp={(e) => { void saveMemory({ context_max_tokens: parseInt((e.target as HTMLInputElement).value) }); }}
                onKeyUp={(e) => { void saveMemory({ context_max_tokens: parseInt((e.target as HTMLInputElement).value) }); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
          </Section>

          {/* Startup — what comes back after a reboot */}
          {isTauri() && (
            <Section title="Startup">
              {autostartError && (
                <div
                  className="text-xs px-3 py-2 rounded-lg mb-2"
                  style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}
                >
                  {autostartError}
                </div>
              )}
              <SettingRow
                label="Start Nira when I log in"
                description="Nira launches to the tray and brings the engine, the server and your models back with it."
              >
                <button
                  onClick={async () => {
                    const next = !autostart;
                    setAutostartError(null);
                    try {
                      await setAutostartEnabled(next);
                      setAutostart(await isAutostartEnabled());
                    } catch (e: any) {
                      setAutostartError(e?.message ?? 'Could not change the login setting');
                    }
                  }}
                  disabled={autostart === null}
                  className="relative w-11 h-6 rounded-full transition-colors cursor-pointer disabled:opacity-50"
                  style={{ background: autostart ? 'var(--color-accent)' : 'var(--color-bg-tertiary)' }}
                >
                  <span
                    className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                    style={{
                      transform: autostart ? 'translateX(20px)' : 'translateX(0)',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                    }}
                  />
                </button>
              </SettingRow>
              <SettingRow
                label="Closing the window"
                description="Nira keeps running in the tray so downloads finish and the API stays up. Quit from the tray icon to stop it."
              >
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  Stays in the tray
                </span>
              </SettingRow>
            </Section>
          )}

          {/* Network — reaching this machine from your other devices */}
          <Section title="Network">
            {networkError && (
              <div
                className="text-xs px-3 py-2 rounded-lg mb-2"
                style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}
              >
                {networkError}
              </div>
            )}
            {network?.error && (
              <div
                className="text-xs px-3 py-2 rounded-lg mb-2"
                style={{ color: 'var(--color-warning, var(--color-error))', border: '1px solid var(--color-border)' }}
              >
                {network.error}
              </div>
            )}

            <SettingRow
              label="Address given to your devices"
              description={
                network?.current
                  ? network.current.note || `Resolved from: ${network.current.kind}`
                  : 'Nothing resolved — pick an address below.'
              }
            >
              <div className="flex items-center gap-2">
                <Wifi
                  size={14}
                  style={{
                    color: network?.current?.reachable_off_machine
                      ? 'var(--color-accent)'
                      : 'var(--color-text-tertiary)',
                  }}
                />
                <span className="text-xs font-mono" style={{ color: 'var(--color-text-secondary)' }}>
                  {network?.current?.url ?? '—'}
                </span>
              </div>
            </SettingRow>

            {network?.current && !network.current.reachable_off_machine && (
              <div className="text-xs px-3 py-2 rounded-lg my-2" style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}>
                This address points at this machine only — another device cannot reach
                it. Pick one below, or type the address your network uses.
              </div>
            )}

            <SettingRow label="How to choose it" description="Automatic prefers a Tailscale address, then your local network.">
              <select
                value={network?.mode ?? 'auto'}
                disabled={!network || networkSaving}
                onChange={(e) => { void saveNetwork({ mode: e.target.value }); }}
                className="text-sm px-3 py-1.5 rounded-lg cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="auto">Automatic</option>
                <option value="tailscale">Tailscale only</option>
                <option value="lan">Local network only</option>
                <option value="manual">A specific address</option>
              </select>
            </SettingRow>

            <SettingRow
              label="Specific address"
              description="An IP or hostname your other devices can reach. Saving one switches the mode above."
            >
              <div className="flex items-center gap-2">
                <input
                  value={networkHost}
                  onChange={(e) => setNetworkHost(e.target.value)}
                  onBlur={() => {
                    const next = networkHost.trim();
                    if (next && next !== (network?.advertise_host ?? '')) {
                      void saveNetwork({ advertise_host: next });
                    }
                  }}
                  placeholder="192.168.1.20"
                  className="w-44 px-2 py-1 rounded text-xs font-mono"
                  style={{
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                />
              </div>
            </SettingRow>

            {(network?.candidates?.length ?? 0) > 0 && (
              <div className="pt-3">
                <div className="text-[11px] uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                  Available on this machine
                </div>
                <div className="flex flex-col gap-1.5">
                  {network!.candidates.map((c) => (
                    <button
                      key={`${c.kind}:${c.host}`}
                      disabled={!c.reachable_off_machine || networkSaving}
                      onClick={() => { void saveNetwork({ advertise_host: c.host, advertise_scheme: c.secure_context ? 'https' : 'http' }); }}
                      className="flex items-start gap-2 px-3 py-2 rounded-lg text-left transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
                      style={{
                        background: 'var(--color-bg-secondary)',
                        border: '1px solid var(--color-border)',
                      }}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-mono truncate" style={{ color: 'var(--color-text)' }}>
                          {c.url}
                        </div>
                        <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                          {c.note}
                        </div>
                      </div>
                      <div className="flex flex-col items-end gap-0.5 shrink-0">
                        {!c.reachable_off_machine && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}>
                            this machine only
                          </span>
                        )}
                        {c.secure_context && c.reachable_off_machine && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}>
                            installable
                          </span>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
                <div className="text-[10px] mt-2" style={{ color: 'var(--color-text-tertiary)' }}>
                  Pair a device with <span className="font-mono">nira device pair &lt;name&gt;</span>. Changing
                  the listening interface needs a server restart.
                </div>
              </div>
            )}
          </Section>

          {/* Model defaults */}
          <Section title="Model Defaults">
            <SettingRow label="Temperature" description={`${settings.temperature}`}>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={settings.temperature}
                onChange={(e) => { updateSettings({ temperature: parseFloat(e.target.value) }); showSaved(); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label="Max tokens" description={`${settings.maxTokens}`}>
              <input
                type="range"
                min="256"
                max="32768"
                step="256"
                value={settings.maxTokens}
                onChange={(e) => { updateSettings({ maxTokens: parseInt(e.target.value) }); showSaved(); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
          </Section>

          {/* Speech */}
          <Section title="Speech">
            <SettingRow label="Speech-to-Text" description="Enable microphone input for voice dictation">
              <button
                onClick={() => { updateSettings({ speechEnabled: !settings.speechEnabled }); showSaved(); }}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: settings.speechEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: settings.speechEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="Backend status" description="Requires Whisper, Deepgram, or another speech backend">
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: speechBackendAvailable === true ? 'var(--color-success)'
                      : speechBackendAvailable === false ? 'var(--color-text-tertiary)'
                      : 'var(--color-text-tertiary)',
                  }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {speechBackendAvailable === null ? 'Checking...'
                    : speechBackendAvailable ? 'Available'
                    : 'Not configured'}
                </span>
              </div>
            </SettingRow>
            {!speechBackendAvailable && speechBackendAvailable !== null && (
              <div className="text-xs mt-2 px-1" style={{ color: 'var(--color-text-tertiary)' }}>
                Set up a speech backend to use voice input.
                See the <a href="https://kmahendra999.github.io/nira/docs/user-guide/tools/" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)' }}>documentation</a> for details.
              </div>
            )}
          </Section>

          {/* Data */}
          <Section title="Data">
            <SettingRow label="Conversations" description={`${conversations.length} stored locally`}>
              <div className="flex gap-2">
                <button
                  onClick={handleExport}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs
                    font-medium transition-colors cursor-pointer border border-border
                    bg-bg-secondary text-text-secondary hover:bg-bg-tertiary"

                >
                  <Download size={12} /> Export
                </button>
                <button
                  onClick={handleImport}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs
                    font-medium transition-colors cursor-pointer border border-border
                    bg-bg-secondary text-text-secondary hover:bg-bg-tertiary"

                >
                  <Upload size={12} /> Import
                </button>
              </div>
            </SettingRow>
            <SettingRow label="Clear all data" description="Permanently delete all conversations">
              <button
                onClick={handleClear}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs
                  font-medium transition-colors cursor-pointer ${
                    confirmClear ? '' : 'hover:bg-error-subtle'
                  }`}
                style={{
                  color: confirmClear ? 'white' : 'var(--color-error)',
                  background: confirmClear ? 'var(--color-error)' : 'transparent',
                  border: '1px solid var(--color-error)',
                }}
              >
                <Trash2 size={12} /> {confirmClear ? 'Click again to confirm' : 'Clear'}
              </button>
            </SettingRow>
          </Section>

          {/* Updates */}
          <Section title="Updates">
            <SettingRow label="Auto-update" description="Check for new desktop builds automatically every 30 minutes">
              <button
                onClick={() => handleAutoUpdateToggle(!autoUpdateEnabled)}
                className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors"
                style={{ background: autoUpdateEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
              >
                <span
                  className="inline-block h-3.5 w-3.5 rounded-full transition-transform"
                  style={{
                    background: 'white',
                    transform: autoUpdateEnabled ? 'translateX(18px)' : 'translateX(2px)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="Check for updates" description="Manually check for a new version right now">
              <button
                onClick={handleCheckNow}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)', color: 'var(--color-text)', cursor: 'pointer' }}
                disabled={updateCheckState === 'checking'}
              >
                <RefreshCw size={12} className={updateCheckState === 'checking' ? 'animate-spin' : ''} />
                {updateCheckState === 'checking' && 'Checking...'}
                {updateCheckState === 'available' && 'Update available — see banner above'}
                {updateCheckState === 'latest' && 'Already up to date'}
                {updateCheckState === 'idle' && 'Check now'}
              </button>
            </SettingRow>
          </Section>

          {/* About */}
          <Section title="About">
            <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              <p className="mb-2">
                <span className="font-semibold" style={{ color: 'var(--color-text)' }}>Nira</span> — Programming abstractions for on-device AI.
              </p>
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                A fork of OpenJarvis, the local-first AI framework from Stanford SAIL.
                Nira is not affiliated with Stanford.
              </p>
              <div className="flex gap-3 mt-3 text-xs">
                <a
                  href="https://kmahendra999.github.io/nira/"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--color-accent)' }}
                >
                  Project site
                </a>
                <a
                  href="https://kmahendra999.github.io/nira/"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--color-accent)' }}
                >
                  Documentation
                </a>
              </div>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
