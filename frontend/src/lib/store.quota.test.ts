/**
 * Running out of localStorage must not lose the conversation silently.
 *
 * `saveConversations` wrote with no try/catch, and it is called on every
 * stream flush through `updateLastAssistant`. On QuotaExceededError the throw
 * escaped the store, escaped the component, and landed in the stream loop —
 * which swallows it. What the user saw was a reply that stopped mid-sentence
 * and a message that was never saved, with nothing anywhere mentioning
 * storage. The same was true of every settings and preference write, which
 * share the quota: once conversations filled it, saving an API key threw too.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { StorageWarning } from './store';

/** localStorage that refuses writes past a byte budget, like the real one. */
class BudgetStorage {
  private store = new Map<string, string>();
  constructor(private budget = Infinity) {}

  getItem(k: string): string | null {
    return this.store.has(k) ? (this.store.get(k) as string) : null;
  }

  setItem(k: string, v: string): void {
    let total = String(v).length;
    for (const [key, val] of this.store) if (key !== k) total += val.length;
    if (total > this.budget) {
      // What Chrome and WebKit actually throw.
      const err = new Error('QuotaExceededError') as Error & { code: number };
      err.name = 'QuotaExceededError';
      err.code = 22;
      throw err;
    }
    this.store.set(k, String(v));
  }

  removeItem(k: string): void {
    this.store.delete(k);
  }

  clear(): void {
    this.store.clear();
  }

  setBudget(bytes: number): void {
    this.budget = bytes;
  }
}

let storage: BudgetStorage;

function install(budget = Infinity): void {
  storage = new BudgetStorage(budget);
  (globalThis as unknown as { localStorage: BudgetStorage }).localStorage = storage;
}

beforeEach(() => {
  vi.resetModules();
  install();
});

afterEach(() => {
  (globalThis as unknown as { localStorage?: BudgetStorage }).localStorage = undefined;
});

/** A well-formed ChatMessage; the store's type requires id and timestamp. */
function msg(content: string) {
  return { id: `m-${content.length}-${content.slice(0, 4)}`, role: 'user' as const, content, timestamp: 1 };
}

/** Build a conversation whose messages are `size` bytes of content. */
function bigConversation(id: string, size: number, updatedAt: number) {
  return {
    id,
    title: id,
    updatedAt,
    createdAt: updatedAt,
    model: 'qwen3.5:4b',
    messages: [msg('x'.repeat(size))],
  };
}

describe('conversation writes when storage is full', () => {
  it('drops the oldest conversation to make room, and says so', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const warnings: StorageWarning[] = [];
    const off = onStorageWarning((w) => warnings.push(w));

    // Seed three, oldest first, then shrink the budget so one must go.
    const store = {
      version: 1 as const,
      activeId: 'new',
      conversations: {
        old: bigConversation('old', 400, 1),
        mid: bigConversation('mid', 400, 2),
        new: bigConversation('new', 400, 3),
      },
    };
    storage.setItem('nira-conversations', JSON.stringify(store));
    useAppStore.getState().loadConversations();

    storage.setBudget(1100); // room for roughly two of them

    useAppStore.getState().addMessage('new', msg('hello'));

    const saved = JSON.parse(storage.getItem('nira-conversations') as string);
    expect(saved.conversations.new, 'the active conversation must survive').toBeTruthy();
    expect(saved.conversations.old, 'the oldest goes first').toBeUndefined();
    expect(warnings.some((w) => w.kind === 'pruned')).toBe(true);
    off();
  });

  it('never drops the conversation being written to', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const off = onStorageWarning(() => {});

    const store = {
      version: 1 as const,
      activeId: 'active',
      conversations: {
        active: bigConversation('active', 300, 9), // newest AND active
        older: bigConversation('older', 300, 1),
      },
    };
    storage.setItem('nira-conversations', JSON.stringify(store));
    useAppStore.getState().loadConversations();
    storage.setBudget(700);

    useAppStore.getState().addMessage('active', msg('hi'));

    const saved = JSON.parse(storage.getItem('nira-conversations') as string);
    expect(saved.conversations.active).toBeTruthy();
    off();
  });

  it('reports "full" rather than throwing when even one conversation will not fit', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const warnings: StorageWarning[] = [];
    const off = onStorageWarning((w) => warnings.push(w));

    const store = {
      version: 1 as const,
      activeId: 'only',
      conversations: { only: bigConversation('only', 5000, 1) },
    };
    storage.setItem('nira-conversations', JSON.stringify(store));
    useAppStore.getState().loadConversations();
    storage.setBudget(50);

    expect(() =>
      useAppStore.getState().addMessage('only', msg('hi')),
    ).not.toThrow();
    expect(warnings.some((w) => w.kind === 'full')).toBe(true);
    off();
  });

  it('keeps the message on screen even when it cannot be saved', async () => {
    // The reply is what the user is reading. Losing it because the disk is
    // full would be strictly worse than a stale file.
    const { useAppStore, onStorageWarning } = await import('./store');
    const off = onStorageWarning(() => {});

    const id = useAppStore.getState().createConversation('qwen3.5:4b');
    storage.setBudget(10);

    useAppStore.getState().addMessage(id, msg('still here?'));

    expect(useAppStore.getState().messages[useAppStore.getState().messages.length - 1]?.content).toBe('still here?');
    off();
  });

  it('a non-quota storage failure is reported as unavailable, not pruned', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const warnings: StorageWarning[] = [];
    const off = onStorageWarning((w) => warnings.push(w));

    const id = useAppStore.getState().createConversation('qwen3.5:4b');
    storage.setItem = () => {
      throw new Error('The operation is insecure.'); // private browsing
    };

    expect(() =>
      useAppStore.getState().addMessage(id, msg('x')),
    ).not.toThrow();
    expect(warnings.some((w) => w.kind === 'unavailable')).toBe(true);
    expect(warnings.some((w) => w.kind === 'pruned')).toBe(false);
    off();
  });
});

