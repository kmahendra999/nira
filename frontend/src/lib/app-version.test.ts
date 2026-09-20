import { createRequire } from 'module';

import { describe, expect, it } from 'vitest';

// analytics.ts hardcoded APP_VERSION = '0.1.0' behind a TODO while the app
// shipped as 1.0.x, so every telemetry event was tagged with a version that
// had not existed for a long time and version-filtered analytics were
// meaningless. It now comes from package.json via Vite's define().

const pkg = createRequire(import.meta.url)('../../package.json') as {
  version: string;
};

describe('__APP_VERSION__', () => {
  it('is injected by the build', () => {
    expect(typeof __APP_VERSION__).toBe('string');
    expect(__APP_VERSION__).not.toBe('');
  });

  it('matches package.json', () => {
    expect(__APP_VERSION__).toBe(pkg.version);
  });

  it('is not the stale hardcoded value', () => {
    expect(__APP_VERSION__).not.toBe('0.1.0');
  });
});
