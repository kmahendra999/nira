import { describe, expect, it } from 'vitest';
import {
  formatCost,
  formatRelativeTime,
  formatSchedule,
  statusColor,
} from './agent-format';

/**
 * These lived among four thousand lines of JSX in AgentsPage, where nothing
 * could reach them. They are the most branch-dense code in that file: a cron
 * expression rendered as "Daily at 9:00 AM" is obviously right until the hour
 * is midnight.
 */

describe('formatSchedule', () => {
  it('describes a daily cron in words', () => {
    expect(formatSchedule('cron', '0 9 * * *')).toBe('Daily at 9:00 AM');
  });

  it('gets midnight and noon right', () => {
    // The two hours a 12-hour clock gets wrong when you convert by
    // subtracting 12 and hoping.
    expect(formatSchedule('cron', '0 0 * * *')).toBe('Daily at 12:00 AM');
    expect(formatSchedule('cron', '0 12 * * *')).toBe('Daily at 12:00 PM');
  });

  it('converts afternoon hours', () => {
    expect(formatSchedule('cron', '0 13 * * *')).toBe('Daily at 1:00 PM');
    expect(formatSchedule('cron', '0 23 * * *')).toBe('Daily at 11:00 PM');
  });

  it('names the days of a weekly schedule', () => {
    expect(formatSchedule('cron', '0 9 * * 1,3,5')).toBe(
      'Weekly on Mon, Wed, Fri at 9:00 AM',
    );
  });

  it('falls back to the raw expression it cannot phrase', () => {
    // Better to show the cron than to describe it wrongly.
    expect(formatSchedule('cron', '*/15 * * * *')).toBe('Cron: */15 * * * *');
    expect(formatSchedule('cron', '30 9 1 * *')).toBe('Cron: 30 9 1 * *');
  });

  it('handles a cron with no expression', () => {
    expect(formatSchedule('cron')).toBe('Cron');
  });

  it('spells out an interval in hours, minutes and seconds', () => {
    expect(formatSchedule('interval', '3600')).toBe('Every 1h');
    expect(formatSchedule('interval', '5400')).toBe('Every 1h 30m');
    expect(formatSchedule('interval', '90')).toBe('Every 1m 30s');
    expect(formatSchedule('interval', '45')).toBe('Every 45s');
  });

  it('omits the units that are zero', () => {
    // "Every 2h 0m 0s" is noise; "Every 2h" is the same fact.
    expect(formatSchedule('interval', '7200')).toBe('Every 2h');
  });

  it('survives an interval that is not a number', () => {
    expect(formatSchedule('interval', 'soon')).toBe('Every soon');
  });

  it('calls a missing or manual schedule manual', () => {
    expect(formatSchedule()).toBe('Manual');
    expect(formatSchedule('manual')).toBe('Manual');
  });

  it('passes an unknown type through rather than inventing one', () => {
    expect(formatSchedule('webhook')).toBe('webhook');
  });
});

describe('formatRelativeTime', () => {
  const now = Date.now() / 1000;

  it('says never when there is no timestamp', () => {
    // Distinct from "just now": one means it has not run, the other that it
    // just did, and they are one falsy check apart.
    expect(formatRelativeTime()).toBe('Never');
    expect(formatRelativeTime(null)).toBe('Never');
    expect(formatRelativeTime(0)).toBe('Never');
  });

  it('counts in minutes, then hours, then days', () => {
    expect(formatRelativeTime(now - 30)).toBe('Just now');
    expect(formatRelativeTime(now - 300)).toBe('5m ago');
    expect(formatRelativeTime(now - 7200)).toBe('2h ago');
    expect(formatRelativeTime(now - 172800)).toBe('2d ago');
  });

  it('changes unit at the boundary rather than one past it', () => {
    expect(formatRelativeTime(now - 3600)).toBe('1h ago');
    expect(formatRelativeTime(now - 86400)).toBe('1d ago');
  });
});

describe('formatCost', () => {
  it('shows four decimal places', () => {
    // Agent runs cost fractions of a cent; two decimals renders most of them
    // as $0.00, which reads as free.
    expect(formatCost(0.0001)).toBe('$0.0001');
    expect(formatCost(1.5)).toBe('$1.5000');
  });

  it('distinguishes unknown from zero', () => {
    expect(formatCost()).toBe('—');
    expect(formatCost(undefined)).toBe('—');
    expect(formatCost(0)).toBe('$0.0000');
  });
});

describe('statusColor', () => {
  it('gives each state its own colour', () => {
    expect(statusColor('running')).toBe('var(--color-accent)');
    expect(statusColor('error')).toBe('var(--color-error)');
    expect(statusColor('idle')).toBe('var(--color-success)');
  });

  it('falls back rather than returning undefined', () => {
    // An undefined colour lands in a style attribute and the dot vanishes.
    expect(statusColor('something-new')).toBe('var(--color-text-tertiary)');
    expect(statusColor('')).toBe('var(--color-text-tertiary)');
  });
});