describe('settings and preferences share the same quota', () => {
  it('saving settings does not throw when storage is full', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const warnings: StorageWarning[] = [];
    const off = onStorageWarning((w) => warnings.push(w));

    storage.setBudget(1);

    // The worst moment for this to throw: the user pasting an API key to fix
    // a 401.
    expect(() =>
      useAppStore.getState().updateSettings({ apiKey: 'nira_sk_typed' }),
    ).not.toThrow();
    expect(useAppStore.getState().settings.apiKey).toBe('nira_sk_typed');
    expect(warnings.length).toBeGreaterThan(0);
    off();
  });

  it('the opt-in choice is kept for the session even if it cannot be stored', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const off = onStorageWarning(() => {});
    storage.setBudget(1);

    expect(() =>
      useAppStore.getState().setOptIn(true, 'Someone', 'a@b.test'),
    ).not.toThrow();
    expect(useAppStore.getState().optInEnabled).toBe(true);
    expect(useAppStore.getState().optInDisplayName).toBe('Someone');
    off();
  });
});

describe('the warning channel itself', () => {
  it('a throwing listener neither breaks the write nor the other listeners', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const seen: StorageWarning[] = [];
    const offBad = onStorageWarning(() => {
      throw new Error('listener blew up');
    });
    const offGood = onStorageWarning((w) => seen.push(w));

    const id = useAppStore.getState().createConversation('qwen3.5:4b');
    storage.setBudget(5);

    expect(() =>
      useAppStore.getState().addMessage(id, msg('x')),
    ).not.toThrow();
    expect(seen.length).toBeGreaterThan(0);
    offBad();
    offGood();
  });

  it('unsubscribing stops delivery', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const seen: StorageWarning[] = [];
    const off = onStorageWarning((w) => seen.push(w));
    off();

    const id = useAppStore.getState().createConversation('qwen3.5:4b');
    storage.setBudget(5);
    useAppStore.getState().addMessage(id, msg('x'));

    expect(seen).toHaveLength(0);
  });
});

