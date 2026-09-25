import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ModelInfo } from '../types';

class MemoryStorage {
  private store = new Map<string, string>();

  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

const model = (id: string): ModelInfo => ({
  id,
  object: 'model',
  created: 0,
  owned_by: 'nira',
});

beforeEach(() => {
  vi.resetModules();
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
});

afterEach(() => {
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage =
    undefined;
});

describe('setModels', () => {
  it('does not select an embedding-only model', async () => {
    const { useAppStore } = await import('./store');

    useAppStore.getState().setModels([model('nomic-embed-text')]);

    expect(useAppStore.getState().selectedModel).toBe('');
  });

  it('clears a missing selection when no chat fallback exists', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.getState().setSelectedModel('deleted-chat-model');

    useAppStore.getState().setModels([model('nomic-embed-text')]);

    expect(useAppStore.getState().selectedModel).toBe('');
  });

  it('replaces an embedding selection with an available chat model', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.getState().setSelectedModel('all-minilm:latest');

    useAppStore.getState().setModels([
      model('all-minilm:latest'),
      model('qwen3.5:4b'),
    ]);

    expect(useAppStore.getState().selectedModel).toBe('qwen3.5:4b');
  });
});

describe('an empty model list is not proof a model is gone', () => {
  // The user's report: "after downloading model it is reverting automatically
  // and not stable". App.tsx called setModels([]) from a .catch(), so every
  // transient failure — a 401, a server restart — read as "you have zero
  // models" and cleared the selection. The next successful poll put it back.
  // That flapping is the instability.

  it('keeps the selection when the list comes back empty', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.getState().setModels([model('qwen3.5:4b'), model('qwen3.5:9b')]);
    useAppStore.getState().setSelectedModel('qwen3.5:9b');

    useAppStore.getState().setModels([]);

    expect(useAppStore.getState().selectedModel).toBe('qwen3.5:9b');
  });

  it('does not flip the selection back to auto-picked', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.getState().setModels([model('qwen3.5:4b')]);
    useAppStore.getState().setSelectedModel('qwen3.5:4b');
    expect(useAppStore.getState().modelWasAutoPicked).toBe(false);

    useAppStore.getState().setModels([]);

    expect(useAppStore.getState().modelWasAutoPicked).toBe(false);
  });

  it('still clears a selection that is genuinely absent from a real list', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.getState().setModels([model('qwen3.5:4b'), model('qwen3.5:9b')]);
    useAppStore.getState().setSelectedModel('qwen3.5:9b');

    // A list we actually received, without it — the model really was deleted.
    useAppStore.getState().setModels([model('qwen3.5:4b')]);

    expect(useAppStore.getState().selectedModel).toBe('qwen3.5:4b');
  });

  it('still rejects an embed-only selection even when the list is empty', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.setState({ selectedModel: 'nomic-embed-text' });

    useAppStore.getState().setModels([]);

    // An embedder 400s on every chat; keeping it is worse than clearing it.
    expect(useAppStore.getState().selectedModel).not.toBe('nomic-embed-text');
  });

  it('a first-ever empty list on a fresh install still picks nothing', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.setState({ selectedModel: '', models: [] });

    useAppStore.getState().setModels([]);

    expect(useAppStore.getState().selectedModel).toBe('');
  });

  it('survives a run of failures between two good fetches', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.getState().setModels([model('qwen3.5:27b')]);
    useAppStore.getState().setSelectedModel('qwen3.5:27b');

    useAppStore.getState().setModels([]); // 401
    useAppStore.getState().setModels([]); // still 401
    useAppStore.getState().setModels([model('qwen3.5:27b')]); // recovered

    expect(useAppStore.getState().selectedModel).toBe('qwen3.5:27b');
    expect(useAppStore.getState().modelWasAutoPicked).toBe(false);
  });
});
