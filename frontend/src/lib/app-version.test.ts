import { describe, expect, it } from 'vitest';

// Read through Vite's JSON import rather than node's createRequire: this is a
// browser-targeted tsconfig with no node types, so createRequire type-checks
// only by accident of a stale incremental build.
import pkg from '../../package.json';

// analytics.ts hardcoded APP_VERSION = '0.1.0' behind a TODO while the app
// shipped as 1.0.x, so every telemetry event was tagged with a version that
// had not existed for a long time and version-filtered analytics were
// meaningless. It now comes from package.json via Vite's define().

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
