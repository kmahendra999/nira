/**
 * The list of connectable sources, and what is already connected.
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { useAppStore } from '../../lib/store';
import { Upload } from 'lucide-react';
import type { ConnectRequest, SyncStatus } from '../../types/connectors';
import {
  listConnectors,
  connectSource,
  disconnectSourceUntilComplete,
  getSyncStatus,
  triggerSync,
  startServerOAuth,
} from '../../lib/connectors-api';
import { SyncStatusDisplay, UploadForm } from '../data-sources/UploadForm';
import {
  GenericConnectPanel,
  GmailOAuthAdvanced,
  InlineConnectForm,
} from './ConnectPanels';
import { metaFor } from './catalog';

export function DataSourcesSection() {
  const cachedConnectors = useAppStore((s) => s.cachedConnectors);
  const setCachedConnectors = useAppStore((s) => s.setCachedConnectors);
  const connectors = cachedConnectors ?? [];
  const isFirstLoad = cachedConnectors === null;
  const [syncStatuses, setSyncStatuses] = useState<Record<string, SyncStatus>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [disconnectError, setDisconnectError] = useState<{ id: string; message: string } | null>(null);
  const disconnectAbortRef = useRef<AbortController | null>(null);

  const loadConnectors = useCallback(async () => {
    try {
      const list = await listConnectors();
      setCachedConnectors(
        list.map((c) => ({
          connector_id: c.connector_id,
          display_name: c.display_name,
          connected: c.connected,
          chunks: (c as any).chunks || 0,
          auth_type: c.auth_type,
        })),
      );
    } catch {
      // The periodic refresh will try again.
    }
  }, [setCachedConnectors]);

  const setConnectors = setCachedConnectors;

  // Poll sync status for connected sources
  const loadSyncStatuses = useCallback(async () => {
    const connected = connectors.filter((c) => c.connected);
    const statuses: Record<string, SyncStatus> = {};
    await Promise.all(
      connected.map(async (c) => {
        try {
          statuses[c.connector_id] = await getSyncStatus(c.connector_id);
        } catch { /* */ }
      }),
    );
    setSyncStatuses((prev) => ({ ...prev, ...statuses }));
  }, [connectors]);

  useEffect(() => {
    void loadConnectors();
    const interval = setInterval(() => void loadConnectors(), 10000);
    return () => clearInterval(interval);
  }, [loadConnectors]);

  useEffect(() => {
    if (connectors.some((c) => c.connected)) {
      loadSyncStatuses();
      const interval = setInterval(loadSyncStatuses, 5000);
      return () => clearInterval(interval);
    }
  }, [connectors, loadSyncStatuses]);

  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [connectStage, setConnectStage] = useState<string>('');
  const [connectError, setConnectError] = useState<string>('');

  useEffect(() => () => disconnectAbortRef.current?.abort(), []);

  const handleDisconnect = async (id: string) => {
    if (disconnectAbortRef.current || loading) return;
    const controller = new AbortController();
    disconnectAbortRef.current = controller;
    setDisconnectingId(id);
    setDisconnectError(null);
    try {
      await disconnectSourceUntilComplete(id, {
        signal: controller.signal,
        onPending: () => {
          setSyncStatuses((prev) => {
            const current = prev[id];
            return {
              ...prev,
              [id]: {
                state: 'stopping',
                items_synced: current?.items_synced ?? 0,
                items_total: current?.items_total ?? 0,
                new_items_synced: current?.new_items_synced ?? null,
                oldest_item_date: current?.oldest_item_date ?? null,
                last_sync: current?.last_sync ?? null,
                error: null,
              },
            };
          });
        },
      });
      setSyncStatuses((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      await loadConnectors();
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        setDisconnectError({
          id,
          message: err instanceof Error ? err.message : 'Disconnect failed',
        });
      }
    } finally {
      if (disconnectAbortRef.current === controller) {
        disconnectAbortRef.current = null;
        setDisconnectingId(null);
      }
    }
  };

  const handleConnect = async (id: string, req: ConnectRequest | null) => {
    if (loading || disconnectAbortRef.current) return;
    setLoading(true);
    setConnectingId(id);
    setConnectStage('Connecting...');
    setConnectError('');
    try {
      const resp = req === null ? null : await connectSource(id, req);

      // OAuth connectors (Google Drive/Calendar/Contacts/Gmail/Tasks): pasting
      // a Client ID / Secret only registers the app credentials. The backend
      // returns `oauth_required` with the path to the in-process consent flow,
      // which is the only path that actually mints an access token. Open it now
      // and wait for the callback to flip the connector to connected. Without
      // this the connector would stay "pending" forever — the exact #512 bug.
      if (req === null || resp?.status === 'oauth_required') {
        setConnectStage('Opening provider sign-in...');
        await startServerOAuth(id, resp?.oauth_start);
      }

      setConnectStage('Connected! Starting sync...');

      // Wait for connector to show as connected
      for (let i = 0; i < 20; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const updated = await listConnectors();
        const target = updated.find((c) => c.connector_id === id);
        if (target?.connected) {
          setConnectors(updated.map((c) => ({
            connector_id: c.connector_id,
            display_name: c.display_name,
            connected: c.connected,
            chunks: (c as any).chunks || 0,
            auth_type: c.auth_type,
          })));
          break;
        }
        setConnectStage(i < 5 ? 'Authenticating...' : 'Waiting for connection...');
      }

      // Trigger sync
      setConnectStage('Syncing data...');
      try {
        await triggerSync(id);
      } catch { /* sync may already be running */ }

      // Close form after a brief moment
      await new Promise((r) => setTimeout(r, 1500));
      setExpandedId(null);
      loadConnectors();
      loadSyncStatuses();
    } catch (err: any) {
      let errorMsg = err.message || 'Connection failed';
      if (id === 'gmail_imap' && (errorMsg.includes('auth') || errorMsg.includes('credentials') || errorMsg.includes('LOGIN'))) {
        errorMsg = 'Invalid credentials — make sure you\'re using an App Password (16 characters), not your regular Gmail password.';
      }
      setConnectError(errorMsg);
      setConnectStage('');
    } finally {
      setLoading(false);
      setConnectingId(null);
      setConnectStage('');
    }
  };

  // Merge the OAuth Gmail (`gmail`) and IMAP Gmail (`gmail_imap`) backend
  // connectors into a single user-facing Gmail card. IMAP is the default
  // flow (no Google Cloud setup needed); OAuth lives behind an "Advanced"
  // disclosure when the card is expanded. If both happen to be connected,
  // keep whichever has more indexed chunks so the active source still
  // surfaces its sync state.
  const unifiedConnectors = (() => {
    const gmail = connectors.find((c) => c.connector_id === 'gmail');
    const gmailImap = connectors.find((c) => c.connector_id === 'gmail_imap');
    if (!gmail || !gmailImap) return connectors;
    if (gmail.connected && !gmailImap.connected) {
      return connectors.filter((c) => c.connector_id !== 'gmail_imap');
    }
    if (gmailImap.connected && !gmail.connected) {
      return connectors.filter((c) => c.connector_id !== 'gmail');
    }
    if (gmail.connected && gmailImap.connected) {
      const dropId = gmail.chunks >= gmailImap.chunks ? 'gmail_imap' : 'gmail';
      return connectors.filter((c) => c.connector_id !== dropId);
    }
    // Neither connected — show only the IMAP card as the default flow.
    return connectors.filter((c) => c.connector_id !== 'gmail');
  })();

  const connected = unifiedConnectors.filter((c) => c.connected);
  const notConnectedBase = unifiedConnectors.filter((c) => !c.connected);
  // Always show the upload card in the not-connected list (it has no backend connector)
  const uploadEntry = { connector_id: 'upload', display_name: 'Upload / Paste', connected: false, chunks: 0, auth_type: 'local' };
  const notConnected = notConnectedBase.some((c) => c.connector_id === 'upload')
    ? notConnectedBase
    : [...notConnectedBase, uploadEntry];
  const connectorActionsBusy = loading || disconnectingId !== null;

  if (isFirstLoad) {
    return (
      <div className="flex flex-col gap-5">
        <section>
          <div className="hud-label mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Loading sources…
          </div>
          <div className="flex flex-col gap-2">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="hud-panel data-skeleton"
                style={{
                  padding: '14px 18px',
                  height: 60,
                  opacity: 0.6 - i * 0.08,
                }}
              />
            ))}
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Connected sources */}
      {connected.length > 0 && (
        <section>
          <div className="hud-label mb-2 flex items-center gap-2">
            <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: 999, background: 'var(--color-success)' }} />
            Connected · {connected.length}
          </div>
          <div className="flex flex-col gap-2">
          {connected.map((c) => {
            const meta = metaFor(c.connector_id);
            const unit = meta?.unitLabel || 'items';
            const sync = syncStatuses[c.connector_id];
            const hasError = !!sync?.error;
            return (
              <div
                key={c.connector_id}
                className="hud-panel"
                style={{
                  borderColor: hasError
                    ? 'color-mix(in srgb, var(--color-error) 28%, transparent)'
                    : 'var(--color-border)',
                }}
              >
                <div style={{
                  padding: '14px 18px',
                  display: 'flex', alignItems: 'center', gap: 14,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="font-semibold" style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)' }}>
                      {meta?.display_name ?? c.display_name}
                    </div>
                    <SyncStatusDisplay
                      chunks={c.chunks}
                      sync={sync}
                      unitLabel={unit}
                      connectorId={c.connector_id}
                      disabled={connectorActionsBusy}
                      onSyncTriggered={loadConnectors}
                    />
                    {disconnectError?.id === c.connector_id && (
                      <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 4 }}>
                        Disconnect failed: {disconnectError.message}
                      </div>
                    )}
                  </div>
                  <button
                    onClick={() => handleDisconnect(c.connector_id)}
                    disabled={connectorActionsBusy}
                    className="hud-label"
                    style={{
                      padding: '6px 12px',
                      background: 'transparent',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 4,
                      cursor: connectorActionsBusy ? 'default' : 'pointer',
                      letterSpacing: '0.15em',
                      opacity: connectorActionsBusy ? 0.5 : 1,
                    }}
                  >
                    {disconnectingId === c.connector_id
                      ? sync?.state === 'stopping' ? 'Cleaning up…' : 'Disconnecting…'
                      : sync?.state === 'stopping' ? 'Finish disconnect' : 'Disconnect'}
                  </button>
                </div>
              </div>
            );
          })}
          </div>
        </section>
      )}

      {/* Not connected list */}
      {notConnected.length > 0 && (
        <section>
          <div className="hud-label mb-2 flex items-center gap-2">
            <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: 999, background: 'var(--color-text-tertiary)' }} />
            Available · {notConnected.length}
          </div>
          <div className="grid grid-cols-2 gap-2">
          {notConnected.map((c) => {
            const meta = metaFor(c.connector_id);
            const isExpanded = expandedId === c.connector_id;

            return (
              <div
                key={c.connector_id}
                className="hud-panel"
                style={{
                  gridColumn: isExpanded ? '1 / -1' : undefined,
                  opacity: isExpanded ? 1 : 0.85,
                  borderStyle: isExpanded ? 'solid' : 'dashed',
                }}
              >
                {/* A real button, now that this file is small enough to
                    restructure. role="button" was the stand-in while these
                    rows lived in a four-thousand-line page: it announces the
                    same thing, but Enter and Space had to be hand-written. */}
                <button
                  type="button"
                  aria-expanded={isExpanded}
                  style={{
                    padding: '12px 14px', display: 'flex',
                    alignItems: 'center', gap: 12,
                    cursor: 'pointer', width: '100%', textAlign: 'left',
                    background: 'none', border: 'none', font: 'inherit',
                    color: 'inherit',
                  }}
                  onClick={() => setExpandedId(isExpanded ? null : c.connector_id)}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="font-semibold" style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)' }}>
                      {meta?.display_name ?? c.display_name}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginTop: 2 }}>
                      {meta?.description ?? 'Not connected'}
                    </div>
                  </div>
                  <span style={{ color: 'var(--color-text-secondary)', fontSize: 12, fontWeight: 500 }}>
                    {isExpanded ? '× Close' : '+ Add'}
                  </span>
                </button>

                {isExpanded && c.connector_id === 'upload' && (
                  <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
                    <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
                      Paste text or upload files (.txt, .md, .pdf, .docx, .csv) to add them to your knowledge base.
                    </div>
                    <UploadForm onDone={loadConnectors} />
                  </div>
                )}

                {isExpanded && c.connector_id !== 'upload' && meta?.steps && (
                  <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
                    {meta.steps.map((step, i) => (
                      <div
                        key={i}
                        style={{
                          background: 'var(--color-bg)',
                          border: '1px solid var(--color-border)',
                          borderRadius: 6, padding: 10,
                          marginBottom: 8,
                        }}
                      >
                        <div style={{ color: 'var(--color-accent-purple)', fontSize: 10, fontWeight: 600, marginBottom: 3 }}>
                          STEP {i + 1}
                        </div>
                        <div style={{ fontSize: 12, marginBottom: step.url ? 4 : 0 }}>{step.label}</div>
                        {step.url && (
                          <a
                            href={step.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: 'var(--color-accent)', fontSize: 11, textDecoration: 'underline' }}
                          >
                            {step.urlLabel || 'Open'} &rarr;
                          </a>
                        )}
                      </div>
                    ))}
                    {meta?.inputFields && (
                      <InlineConnectForm
                        fields={meta.inputFields}
                        loading={loading && connectingId === c.connector_id}
                        disabled={connectorActionsBusy}
                        onSubmit={(req) => handleConnect(c.connector_id, req)}
                      />
                    )}
                    {c.connector_id === 'gmail_imap' && (
                      <GmailOAuthAdvanced
                        loading={loading && connectingId === 'gmail'}
                        disabled={connectorActionsBusy}
                        onConnect={(req) => handleConnect('gmail', req)}
                      />
                    )}
                    {meta?.troubleshooting && (
                      <details className="mt-2">
                        <summary className="text-[11px] cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}>
                          Having trouble?
                        </summary>
                        <ul className="mt-1 space-y-1">
                          {meta.troubleshooting.map((tip: string, i: number) => (
                            <li key={i} className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                              {tip}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                    {/* Connection progress */}
                    {connectingId === c.connector_id && connectStage && (
                      <div style={{ marginTop: 8 }}>
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: 6,
                          fontSize: 12, color: 'var(--color-warning)',
                        }}>
                          <div className="animate-spin" style={{
                            width: 12, height: 12, borderRadius: '50%',
                            border: '2px solid var(--color-warning)',
                            borderTopColor: 'transparent',
                          }} />
                          {connectStage}
                        </div>
                        <div style={{
                          height: 3, borderRadius: 2, marginTop: 6,
                          background: 'var(--color-bg-tertiary)',
                          overflow: 'hidden',
                        }}>
                          <div style={{
                            height: '100%', borderRadius: 2, background: 'var(--color-warning)',
                            width: connectStage.includes('Sync') ? '75%' : connectStage.includes('Connected') ? '50%' : '25%',
                            transition: 'width 0.5s ease',
                          }} />
                        </div>
                      </div>
                    )}
                    {/* Connection error */}
                    {connectError && connectingId === null && expandedId === c.connector_id && (
                      <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
                        {connectError}
                      </div>
                    )}
                  </div>
                )}

                {isExpanded && c.connector_id !== 'upload' && !meta?.steps && (
                  <div style={{ borderTop: '1px solid var(--color-border)', padding: 12 }}>
                    <GenericConnectPanel
                      connectorId={c.connector_id}
                      displayName={meta?.display_name ?? c.display_name}
                      authType={c.auth_type || 'oauth'}
                      loading={loading && connectingId === c.connector_id}
                      disabled={connectorActionsBusy}
                      onConnect={(req) => handleConnect(c.connector_id, req)}
                      onOAuthStart={() => handleConnect(c.connector_id, null)}
                    />
                    {connectingId === c.connector_id && connectStage && (
                      <div style={{ marginTop: 8, fontSize: 12, color: 'var(--color-warning)' }}>
                        {connectStage}
                      </div>
                    )}
                    {connectError && connectingId === null && expandedId === c.connector_id && (
                      <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
                        {connectError}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Messaging channels section
// ---------------------------------------------------------------------------

