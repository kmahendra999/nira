/**
 * Uploading files as a data source, and the sync status beside them.
 */

import { useState } from 'react';
import { getBase } from '../../lib/api';
import { Upload } from 'lucide-react';
import type { SyncStatus } from '../../types/connectors';
import { listConnectors, triggerSync } from '../../lib/connectors-api';

export const ACCEPTED_EXTENSIONS = '.txt,.md,.pdf,.docx,.csv';

export function formatBacklogRange(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const days = (Date.now() - t) / 86400_000;
  if (days < 7) return 'past few days';
  if (days < 30) return 'past month';
  if (days < 90) return 'past 3 months';
  if (days < 365) return 'past year';
  const years = Math.round(days / 365);
  return `past ${years} year${years === 1 ? '' : 's'}`;
}

export function formatTimeAgo(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const diffSec = (Date.now() - t) / 1000;
  if (diffSec < 30) return 'just now';
  if (diffSec < 60) return 'less than a min ago';
  if (diffSec < 3600) {
    const m = Math.round(diffSec / 60);
    return `${m} min${m === 1 ? '' : 's'} ago`;
  }
  if (diffSec < 86400) {
    const h = Math.round(diffSec / 3600);
    return `${h} hr${h === 1 ? '' : 's'} ago`;
  }
  const d = Math.round(diffSec / 86400);
  return `${d} day${d === 1 ? '' : 's'} ago`;
}

/** Render how far back the corpus extends, given the oldest indexed
 *  item's timestamp. Returns null when there isn't enough data yet. */

