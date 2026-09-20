import { describe, expect, it } from 'vitest';

import { parseDeepLink } from './deep-link';

// The backend hands these links to users: channel_agent.py answers a long
// research query over Telegram/iMessage/Slack with
// "Full report ready — open in Nira: nira://research/<session_id>".
//
// The scheme was registered with the OS in tauri.conf.json, but
// tauri-plugin-deep-link was in neither Cargo.toml nor package.json and this
// parser had no callers, so clicking one of those links opened an app that
// ignored it. The plugin is now installed and useDeepLink routes the result;
// these cover the parsing contract that sits between them.

describe('parseDeepLink', () => {
  it('parses the research links the backend sends over channels', () => {
    expect(parseDeepLink('nira://research/abc123')).toEqual({
      type: 'research',
      id: 'abc123',
    });
  });

  it('parses connector links', () => {
    expect(parseDeepLink('nira://connector/gmail')).toEqual({
      type: 'connector',
      id: 'gmail',
    });
  });

  it('keeps ids that contain a UUID', () => {
    const id = '3f6b1c2e-9a4d-4f7b-8e2a-1d5c7b9e0a11';
    expect(parseDeepLink(`nira://research/${id}`)).toEqual({
      type: 'research',
      id,
    });
  });

  it('rejects other schemes', () => {
    expect(parseDeepLink('https://example.com/research/abc')).toBeNull();
    expect(parseDeepLink('openjarvis://research/abc')).toBeNull();
  });

  it('rejects a scheme with no resource id', () => {
    expect(parseDeepLink('nira://research')).toBeNull();
  });

  it('returns null rather than throwing on junk', () => {
    expect(parseDeepLink('not a url at all')).toBeNull();
    expect(parseDeepLink('')).toBeNull();
  });
});
