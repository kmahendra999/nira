import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

// In tests/ rather than src/: it reads the tree off disk, and src/ is inside
// tsconfig's include with no @types/node.

describe('the UI does not hardcode a version', () => {
  it('no component ships a literal vN.N badge', () => {
    // `analytics.ts` had this bug and it was fixed; GetStartedPage had the
    // same literal twice, reading "v2.8" while the app shipped as 1.0.1. A
    // version string is only ever right by accident when it is typed by hand.
    const root = path.resolve(import.meta.dirname, '../src');

    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (/\.tsx?$/.test(entry.name) && !entry.name.includes('.test.')) {
          const text = fs.readFileSync(full, 'utf8');
          // A bare `vN.N` in rendered text, not in a URL or an import.
          for (const m of text.matchAll(/^\s*v\d+\.\d+(\.\d+)?\s*$/gm)) {
            offenders.push(`${path.relative(root, full)}: ${m[0].trim()}`);
          }
        }
      }
    };
    walk(root);

    expect(offenders).toEqual([]);
  });
});