export function UploadForm({ onDone }: { onDone?: () => void }) {
  const [tab, setTab] = useState<'paste' | 'upload'>('paste');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState('');
  const [error, setError] = useState('');

  const handlePaste = async () => {
    if (!content.trim()) return;
    setBusy(true);
    setError('');
    setResult('');
    try {
      const res = await fetch(`${getBase()}/v1/connectors/upload/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), content }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Upload failed: ${res.status}`);
      }
      const data = await res.json();
      setResult(`Added ${data.chunks_added} chunk${data.chunks_added !== 1 ? 's' : ''} to knowledge base`);
      setTitle('');
      setContent('');
      onDone?.();
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setBusy(false);
    }
  };

  const handleUpload = async () => {
    if (files.length === 0) return;
    setBusy(true);
    setError('');
    setResult('');
    try {
      const formData = new FormData();
      for (const f of files) formData.append('files', f);
      if (title.trim()) formData.append('title', title.trim());

      const res = await fetch(`${getBase()}/v1/connectors/upload/ingest/files`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `Upload failed: ${res.status}`);
      }
      const data = await res.json();
      setResult(`Added ${data.chunks_added} chunk${data.chunks_added !== 1 ? 's' : ''} from ${files.length} file${files.length !== 1 ? 's' : ''}`);
      setFiles([]);
      setTitle('');
      onDone?.();
    } catch (err: any) {
      setError(err.message || 'Upload failed');
    } finally {
      setBusy(false);
    }
  };

  const tabStyle = (active: boolean): React.CSSProperties => ({
    flex: 1, padding: '6px 0', textAlign: 'center',
    fontSize: 12, fontWeight: 600, cursor: 'pointer',
    background: active ? 'var(--color-accent-purple)' : 'transparent',
    color: active ? 'white' : 'var(--color-text-secondary)',
    border: 'none', borderRadius: 4,
  });

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '7px 10px',
    background: 'var(--color-bg)',
    border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)',
    fontSize: 12, marginBottom: 6,
    boxSizing: 'border-box' as const,
  };

  return (
    <div>
      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 10,
        background: 'var(--color-bg)', borderRadius: 6, padding: 2 }}>
        <button style={tabStyle(tab === 'paste')} onClick={() => setTab('paste')}>
          Paste Text
        </button>
        <button style={tabStyle(tab === 'upload')} onClick={() => setTab('upload')}>
          Upload Files
        </button>
      </div>

      {/* Title input (shared) */}
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title (optional)"
        style={inputStyle}
      />

      {tab === 'paste' && (
        <>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Paste your text here..."
            rows={6}
            style={{
              ...inputStyle,
              resize: 'vertical',
              fontFamily: 'inherit',
              minHeight: 100,
            }}
          />
          <button
            onClick={handlePaste}
            disabled={busy || !content.trim()}
            style={{
              width: '100%', padding: 8,
              background: busy || !content.trim() ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)', border: 'none',
              borderRadius: 6, fontSize: 12, cursor: 'pointer',
            }}
          >
            {busy ? 'Adding...' : 'Add to Knowledge Base'}
          </button>
        </>
      )}

      {tab === 'upload' && (
        <>
          <input
            type="file"
            multiple
            accept={ACCEPTED_EXTENSIONS}
            onChange={(e) => {
              const selected = Array.from(e.target.files || []);
              setFiles(selected);
            }}
            style={{ ...inputStyle, padding: 6 }}
          />
          {files.length > 0 && (
            <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 6 }}>
              {files.map((f) => f.name).join(', ')}
            </div>
          )}
          <button
            onClick={handleUpload}
            disabled={busy || files.length === 0}
            style={{
              width: '100%', padding: 8,
              background: busy || files.length === 0 ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)', border: 'none',
              borderRadius: 6, fontSize: 12, cursor: 'pointer',
            }}
          >
            {busy ? 'Uploading...' : 'Upload & Index'}
          </button>
        </>
      )}

      {result && (
        <div style={{ fontSize: 12, color: 'var(--color-success)', marginTop: 8 }}>
          {result}
        </div>
      )}
      {error && (
        <div style={{ fontSize: 12, color: 'var(--color-error)', marginTop: 8 }}>
          {error}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Icon map
// ---------------------------------------------------------------------------

export function SyncStatusDisplay({
  chunks,
  sync,
  unitLabel,
  connectorId,
  disabled = false,
  onSyncTriggered,
}: {
  chunks: number;
  sync: SyncStatus | undefined;
  unitLabel: string;
  connectorId: string;
  disabled?: boolean;
  onSyncTriggered: () => void;
}) {
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState('');

  const handleSync = async () => {
    if (disabled || sync?.state === 'stopping') return;
    setSyncing(true);
    setSyncError('');
    try {
      await triggerSync(connectorId);
      onSyncTriggered();
    } catch (err: any) {
      setSyncError(err.message || 'Sync failed');
    } finally {
      setSyncing(false);
    }
  };

  // Disconnect cleanup only begins after the active sync worker exits. Keep
  // every competing lifecycle action unavailable while the backend reports
  // this transitional state; the disconnect handler retries automatically.
  if (sync?.state === 'stopping') {
    return (
      <div>
        <div style={{ fontSize: 12, color: 'var(--color-warning)', marginBottom: 4 }}>
          Disconnect pending — waiting for the active sync to stop.
        </div>
        <div style={{ fontSize: 10.5, color: 'var(--color-text-tertiary)' }}>
          Indexed data will be cleaned up before this source disconnects.
        </div>
      </div>
    );
  }

  // Error state
  if (sync?.error) {
    return (
      <div>
        <div style={{ fontSize: 12, color: 'var(--color-error)', marginBottom: 4 }}>
          Error: {sync.error}
        </div>
        <button
          onClick={handleSync}
          disabled={syncing || disabled}
          style={{
            fontSize: 10, padding: '2px 10px',
            background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
            border: 'none', borderRadius: 3,
            cursor: syncing || disabled ? 'default' : 'pointer', fontWeight: 600,
            opacity: syncing || disabled ? 0.5 : 1,
          }}
        >{syncing ? 'Retrying...' : 'Retry Sync'}</button>
      </div>
    );
  }

  // Treat the SyncEngine's checkpointed items_synced as the source of
  // truth for "total indexed" — `chunks` from listConnectors counts
  // embedding chunks (often != source items) and the checkpoint is what
  // both the syncing and idle branches need to display consistently.
  const totalIndexed = sync?.items_synced ?? chunks;
  const itemsTotal = sync?.items_total ?? 0;
  const backlogRange = formatBacklogRange(sync?.oldest_item_date);
  // "Complete inbox" — the user has indexed everything reachable. Only
  // surface this label when idle (during a sync we always show how far
  // back we've gotten so far).
  const isComplete =
    totalIndexed > 0 && itemsTotal > 0 && totalIndexed >= itemsTotal;

  // Actively syncing — single status line + reassurance line.
  if (sync?.state === 'syncing' || syncing) {
    const rangeLabel = backlogRange ?? 'building corpus';
    return (
      <div>
        <div style={{ fontSize: 11, color: 'var(--color-warning)', marginBottom: 4 }}>
          Indexed{' '}
          <span key={totalIndexed} className="sync-bump">
            {totalIndexed.toLocaleString()} {unitLabel}
          </span>{' '}
          <span style={{ color: 'var(--color-text-tertiary)' }}>
            ({rangeLabel})
          </span>{' '}
          <span style={{ color: 'var(--color-text-tertiary)' }}>
            · Still indexing…
          </span>
        </div>
        <div style={{ fontSize: 10.5, color: 'var(--color-text-tertiary)' }}>
          Deep Research available now · results improve as more {unitLabel} are indexed
        </div>
      </div>
    );
  }

  // Idle — already has indexed items: show the corpus size + range or
  // "complete inbox" label, plus how long ago we last refreshed it.
  if (totalIndexed > 0) {
    const lastSyncLabel = formatTimeAgo(sync?.last_sync);
    const rangeLabel = isComplete
      ? 'complete inbox'
      : backlogRange;
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--color-success)' }}>
            Indexed {totalIndexed.toLocaleString()} {unitLabel}
            {rangeLabel && (
              <span style={{ color: 'var(--color-text-tertiary)' }}>
                {' '}({rangeLabel})
              </span>
            )}
            {lastSyncLabel && (
              <span style={{ color: 'var(--color-text-tertiary)' }}>
                {' · '}Last synced {lastSyncLabel}
              </span>
            )}
          </span>
          <button
            onClick={handleSync}
            disabled={syncing || disabled}
            style={{
              fontSize: 9, padding: '1px 6px',
              background: 'transparent',
              color: 'var(--color-text-tertiary)',
              border: '1px solid var(--color-border)',
              borderRadius: 3,
              cursor: syncing || disabled ? 'default' : 'pointer',
              opacity: syncing || disabled ? 0.5 : 1,
            }}
          >{syncing ? '...' : 'Re-sync'}</button>
        </div>
        {syncError && (
          <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 4 }}>
            {syncError}
          </div>
        )}
      </div>
    );
  }

  // Connected but nothing ever ingested. Mirror the original copy.
  const hasSynced = sync?.last_sync != null;
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>
          {hasSynced
            ? `Synced — 0 ${unitLabel} found`
            : 'Connected — not synced yet'}
        </span>
        <button
          onClick={handleSync}
          disabled={syncing || disabled}
          style={{
            fontSize: 10, padding: '2px 10px',
            background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
            border: 'none', borderRadius: 3,
            cursor: syncing || disabled ? 'default' : 'pointer', fontWeight: 600,
            opacity: syncing || disabled ? 0.5 : 1,
          }}
        >{syncing ? 'Syncing...' : hasSynced ? 'Re-sync' : 'Sync Now'}</button>
      </div>
      {hasSynced && connectorId === 'slack' && (
        <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 4 }}>
          Tip: invite the bot to channels with /invite @Nira, then re-sync
        </div>
      )}
      {syncError && (
        <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 4 }}>
          {syncError}
        </div>
      )}
    </div>
  );
}

