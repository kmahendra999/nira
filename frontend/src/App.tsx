import { useEffect, useState, useCallback, useRef } from 'react';
import { Routes, Route } from 'react-router';
import { Layout } from './components/Layout';
import { ChatPage } from './pages/ChatPage';
import { DashboardPage } from './pages/DashboardPage';
import { SettingsPage } from './pages/SettingsPage';
import { GetStartedPage } from './pages/GetStartedPage';
import { AgentsPage } from './pages/AgentsPage';
import { DataSourcesPage } from './pages/DataSourcesPage';
import { ResearchPage } from './pages/ResearchPage';
import { LogsPage } from './pages/LogsPage';
import { CommandPalette } from './components/CommandPalette';
import { SetupScreen } from './components/SetupScreen';
import { Toaster } from './components/ui/sonner';
import { useAppStore, onStorageWarning } from './lib/store';
import { fetchModels, fetchServerInfo, fetchSavings, submitSavings, isTauri, onAuthFailure } from './lib/api';
import { toast } from 'sonner';
import { OptInModal } from './components/OptInModal';
import { UpdateChecker } from './components/Desktop/UpdateChecker';
import { track, hashId } from './lib/analytics';
import { useDeepLink } from './lib/useDeepLink';

export default function App() {
  // A 401 used to surface as whatever each caller rendered on failure — most
  // visibly "No models available", which reads as a broken install rather
  // than a server asking for a key. One message for the whole app, with the
  // one action that fixes it.
  useEffect(
    () =>
      onAuthFailure(({ message }) => {
        toast.error('Not authorized', {
          description: message,
          id: 'nira-auth-failure',
          duration: 10000,
          action: {
            label: 'Open Settings',
            onClick: () => {
              window.location.hash = '';
              window.history.pushState({}, '', '/settings');
              window.dispatchEvent(new PopStateEvent('popstate'));
            },
          },
        });
      }),
    [],
  );

  // Storage trouble used to be completely silent: the throw escaped into the
  // stream loop, which swallows it, so a reply stopped mid-sentence and the
  // message was never saved. Say what happened and what it cost.
  useEffect(
    () =>
      onStorageWarning((warning) => {
        if (warning.kind === 'pruned') {
          toast.warning('Storage was full', {
            id: 'nira-storage',
            duration: 8000,
            description: `Removed ${warning.removed} of your oldest conversation${
              warning.removed === 1 ? '' : 's'
            } to make room. Export from Settings → Data to keep them next time.`,
          });
        } else if (warning.kind === 'full') {
          toast.error('Out of storage space', {
            id: 'nira-storage',
            duration: 12000,
            description:
              'This conversation is too large to save. It stays on screen, but ' +
              'it will not survive a restart. Export it from Settings → Data.',
          });
        } else {
          toast.error('Cannot save locally', {
            id: 'nira-storage',
            duration: 12000,
            description: `${warning.detail}. Conversations will not persist.`,
          });
        }
      }),
    [],
  );

  const [setupDone, setSetupDone] = useState(!isTauri());
  const handleSetupReady = useCallback(() => {
    setSetupDone(true);
    // Only fire once per install — guard against setup screen re-appearing
    // on reinstalls or dev reloads.
    if (!localStorage.getItem('oj-setup-completed')) {
      localStorage.setItem('oj-setup-completed', '1');
      track('setup_completed', { preset: 'default' });
    }
  }, []);
  const prevModelRef = useRef<string>('');
  const setModels = useAppStore((s) => s.setModels);
  const setModelsLoading = useAppStore((s) => s.setModelsLoading);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setServerInfo = useAppStore((s) => s.setServerInfo);
  const setSavings = useAppStore((s) => s.setSavings);
  const settings = useAppStore((s) => s.settings);
  const commandPaletteOpen = useAppStore((s) => s.commandPaletteOpen);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const optInEnabled = useAppStore((s) => s.optInEnabled);
  const optInDisplayName = useAppStore((s) => s.optInDisplayName);
  const optInEmail = useAppStore((s) => s.optInEmail);
  const optInAnonId = useAppStore((s) => s.optInAnonId);
  const optInModalSeen = useAppStore((s) => s.optInModalSeen);
  const optInModalOpen = useAppStore((s) => s.optInModalOpen);
  const setOptInModalOpen = useAppStore((s) => s.setOptInModalOpen);
  const markOptInModalSeen = useAppStore((s) => s.markOptInModalSeen);
  const savings = useAppStore((s) => s.savings);

  // Route incoming nira:// links (e.g. the research report links the backend
  // sends over messaging channels) to the right screen.
  useDeepLink();

  // Apply theme class to <html>
  useEffect(() => {
    const root = document.documentElement;
    const media =
      typeof window !== 'undefined' && typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-color-scheme: dark)')
        : null;

    const apply = () => {
      const dark =
        settings.theme === 'dark' ||
        (settings.theme === 'system' && !!media?.matches);
      root.classList.toggle('dark', dark);
      root.classList.toggle('light', !dark);
    };
    apply();

    // On `system`, follow the OS while the app is open. The CSS media query
    // this replaces did that for free; resolving the theme in one place costs
    // us an explicit listener.
    if (settings.theme !== 'system' || !media) return;
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [settings.theme]);

  // Sync overlay conversations into the main app
  const importOverlay = useAppStore((s) => s.importOverlayConversation);
  useEffect(() => {
    if (!isTauri()) return;
    importOverlay();
    const interval = setInterval(importOverlay, 5000);
    return () => clearInterval(interval);
  }, [importOverlay]);

  // Fetch models on mount
  useEffect(() => {
    let cancelled = false;

    const load = () =>
      fetchModels()
        .then((m) => {
          if (!cancelled) setModels(m);
        })
        // Not setModels([]): a failed fetch is not the same fact as "you have
        // no models", and reporting it as one cleared the user's selection on
        // every transient failure. Leave the last known list alone; the auth
        // toast and the picker's own empty state explain the failure.
        .catch(() => {})
        .finally(() => {
          if (!cancelled) setModelsLoading(false);
        });

    void load();

    // Retry until it works, then stop.
    //
    // This ran once, in a mount effect with an empty dep array, and nothing
    // ever re-ran it. So every recoverable cause of an empty list was in
    // practice permanent: pasting the API key into Settings fixed the auth
    // but left the picker empty, and a list fetched while `nira serve` was
    // still starting stayed empty until the window was reloaded. Both are
    // states the user is actively trying to get out of.
    const interval = setInterval(() => {
      if (cancelled) return;
      if (useAppStore.getState().models.length > 0) {
        clearInterval(interval);
        return;
      }
      void load();
    }, 5000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch server info
  useEffect(() => {
    fetchServerInfo().then(setServerInfo).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll savings and optionally share to Supabase
  useEffect(() => {
    const refresh = () =>
      fetchSavings()
        .then((data) => {
          setSavings(data);
          if (optInEnabled && optInDisplayName && data) {
            const claudeEntry = data.per_provider.find(
              (p) => p.provider === 'claude-fable-5',
            );
            const dollarSavings = claudeEntry ? claudeEntry.total_cost : 0;
            const energySaved = data.per_provider.reduce(
              (sum, p) => sum + (p.energy_wh || 0),
              0,
            );
            const flopsSaved = data.per_provider.reduce(
              (sum, p) => sum + (p.flops || 0),
              0,
            );
            submitSavings({
              anon_id: optInAnonId,
              display_name: optInDisplayName,
              email: optInEmail,
              total_calls: data.total_calls,
              total_tokens: data.total_tokens,
              dollar_savings: dollarSavings,
              energy_wh_saved: energySaved,
              flops_saved: flopsSaved,
              token_counting_version: data.token_counting_version ?? 1,
            });
          }
        })
        .catch(() => {});
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [optInEnabled, optInDisplayName, optInAnonId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Show opt-in modal on first visit
  useEffect(() => {
    if (!optInModalSeen) {
      setOptInModalOpen(true);
      markOptInModalSeen();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fire model_changed when the user switches models. First mount is
  // not a "change" — only emit when both prev and current are real and
  // differ.
  useEffect(() => {
    const prev = prevModelRef.current;
    const curr = selectedModel || '';
    prevModelRef.current = curr;
    if (!prev || !curr || prev === curr) return;
    void (async () => {
      const [fromHash, toHash] = await Promise.all([
        hashId(prev),
        hashId(curr),
      ]);
      track('model_changed', {
        from_model_hash: fromHash,
        to_model_hash: toHash,
      });
    })();
  }, [selectedModel]);

  // app_opened — one-shot per app launch, fires after analytics has had
  // a chance to initialize. platform + version are super-properties
  // registered in analytics.ts initAnalytics, so no per-call props needed.
  useEffect(() => {
    const t = setTimeout(() => {
      track('app_opened', {});
    }, 500);
    return () => clearTimeout(t);
  }, []);

  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'i') {
        e.preventDefault();
        toggleSystemPanel();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [commandPaletteOpen, setCommandPaletteOpen, toggleSystemPanel]);


  if (!setupDone) {
    return <SetupScreen onReady={handleSetupReady} />;
  }

  return (
    <>
      <UpdateChecker />
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<ChatPage />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="get-started" element={<GetStartedPage />} />
          <Route path="data-sources" element={<DataSourcesPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="logs" element={<LogsPage />} />
          <Route path="research" element={<ResearchPage />} />
          <Route path="research/:id" element={<ResearchPage />} />
        </Route>
      </Routes>
      <Toaster position="bottom-right" />
      {commandPaletteOpen && <CommandPalette />}
      {optInModalOpen && (
        <OptInModal onClose={() => setOptInModalOpen(false)} />
      )}
    </>
  );
}
