import { describe, expect, it } from 'vitest';
import {
  handlesKey,
  nextTabIndex,
  panelProps,
  tabProps,
} from './tablist';

describe('nextTabIndex', () => {
  it('moves forward and back', () => {
    expect(nextTabIndex('ArrowRight', 0, 3)).toBe(1);
    expect(nextTabIndex('ArrowLeft', 1, 3)).toBe(0);
  });

  it('treats up and down like left and right', () => {
    // A vertical tab strip uses the same pattern, and a horizontal one should
    // not simply ignore the keys a person happens to reach for.
    expect(nextTabIndex('ArrowDown', 0, 3)).toBe(1);
    expect(nextTabIndex('ArrowUp', 0, 3)).toBe(2);
  });

  it('wraps at both ends', () => {
    expect(nextTabIndex('ArrowRight', 2, 3)).toBe(0);
    expect(nextTabIndex('ArrowLeft', 0, 3)).toBe(2);
  });

  it('jumps to the ends', () => {
    expect(nextTabIndex('Home', 2, 3)).toBe(0);
    expect(nextTabIndex('End', 0, 3)).toBe(2);
  });

  it('leaves other keys alone', () => {
    // Tab must still leave the strip, and typing must still reach an input.
    for (const key of ['Tab', 'Enter', ' ', 'a', 'Escape', 'PageDown']) {
      expect(nextTabIndex(key, 0, 3), key).toBeNull();
      expect(handlesKey(key), key).toBe(false);
    }
  });

  it('does nothing with no tabs', () => {
    expect(nextTabIndex('ArrowRight', 0, 0)).toBeNull();
  });

  it('stays put in a strip of one', () => {
    expect(nextTabIndex('ArrowRight', 0, 1)).toBe(0);
    expect(nextTabIndex('ArrowLeft', 0, 1)).toBe(0);
  });
});

describe('tabProps', () => {
  it('links a tab to its panel', () => {
    const tab = tabProps('settings', 'general', true);
    const panel = panelProps('settings', 'general');

    expect(tab['aria-controls']).toBe(panel.id);
    expect(panel['aria-labelledby']).toBe(tab.id);
  });

  it('keeps only the selected tab in the tab order', () => {
    // Roving tabindex. Without it, Tab stops at every tab before reaching the
    // content, which on a three-tab page is three extra presses every time.
    expect(tabProps('g', 'a', true).tabIndex).toBe(0);
    expect(tabProps('g', 'b', false).tabIndex).toBe(-1);
  });

  it('reports which tab is showing', () => {
    expect(tabProps('g', 'a', true)['aria-selected']).toBe(true);
    expect(tabProps('g', 'b', false)['aria-selected']).toBe(false);
  });

  it('gives different groups different ids', () => {
    // Two tab strips on one page would otherwise collide, and aria-controls
    // would point at whichever element won the duplicate id.
    expect(tabProps('one', 'a', true).id).not.toBe(tabProps('two', 'a', true).id);
  });
});