describe('reclaiming room prefers trimming attachments to deleting conversations', () => {
  // A single tool-call result can dwarf an entire conversation's text, so the
  // bytes are almost always in the attachments. Deleting whole conversations
  // to reclaim them throws away the words too — and the words are what people
  // came back for.
  function withAttachment(id: string, updatedAt: number) {
    return {
      id,
      title: id,
      updatedAt,
      createdAt: updatedAt,
      model: 'qwen3.5:4b',
      messages: [
        {
          id: `${id}-m`,
          role: 'assistant' as const,
          content: 'the words',
          timestamp: updatedAt,
          toolCalls: [
            { id: 't', name: 'search', arguments: '{}', result: 'R'.repeat(600) },
          ],
        },
      ],
    };
  }

  it('strips attachments from the oldest first, keeping the messages', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const warnings: StorageWarning[] = [];
    const off = onStorageWarning((w) => warnings.push(w));

    const store = {
      version: 1 as const,
      activeId: 'active',
      conversations: {
        old: withAttachment('old', 1),
        active: withAttachment('active', 9),
      },
    };
    storage.setItem('nira-conversations', JSON.stringify(store));
    useAppStore.getState().loadConversations();
    // Measured: 1733 bytes intact, 1117 once the older attachment is
    // stripped, 952 if the whole conversation is deleted. 1200 admits the
    // trimmed form and rejects the intact one, so trimming must suffice.
    storage.setBudget(1200);

    useAppStore.getState().addMessage('active', msg('hi'));

    const saved = JSON.parse(storage.getItem('nira-conversations') as string);
    expect(saved.conversations.old, 'the conversation survives').toBeTruthy();
    expect(saved.conversations.old.messages[0].content).toBe('the words');
    expect(saved.conversations.old.messages[0].toolCalls).toBeUndefined();
    expect(warnings.some((w) => w.kind === 'trimmed')).toBe(true);
    expect(warnings.some((w) => w.kind === 'pruned')).toBe(false);
    off();
  });

  it('falls through to deleting when trimming is not enough', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const warnings: StorageWarning[] = [];
    const off = onStorageWarning((w) => warnings.push(w));

    const store = {
      version: 1 as const,
      activeId: 'active',
      conversations: {
        old: bigConversation('old', 900, 1), // plain text, nothing to trim
        active: bigConversation('active', 200, 9),
      },
    };
    storage.setItem('nira-conversations', JSON.stringify(store));
    useAppStore.getState().loadConversations();
    storage.setBudget(600);

    useAppStore.getState().addMessage('active', msg('hi'));

    const saved = JSON.parse(storage.getItem('nira-conversations') as string);
    expect(saved.conversations.old).toBeUndefined();
    expect(saved.conversations.active).toBeTruthy();
    expect(warnings.some((w) => w.kind === 'pruned')).toBe(true);
    off();
  });

  it('never reclaims the conversation being written, even when it is not the active one', async () => {
    // importOverlayConversation writes a conversation that is not activeId.
    // Protecting only activeId would let the reclaim delete the very thing
    // the write is about.
    const { useAppStore, onStorageWarning } = await import('./store');
    const off = onStorageWarning(() => {});

    const store = {
      version: 1 as const,
      activeId: 'elsewhere',
      conversations: {
        elsewhere: bigConversation('elsewhere', 200, 5),
        target: bigConversation('target', 700, 1), // oldest → first to go
      },
    };
    storage.setItem('nira-conversations', JSON.stringify(store));
    useAppStore.getState().loadConversations();
    storage.setBudget(500);

    useAppStore.getState().addMessage('target', msg('appended'));

    const saved = JSON.parse(storage.getItem('nira-conversations') as string);
    expect(
      saved.conversations.target,
      'the conversation the message was appended to must survive',
    ).toBeTruthy();
    off();
  });
});

describe('the sidebar does not keep listing conversations that were reclaimed', () => {
  it('rebuilds the list when a reclaim removes one', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const off = onStorageWarning(() => {});

    const store = {
      version: 1 as const,
      activeId: 'active',
      conversations: {
        gone: bigConversation('gone', 900, 1),
        active: bigConversation('active', 200, 9),
      },
    };
    storage.setItem('nira-conversations', JSON.stringify(store));
    useAppStore.getState().loadConversations();
    expect(useAppStore.getState().conversations).toHaveLength(2);

    storage.setBudget(600);
    useAppStore.getState().addMessage('active', msg('hi'));

    const listed = useAppStore.getState().conversations.map((c) => c.id);
    expect(listed, 'a reclaimed conversation must leave the sidebar').not.toContain('gone');
    off();
  });

  it('selecting a stale entry repairs the list instead of showing a blank chat', async () => {
    const { useAppStore, onStorageWarning } = await import('./store');
    const off = onStorageWarning(() => {});

    const store = {
      version: 1 as const,
      activeId: 'a',
      conversations: { a: bigConversation('a', 50, 1) },
    };
    storage.setItem('nira-conversations', JSON.stringify(store));
    useAppStore.getState().loadConversations();

    // Something removed it behind the app's back.
    useAppStore.setState({
      conversations: [bigConversation('ghost', 10, 2), ...useAppStore.getState().conversations],
    });
    expect(useAppStore.getState().conversations.map((c) => c.id)).toContain('ghost');

    useAppStore.getState().selectConversation('ghost');

    expect(
      useAppStore.getState().conversations.map((c) => c.id),
      'the click should have repaired the list',
    ).not.toContain('ghost');
    off();
  });
});
