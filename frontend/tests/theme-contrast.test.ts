import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Glass opacity is a legibility budget.
 *
 * Lives in frontend/tests/ rather than src/: it reads index.css off disk, and
 * src/ is inside tsconfig's `include` with no @types/node, so node:fs there
 * fails `tsc --noEmit` even though vitest runs it happily.
 *
 * The text tokens in index.css carry a comment explaining that they are the
 * dimmest values clearing 4.5:1 on every surface they land on — worked out
 * against *solid* backgrounds. Making those surfaces translucent moves the
 * effective background under all of them, and thinning a panel by ten percent
 * to make it look better is a one-character change that silently spends that
 * budget.
 *
 * So this composites the glass over the page background the way the browser
 * does, and checks what is actually behind the text.
 *
 * (index.css also claims a `theme-tokens.test.ts` "fails the build rather
 * than let that ship". No such file exists — this is the nearest thing.)
 */

const CSS = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/index.css'),
  'utf8',
);

type RGB = [number, number, number];

function hexToRgb(hex: string): RGB {
  const h = hex.replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

/** Relative luminance, per WCAG 2.x. */
function luminance([r, g, b]: RGB): number {
  const f = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function contrast(a: RGB, b: RGB): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** `over` composited under `top` at `alpha`, which is what a glass panel does. */
function composite(top: RGB, over: RGB, alpha: number): RGB {
  return top.map((c, i) => Math.round(c * alpha + over[i] * (1 - alpha))) as RGB;
}

/** Pull a `--token: #value;` out of the `:root` or `.dark` block. */
function token(block: string, name: string): string {
  const m = new RegExp(`--${name}:\\s*([^;]+);`).exec(block);
  if (!m) throw new Error(`token --${name} not found`);
  return m[1].trim();
}

function blockFor(theme: 'light' | 'dark'): string {
  const start =
    theme === 'dark' ? CSS.indexOf('.dark {') : CSS.indexOf('  :root {');
  expect(start).toBeGreaterThan(-1);
  return CSS.slice(start, CSS.indexOf('\n  }', start));
}

/** The `NN%` out of `color-mix(in srgb, var(--color-surface) NN%, transparent)`. */
function glassAlpha(block: string, name: string): number {
  const value = token(block, name);
  const m = /(\d+(?:\.\d+)?)%/.exec(value);
  if (!m) throw new Error(`no percentage in --${name}: ${value}`);
  return Number(m[1]) / 100;
}

describe.each(['light', 'dark'] as const)('%s theme', (theme) => {
  const block = blockFor(theme);
  const surface = hexToRgb(token(block, 'color-surface'));
  const pageBg = hexToRgb(token(block, 'color-bg'));

  // The worst case a panel ever sits on, not the average one.
  //
  // Compositing over --color-bg alone is close to meaningless in the dark
  // theme: surface and page are both nearly black, so thinning the glass
  // from 82% to 50% moves the luminance almost not at all and the check
  // passes on glass nobody could read text through. (Confirmed by doing
  // exactly that and watching this file stay green.)
  //
  // What actually sits behind a panel is .hud-backdrop, whose brightest
  // region is a radial bloom of the accent at 10%. That is the background to
  // measure against, because it is the one where the text is dimmest
  // relative to what is behind it.
  const accent = hexToRgb(token(block, 'color-accent'));
  const worstBackdrop = composite(accent, pageBg, 0.1);

  const behindPanel = composite(surface, worstBackdrop, glassAlpha(block, 'glass-bg'));
  const behindChrome = composite(
    surface,
    worstBackdrop,
    glassAlpha(block, 'glass-bg-strong'),
  );

  it.each([
    ['text', 4.5],
    ['text-secondary', 4.5],
    ['text-tertiary', 4.5],
  ])('--color-%s clears AA on a glass panel', (name, min) => {
    const ratio = contrast(hexToRgb(token(block, `color-${name}`)), behindPanel);
    expect(ratio, `${name} on glass = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(min);
  });

  it('the dimmest text clears AA on glass chrome too', () => {
    const ratio = contrast(hexToRgb(token(block, 'color-text-tertiary')), behindChrome);
    expect(ratio, `tertiary on chrome = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
  });

  it('glass is translucent enough to be glass at all', () => {
    // The other direction: fully opaque would pass every contrast check
    // above and would not be a glass theme.
    expect(glassAlpha(block, 'glass-bg')).toBeLessThan(1);
    expect(glassAlpha(block, 'glass-bg')).toBeLessThanOrEqual(
      glassAlpha(block, 'glass-bg-strong'),
    );
  });
});

describe('the glass is actually frosted', () => {
  it('panels and chrome both carry a backdrop filter', () => {
    // Translucency without blur is a washed-out panel, not glass: whatever is
    // behind stays legible and competes with the text in front.
    const panel = CSS.slice(CSS.indexOf('.hud-panel {'), CSS.indexOf('.hud-panel::before'));
    expect(panel).toMatch(/backdrop-filter:\s*blur\(/);
    const chrome = CSS.slice(CSS.indexOf('.glass-chrome {'));
    expect(chrome.slice(0, 400)).toMatch(/backdrop-filter:\s*blur\(/);
  });

  it('ships the -webkit- prefix, which Safari still needs', () => {
    const uses = CSS.match(/backdrop-filter:/g) ?? [];
    const prefixed = CSS.match(/-webkit-backdrop-filter:/g) ?? [];
    expect(prefixed.length).toBe(uses.length - prefixed.length);
  });
});
