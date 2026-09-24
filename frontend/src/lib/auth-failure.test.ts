/**
 * A 401 should say "add your API key", once.
 *
 * Before this, every caller rendered its own fallback for an auth failure —
 * the visible one being "No models available", which reads as a broken
 * install rather than a server asking for a key. And a fresh page load fires
 * about a dozen requests, so naively toasting each one would stack a dozen
 * identical messages.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { apiFetch, onAuthFailure, resetAuthFailureThrottle } from './api';

const originalFetch = globalThis.fetch;

// The suite runs in node, with no DOM. `api.ts` reads the key out of
// localStorage, so the tests need one.
class MemoryStorage {
  private store = new Map<string, string>();
  getItem(k: string): string | null {
    return this.store.has(k) ? (this.store.get(k) as string) : null;
  }
  setItem(k: string, v: string): void {
    this.store.set(k, String(v));
  }
  removeItem(k: string): void {
    this.store.delete(k);
  }
  clear(): void {
    this.store.clear();
  }
}

function respond(status: number): void {
  globalThis.fetch = vi.fn(async () =>
    new Response(JSON.stringify({ detail: 'Missing Authorization header' }), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  ) as unknown as typeof fetch;
}

describe('auth failure notification', () => {
  beforeEach(() => {
    resetAuthFailureThrottle();
    (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
      new MemoryStorage();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage = undefined;
    vi.useRealTimers();
  });

  it('fires on a 401', async () => {
    respond(401);
    const seen: Array<{ status: number; message: string }> = [];
    const off = onAuthFailure((d) => seen.push(d));

    await apiFetch('/v1/models');

    expect(seen).toHaveLength(1);
    expect(seen[0].status).toBe(401);
    off();
  });

  it('fires on a 403 too', async () => {
    respond(403);
    const seen: unknown[] = [];
    const off = onAuthFailure((d) => seen.push(d));
    await apiFetch('/v1/models');
    expect(seen).toHaveLength(1);
    off();
  });

  it('says to add a key when none is set', async () => {
    respond(401);
    let message = '';
    const off = onAuthFailure((d) => { message = d.message; });
    await apiFetch('/v1/models');
    expect(message).toContain('needs an API key');
    expect(message).toContain('Settings');
    off();
  });

  it('says the key was rejected when one is set', async () => {
    localStorage.setItem('nira-settings', JSON.stringify({ apiKey: 'nira_sk_wrong' }));
    respond(401);
    let message = '';
    const off = onAuthFailure((d) => { message = d.message; });
    await apiFetch('/v1/models');
    expect(message).toContain('rejected');
    off();
  });

  it('collapses a burst of failures into one message', async () => {
    respond(401);
    const seen: unknown[] = [];
    const off = onAuthFailure((d) => seen.push(d));

    // What a page load actually does.
    await Promise.all([
      apiFetch('/v1/models'),
      apiFetch('/v1/savings'),
      apiFetch('/v1/telemetry/stats'),
      apiFetch('/v1/memory/stats'),
      apiFetch('/v1/network/config'),
    ]);

    expect(seen).toHaveLength(1);
    off();
  });

  it('speaks again after the window passes, so a retry is not silent', async () => {
    vi.useFakeTimers();
    respond(401);
    const seen: unknown[] = [];
    const off = onAuthFailure((d) => seen.push(d));

    await apiFetch('/v1/models');
    expect(seen).toHaveLength(1);

    vi.advanceTimersByTime(11_000);
    await apiFetch('/v1/models');
    expect(seen).toHaveLength(2);
    off();
  });

  it('stays quiet on a successful request', async () => {
    globalThis.fetch = vi.fn(async () => new Response('{}', { status: 200 })) as never;
    const seen: unknown[] = [];
    const off = onAuthFailure((d) => seen.push(d));
    await apiFetch('/v1/models');
    expect(seen).toHaveLength(0);
    off();
  });

  it('stays quiet on a 500 — that is not an auth problem', async () => {
    respond(500);
    const seen: unknown[] = [];
    const off = onAuthFailure((d) => seen.push(d));
    await apiFetch('/v1/models');
    expect(seen).toHaveLength(0);
    off();
  });

  it('still returns the response to the caller', async () => {
    respond(401);
    const res = await apiFetch('/v1/models');
    expect(res.status).toBe(401);
    expect((await res.json()).detail).toBe('Missing Authorization header');
  });

  it('a throwing listener does not break the response or the others', async () => {
    respond(401);
    const seen: unknown[] = [];
    const offBad = onAuthFailure(() => { throw new Error('listener blew up'); });
    const offGood = onAuthFailure((d) => seen.push(d));

    const res = await apiFetch('/v1/models');

    expect(res.status).toBe(401);
    expect(seen).toHaveLength(1);
    offBad();
    offGood();
  });

  it('unsubscribing stops delivery', async () => {
    respond(401);
    const seen: unknown[] = [];
    const off = onAuthFailure((d) => seen.push(d));
    off();
    await apiFetch('/v1/models');
    expect(seen).toHaveLength(0);
  });
});
