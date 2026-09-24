import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// "Always allow" existed on both sides and was reachable from neither.
//
// `ApprovalStore` has held `always_approve` since the permission memory
// existed, and the bridge honours it — a remembered hit short-circuits before
// anyone is asked. No client could set it, so the only route to the feature
// was editing the database by hand. These cover the client half: the request
// body actually carries the choice.

const fetchMock = vi.fn<typeof fetch>();

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

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv('VITE_SUPABASE_ANON_KEY', 'test-anon-key');
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ status: 'approved' }), { status: 200 }),
  );
  globalThis.fetch = fetchMock;
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage =
    new MemoryStorage();
});

afterEach(() => {
  vi.unstubAllEnvs();
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage = undefined;
});

async function freshApi() {
  return await import('./api');
}

// `.at` is outside this project's TS lib target, so index the old way.
function lastCall(): [string, RequestInit] {
  const calls = fetchMock.mock.calls;
  return calls[calls.length - 1] as unknown as [string, RequestInit];
}

function lastBody(): unknown {
  return JSON.parse(String(lastCall()[1]?.body ?? '{}'));
}

describe('approveAction', () => {
  it('defaults to answering only this once', async () => {
    const { approveAction } = await freshApi();
    await approveAction('act_1');

    // A standing decision must be asked for, never the default.
    expect(lastBody()).toEqual({ remember: false });
  });

  it('sends remember when the reader chose it', async () => {
    const { approveAction } = await freshApi();
    await approveAction('act_1', true);

    expect(lastBody()).toEqual({ remember: true });
  });

  it('posts to the action it was given', async () => {
    const { approveAction } = await freshApi();
    await approveAction('act_42', true);

    const [url, init] = lastCall();
    expect(String(url)).toContain('/v1/approvals/act_42/approve');
    expect(init.method).toBe('POST');
  });

  it('throws on a failed response', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 500 }));
    const { approveAction } = await freshApi();

    await expect(approveAction('act_1')).rejects.toThrow();
  });
});

describe('denyAction', () => {
  it('can record a standing no', async () => {
    const { denyAction } = await freshApi();
    await denyAction('act_1', true);

    const [url] = lastCall();
    expect(String(url)).toContain('/deny');
    expect(lastBody()).toEqual({ remember: true });
  });

  it('defaults to this once', async () => {
    const { denyAction } = await freshApi();
    await denyAction('act_1');

    expect(lastBody()).toEqual({ remember: false });
  });
});
