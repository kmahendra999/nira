/**
 * Keyboard navigation for a set of tabs.
 *
 * Tabs rendered as plain buttons are announced as plain buttons: nothing says
 * they belong to a group, nothing says which one is showing, and moving
 * between them takes one Tab press each — so reaching the page's content means
 * tabbing through every tab first. The ARIA tabs pattern fixes all three, and
 * arrow-key movement is the half that has to live in JavaScript.
 */

/** Keys this pattern claims. Anything else is left to the browser. */
const HANDLED = new Set([
  'ArrowLeft',
  'ArrowRight',
  'ArrowUp',
  'ArrowDown',
  'Home',
  'End',
]);

export function handlesKey(key: string): boolean {
  return HANDLED.has(key);
}

/**
 * The tab a key press should move to, or `null` to leave focus alone.
 *
 * Wraps at both ends, which is what the ARIA authoring practices specify and
 * what makes a short tab strip quick to cycle.
 */
export function nextTabIndex(
  key: string,
  current: number,
  count: number,
): number | null {
  if (count <= 0 || !handlesKey(key)) return null;

  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return (current + 1) % count;
    case 'ArrowLeft':
    case 'ArrowUp':
      return (current - 1 + count) % count;
    case 'Home':
      return 0;
    case 'End':
      return count - 1;
    default:
      return null;
  }
}

/** Stable ids so a tab and its panel can point at each other. */
export function tabIds(group: string, id: string) {
  return { tab: `${group}-tab-${id}`, panel: `${group}-panel-${id}` };
}

/**
 * The attributes a tab button needs.
 *
 * `tabIndex` is the roving part: only the selected tab is in the tab order, so
 * Tab enters the strip once and moves on to the content, rather than stopping
 * at every tab on the way.
 */
export function tabProps(group: string, id: string, selected: boolean) {
  const ids = tabIds(group, id);
  return {
    id: ids.tab,
    role: 'tab' as const,
    'aria-selected': selected,
    'aria-controls': ids.panel,
    tabIndex: selected ? 0 : -1,
  };
}

/** The attributes the panel needs to be found from its tab. */
export function panelProps(group: string, id: string) {
  const ids = tabIds(group, id);
  return {
    id: ids.panel,
    role: 'tabpanel' as const,
    'aria-labelledby': ids.tab,
    // Focusable so that a screen reader user moving from the tab lands on the
    // content, rather than being dropped at the top of the document.
    tabIndex: 0,
  };
}
