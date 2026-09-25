/**
 * Nothing may call the local server without going through apiFetch.
 *
 * `apiFetch` exists precisely to guarantee the Authorization header is
 * attached, and its own comment says so — the bug it was written for (#266)
 * was direct `fetch()` calls omitting the header and 401ing. It then happened
 * again anyway, in six more places, because nothing enforced it:
 *
 *   SystemPanel      /v1/telemetry/energy + /stats — polled every 3s, so the
 *                    panel rendered 0.0 W, 0.0 kJ, 0 requests, 0 tokens. Every
 *                    number on screen was a failed request wearing a plausible
 *                    value.
 *   TraceDebugger    /v1/traces — and it built its base from VITE_API_URL
 *                    alone, so in the desktop app it pointed at the wrong
 *                    origin entirely.
 *   InputArea        /api/digest
 *   analytics        /v1/analytics/identity
 *   UploadForm       /v1/connectors/upload/ingest (both forms)
 *
 * A grep test is blunt, but it is the only thing that actually holds this
 * line: every one of those call sites looked completely reasonable on its own.
 */

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const SRC = new URL('../src', import.meta.url).pathname;

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.(ts|tsx)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

// Call sites allowed to use a bare fetch, with the reason each is safe.
const ALLOWED: Array<{ file: string; reason: RegExp }> = [
  // apiFetch itself is the one place the real fetch is called.
  { file: 'lib/api.ts', reason: /.*/ },
  // sse.ts streams, so it cannot use apiFetch's Response-returning shape —
  // it attaches authHeaders() by hand instead, which the test below checks.
  { file: 'lib/sse.ts', reason: /.*/ },
];

/** Bare `fetch(...)` whose URL is built from our own server's base. */
const SERVER_FETCH =
  /(?<!api)(?<!\w)fetch\(\s*`\$\{(?:base|getBase\(\)|apiBase)\}/;

describe('every call to the local server carries auth', () => {
  const files = walk(SRC);

  it('finds source files to check', () => {
    expect(files.length).toBeGreaterThan(20);
  });

  it('no component builds its own server URL and calls fetch directly', () => {
    const offenders: string[] = [];

    for (const file of files) {
      const rel = relative(SRC, file);
      if (ALLOWED.some((a) => rel === a.file)) continue;

      const text = readFileSync(file, 'utf8');
      text.split('\n').forEach((line, i) => {
        if (line.trimStart().startsWith('//') || line.trimStart().startsWith('*')) return;
        if (SERVER_FETCH.test(line)) {
          offenders.push(`${rel}:${i + 1}  ${line.trim()}`);
        }
      });
    }

    expect(
      offenders,
      'Use apiFetch (or authHeaders for a streaming call). A bare fetch to ' +
        'our own server sends no Authorization header and 401s on any ' +
        'install with an API key — silently, as an empty result.',
    ).toEqual([]);
  });

  it('sse.ts attaches authHeaders on both of its streaming calls', () => {
    // It is on the allow-list because it cannot use apiFetch; that exemption
    // is only safe while it keeps doing this itself.
    const text = readFileSync(join(SRC, 'lib/sse.ts'), 'utf8');
    const fetches = (text.match(/await fetch\(/g) || []).length;
    const authed = (text.match(/authHeaders\(/g) || []).length;
    expect(authed).toBeGreaterThanOrEqual(fetches);
  });

  it('apiFetch still attaches the header it exists to attach', () => {
    const text = readFileSync(join(SRC, 'lib/api.ts'), 'utf8');
    expect(text).toMatch(/export const apiFetch[\s\S]{0,400}authHeaders\(/);
  });
});
