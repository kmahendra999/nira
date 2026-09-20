/**
 * What Nira remembers, and letting the user see and clear it.
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import {
  getMemoryStats,
  searchMemory,
  storeMemory,
  indexMemoryPath,
} from '../../lib/api';
import type { MemoryStats, MemorySearchResult } from '../../lib/api';
import { isTauri } from '../../lib/api';
import { Loader2, Brain, Search, FolderOpen, FileText } from 'lucide-react';

export function MemorySection() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [statsError, setStatsError] = useState('');

  // Search
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<MemorySearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchDone, setSearchDone] = useState(false);

  // Index
  const [indexPath, setIndexPath] = useState('');
  const [indexing, setIndexing] = useState(false);
  const [indexResult, setIndexResult] = useState('');
  const [indexError, setIndexError] = useState('');

  // Store
  const [storeContent, setStoreContent] = useState('');
  const [storing, setStoring] = useState(false);
  const [storeResult, setStoreResult] = useState('');
  const [storeError, setStoreError] = useState('');

  const statsInterval = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadStats = useCallback(() => {
    getMemoryStats()
      .then((s) => { setStats(s); setStatsError(''); })
      .catch(() => setStatsError('Could not reach memory backend'));
  }, []);

  useEffect(() => {
    loadStats();
    statsInterval.current = setInterval(loadStats, 10000);
    return () => { if (statsInterval.current) clearInterval(statsInterval.current); };
  }, [loadStats]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setSearchDone(false);
    try {
      const results = await searchMemory(searchQuery.trim());
      setSearchResults(results || []);
      setSearchDone(true);
    } catch {
      setSearchResults([]);
      setSearchDone(true);
    } finally {
      setSearching(false);
    }
  };

  const handleBrowse = async () => {
    if (isTauri()) {
      try {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const selected = await open({ directory: true, multiple: false, title: 'Select folder to index' });
        if (selected) setIndexPath(selected as string);
        return;
      } catch {
        // fall through to browser picker
      }
    }
    const input = document.createElement('input');
    input.type = 'file';
    input.setAttribute('webkitdirectory', '');
    input.onchange = () => {
      const files = input.files;
      if (files && files.length > 0) {
        const rel = (files[0] as any).webkitRelativePath || '';
        const folder = rel.split('/')[0];
        if (folder) setIndexPath(folder);
      }
    };
    input.click();
  };

  const handleIndex = async () => {
    if (!indexPath.trim()) return;
    setIndexing(true);
    setIndexResult('');
    setIndexError('');
    try {
      const res = await indexMemoryPath(indexPath.trim());
      setIndexResult(`Indexed ${res.chunks_indexed} chunk${res.chunks_indexed !== 1 ? 's' : ''}`);
      setIndexPath('');
      loadStats();
    } catch (err: any) {
      setIndexError(err.message || 'Indexing failed');
    } finally {
      setIndexing(false);
    }
  };

  const handleStore = async () => {
    if (!storeContent.trim()) return;
    setStoring(true);
    setStoreResult('');
    setStoreError('');
    try {
      await storeMemory(storeContent.trim());
      setStoreResult('Stored successfully');
      setStoreContent('');
      loadStats();
    } catch (err: any) {
      setStoreError(err.message || 'Failed to store');
    } finally {
      setStoring(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Stats overview */}
      <div
        className="rounded-xl p-5 relative overflow-hidden"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        {/* Subtle gradient accent along top edge */}
        <div className="absolute top-0 left-0 right-0 h-[2px]" style={{
          background: 'linear-gradient(90deg, var(--color-accent-purple), var(--color-accent), transparent)',
        }} />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{
              background: 'var(--color-accent-purple-subtle)',
            }}>
              <Brain size={18} style={{ color: 'var(--color-accent-purple)' }} />
            </div>
            <div>
              <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Memory Backend</h3>
              {statsError ? (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{statsError}</p>
              ) : stats ? (
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="w-1.5 h-1.5 rounded-full" style={{
                    background: stats.entries > 0 ? 'var(--color-success)' : 'var(--color-text-tertiary)',
                  }} />
                  <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    {stats.backend} &middot; {stats.entries.toLocaleString()} {stats.entries === 1 ? 'chunk' : 'chunks'}
                  </span>
                </div>
              ) : (
                <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>Connecting...</p>
              )}
            </div>
          </div>
          {stats && stats.entries > 0 && (
            <div className="text-right">
              <div className="text-lg font-bold tabular-nums" style={{ color: 'var(--color-text)' }}>
                {stats.entries.toLocaleString()}
              </div>
              <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--color-text-tertiary)' }}>
                indexed
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Search */}
      <div
        className="rounded-xl p-5"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-2 mb-3">
          <Search size={14} style={{ color: 'var(--color-accent-purple)' }} />
          <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Search Memory</h3>
        </div>
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
              placeholder="What are you looking for?"
              className="w-full text-sm px-3 py-2 rounded-lg transition-colors"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>
          <button
            onClick={handleSearch}
            disabled={searching || !searchQuery.trim()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer whitespace-nowrap"
            style={{
              background: searching || !searchQuery.trim() ? 'var(--color-bg-tertiary)' : 'var(--color-accent-purple)',
              color: searching || !searchQuery.trim() ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
              opacity: searching || !searchQuery.trim() ? 0.6 : 1,
            }}
          >
            {searching ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
            {searching ? 'Searching' : 'Search'}
          </button>
        </div>

        {/* Results */}
        {searchDone && searchResults.length === 0 && (
          <div className="flex flex-col items-center py-6 gap-2">
            <Search size={20} style={{ color: 'var(--color-text-tertiary)', opacity: 0.4 }} />
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>No matching memories found</p>
          </div>
        )}
        {searchResults.length > 0 && (
          <div className="mt-3 space-y-2">
            {searchResults.map((r, i) => (
              <div
                key={i}
                className="rounded-lg p-3 transition-colors"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <p className="text-xs leading-relaxed" style={{ color: 'var(--color-text)' }}>
                  {r.content.length > 250 ? r.content.slice(0, 250) + '...' : r.content}
                </p>
                <div className="flex items-center gap-3 mt-2">
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium" style={{
                    background: r.score > 0.5
                      ? 'rgba(74, 222, 128, 0.1)'
                      : r.score > 0.2
                        ? 'var(--color-accent-amber-subtle)'
                        : 'var(--color-bg-tertiary)',
                    color: r.score > 0.5
                      ? 'var(--color-success)'
                      : r.score > 0.2
                        ? 'var(--color-warning)'
                        : 'var(--color-text-tertiary)',
                  }}>
                    {(r.score * 100).toFixed(0)}% match
                  </span>
                  {r.metadata?.source != null && (
                    <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
                      {String(r.metadata.source)}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add to Memory — two-column grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Index folder */}
        <div
          className="rounded-xl p-5"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center gap-2 mb-3">
            <FolderOpen size={14} style={{ color: 'var(--color-accent-purple)' }} />
            <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Index Folder</h3>
          </div>
          <p className="text-xs mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
            Scan a folder and index all supported files into memory.
          </p>
          <div className="flex gap-2 mb-2">
            <input
              value={indexPath}
              onChange={(e) => setIndexPath(e.target.value)}
              placeholder="~/Documents/notes"
              className="flex-1 text-sm px-3 py-2 rounded-lg"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
            {isTauri() && (
              <button
                onClick={handleBrowse}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium cursor-pointer transition-colors whitespace-nowrap"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-secondary)',
                }}
              >
                <FolderOpen size={12} />
                Browse
              </button>
            )}
          </div>
          <button
            onClick={handleIndex}
            disabled={indexing || !indexPath.trim()}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium cursor-pointer transition-all"
            style={{
              background: indexing || !indexPath.trim() ? 'var(--color-bg-tertiary)' : 'var(--color-accent-purple)',
              color: indexing || !indexPath.trim() ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
              opacity: indexing || !indexPath.trim() ? 0.6 : 1,
            }}
          >
            {indexing && <Loader2 size={13} className="animate-spin" />}
            {indexing ? 'Indexing files...' : 'Index'}
          </button>
          {indexResult && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-success)' }}>{indexResult}</p>
          )}
          {indexError && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-error)' }}>{indexError}</p>
          )}
        </div>

        {/* Paste content */}
        <div
          className="rounded-xl p-5"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center gap-2 mb-3">
            <FileText size={14} style={{ color: 'var(--color-accent-purple)' }} />
            <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Store Text</h3>
          </div>
          <p className="text-xs mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
            Paste any text to add directly to your memory store.
          </p>
          <textarea
            value={storeContent}
            onChange={(e) => setStoreContent(e.target.value)}
            placeholder="Paste or type content here..."
            rows={4}
            className="w-full text-sm px-3 py-2 rounded-lg resize-y"
            style={{
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
              fontFamily: 'inherit',
              minHeight: 80,
              marginBottom: 8,
            }}
          />
          <button
            onClick={handleStore}
            disabled={storing || !storeContent.trim()}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg text-sm font-medium cursor-pointer transition-all"
            style={{
              background: storing || !storeContent.trim() ? 'var(--color-bg-tertiary)' : 'var(--color-accent-purple)',
              color: storing || !storeContent.trim() ? 'var(--color-text-tertiary)' : 'var(--color-on-accent)',
              opacity: storing || !storeContent.trim() ? 0.6 : 1,
            }}
          >
            {storing && <Loader2 size={13} className="animate-spin" />}
            {storing ? 'Storing...' : 'Store'}
          </button>
          {storeResult && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-success)' }}>{storeResult}</p>
          )}
          {storeError && (
            <p className="text-xs mt-2 font-medium" style={{ color: 'var(--color-error)' }}>{storeError}</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

