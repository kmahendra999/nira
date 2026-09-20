/**
 * Connecting an agent to messaging channels.
 */

import { useEffect, useState, useCallback } from 'react';
import {
  fetchAgentChannels,
  bindAgentChannel,
  unbindAgentChannel,
} from '../../lib/api';
import type { ChannelBinding } from '../../lib/api';
import { Bot, Copy, Check } from 'lucide-react';
import { SOURCE_CATALOG } from '../../types/connectors';
import type { ConnectRequest } from '../../types/connectors';
import { listConnectors, connectSource } from '../../lib/connectors-api';
import { SendBlueWizard } from '../agents/SendBlueWizard';

interface MessagingChannelConfig {
  type: string;
  name: string;
  icon: string;
  description: string;
  setupSteps: string[];
  fields: ChannelField[];
  activeLabel: (cfg: Record<string, unknown>) => string;
  howToUse: (cfg: Record<string, unknown>) => string;
}

export const MESSAGING_CHANNELS: MessagingChannelConfig[] = [
  // SendBlue (iMessage + SMS) is handled by the dedicated SendBlueWizard above.
  // These are the other supported channels.
  {
    type: 'slack',
    name: 'Slack',
    icon: '#',
    description: 'DM your agent in any Slack workspace',
    setupSteps: [
      '1. Go to api.slack.com/apps → click "Create New App" → choose "From an app manifest"',
      '2. Select your workspace. When asked for the manifest format, choose JSON. Then paste the manifest below (click "Copy" to copy it):',
      'COPYABLE:{"display_information":{"name":"Nira"},"features":{"app_home":{"home_tab_enabled":true,"messages_tab_enabled":true,"messages_tab_read_only_enabled":false},"bot_user":{"display_name":"Nira","always_online":true}},"oauth_config":{"scopes":{"bot":["chat:write","im:write","im:read","im:history","mpim:read","mpim:history","users:read","channels:read","channels:history","channels:join","groups:read","groups:history","app_mentions:read"]}},"settings":{"event_subscriptions":{"bot_events":["message.im"]},"socket_mode_enabled":true}}',
      '3. Click "Next" → review the summary → click "Create". Then go to "Install App" in the left sidebar → click "Install to Workspace" → click "Allow"',
      '4. In the left sidebar, click "OAuth & Permissions". Copy the "Bot User OAuth Token" (starts with xoxb-...)',
      '5. In the left sidebar, click "Basic Information" → scroll to "App-Level Tokens" → click "Generate Token and Scopes" → name it "socket" → click "Add Scope" → select "connections:write" → click "Generate" → copy the token (starts with xapp-...)',
      '6. (Optional) Still in "Basic Information", scroll to "Display Information" → upload the Nira icon as the app icon',
      '7. Paste both tokens below and click Connect',
    ],
    fields: [
      { key: 'bot_token', label: 'Bot Token', placeholder: 'xoxb-...', type: 'password', required: true },
      { key: 'app_token', label: 'App Token', placeholder: 'xapp-...', type: 'password', required: true },
    ],
    activeLabel: () => 'Connected to Slack',
    howToUse: () => 'Open Slack and DM @Nira to talk to your agent.',
  },
];

// ---------------------------------------------------------------------------
// SendBlue webhook step — ngrok tunnel + registration
// ---------------------------------------------------------------------------

interface ChannelField {
  key: string;
  label: string;
  placeholder: string;
  type?: 'text' | 'password';
  required?: boolean;
}

export function InlineConnectForm({
  fields,
  loading,
  onSubmit,
}: {
  fields: Array<{ name: string; placeholder: string; type?: string }>;
  loading: boolean;
  onSubmit: (req: ConnectRequest) => void;
}) {
  const [inputs, setInputs] = useState<Record<string, string>>({});

  const update = (name: string, value: string) =>
    setInputs((p) => ({ ...p, [name]: value }));

  const allFilled = fields.every((f) => inputs[f.name]?.trim());

  const submit = () => {
    const req: ConnectRequest = {};
    for (const f of fields) {
      if (f.name === 'email') req.email = inputs.email;
      else if (f.name === 'password') req.password = inputs.password;
      else if (f.name === 'token') req.token = inputs.token;
      else if (f.name === 'path') req.path = inputs.path;
    }
    if (req.email && req.password) {
      req.token = `${req.email}:${req.password}`;
      req.code = req.token;
    }
    if (req.token && !req.code) req.code = req.token;
    onSubmit(req);
  };

  return (
    <div>
      {fields.map((f) => (
        <input
          key={f.name}
          value={inputs[f.name] || ''}
          onChange={(e) => update(f.name, e.target.value)}
          placeholder={f.placeholder}
          type={f.type || 'text'}
          style={{
            width: '100%', padding: '7px 10px',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 4, color: 'var(--color-text)',
            fontSize: 12, marginBottom: 6,
            boxSizing: 'border-box',
          }}
        />
      ))}
      <button
        onClick={submit}
        disabled={loading || !allFilled}
        style={{
          width: '100%', padding: 8,
          background: loading || !allFilled ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
          color: 'var(--color-on-accent)', border: 'none',
          borderRadius: 6, fontSize: 12, cursor: 'pointer',
        }}
      >
        {loading ? 'Connecting...' : 'Connect'}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Messaging tab component
// ---------------------------------------------------------------------------

export function ChannelsTab({ agentId }: { agentId: string }) {
  const [connectors, setConnectors] = useState<
    Array<{ connector_id: string; display_name: string; connected: boolean; chunks: number }>
  >([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // suppress unused var – agentId reserved for future per-agent source binding
  void agentId;

  const loadConnectors = useCallback(() => {
    listConnectors()
      .then((list) =>
        setConnectors(
          list.map((c) => ({
            connector_id: c.connector_id,
            display_name: c.display_name,
            connected: c.connected,
            chunks: (c as any).chunks || 0,
          })),
        ),
      )
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadConnectors();
    // Poll every 10s to catch background OAuth completions
    const interval = setInterval(loadConnectors, 10000);
    return () => clearInterval(interval);
  }, [loadConnectors]);

  const handleConnect = async (id: string, req: ConnectRequest) => {
    setLoading(true);
    try {
      await connectSource(id, req);
      setExpandedId(null);
      // Poll for connection status (OAuth flow runs in background thread)
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        await loadConnectors();
        // Check if this connector is now connected
        const updated = await listConnectors();
        const target = updated.find((c) => c.connector_id === id);
        if (target?.connected) break;
      }
    } catch {
      // error handling
    } finally {
      setLoading(false);
    }
  };

  const connected = connectors.filter((c) => c.connected);
  const notConnected = connectors.filter((c) => !c.connected);

  // Merge with SOURCE_CATALOG for icons/descriptions
  const getMeta = (id: string) =>
    SOURCE_CATALOG.find((s) => s.connector_id === id);

  const iconMap: Record<string, string> = {
    gmail: '\u2709\uFE0F', gmail_imap: '\u2709\uFE0F', slack: '#',
    imessage: '\uD83D\uDCAC', gdrive: '\uD83D\uDCC1', notion: '\uD83D\uDCC4',
    obsidian: '\uD83D\uDCC1', granola: '\uD83C\uDF99\uFE0F', gcalendar: '\uD83D\uDCC5',
    gcontacts: '\uD83D\uDCC7', outlook: '\u2709\uFE0F', apple_notes: '\uD83C\uDF4E',
    dropbox: '\uD83D\uDCE6', whatsapp: '\uD83D\uDCF1',
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{
        color: 'var(--color-text-secondary)',
        fontSize: 12, marginBottom: 12,
      }}>
        Data sources your agent can search across
      </div>

      {/* Connected sources grid */}
      {connected.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 6, marginBottom: 12,
        }}>
          {connected.map((c) => {
            const meta = SOURCE_CATALOG.find(s => s.connector_id === c.connector_id);
            const unit = meta?.unitLabel || 'items';
            const isReconnecting = expandedId === c.connector_id;
            return (
            <div
              key={c.connector_id}
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
                borderRadius: 6,
                overflow: 'hidden',
                gridColumn: isReconnecting ? '1 / -1' : undefined,
              }}
            >
              <div style={{
                padding: '12px 14px',
                display: 'flex', alignItems: 'center', gap: 8,
              }}>
                <span style={{ fontSize: 20 }}>{iconMap[c.connector_id] || '\uD83D\uDD17'}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>
                    {c.display_name}
                  </div>
                  <div style={{ fontSize: 12, color: c.chunks > 0 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                    {c.chunks > 0
                      ? `${c.chunks.toLocaleString()} ${unit}`
                      : 'Connected — no data synced yet'}
                  </div>
                </div>
                <button
                  onClick={() => setExpandedId(isReconnecting ? null : c.connector_id)}
                  style={{
                    fontSize: 10, padding: '3px 10px',
                    background: 'transparent',
                    color: 'var(--color-text-secondary)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 4, cursor: 'pointer',
                  }}
                >
                  {isReconnecting ? 'Cancel' : 'Reconnect'}
                </button>
              </div>
              {isReconnecting && meta?.steps && (
                <div style={{
                  borderTop: '1px solid var(--color-border)',
                  padding: 12,
                }}>
                  <div style={{
                    fontSize: 12, color: 'var(--color-warning)',
                    marginBottom: 8,
                  }}>
                    Re-enter credentials to reconnect this source.
                  </div>
                  {meta.steps.map((step, i) => (
                    <div
                      key={i}
                      style={{
                        background: 'var(--color-bg)',
                        border: '1px solid var(--color-border)',
                        borderRadius: 6, padding: 10,
                        marginBottom: 8,
                      }}
                    >
                      <div style={{
                        color: 'var(--color-accent-purple)', fontSize: 10,
                        fontWeight: 600, marginBottom: 3,
                      }}>
                        STEP {i + 1}
                      </div>
                      <div style={{ fontSize: 12, marginBottom: step.url ? 4 : 0 }}>
                        {step.label}
                      </div>
                      {step.url && (
                        <a
                          href={step.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                            color: 'var(--color-accent)', fontSize: 11,
                            textDecoration: 'underline',
                          }}
                        >
                          {step.urlLabel || 'Open'} →
                        </a>
                      )}
                    </div>
                  ))}
                  {meta.inputFields && (
                    <InlineConnectForm
                      fields={meta.inputFields}
                      loading={loading}
                      onSubmit={(req) => handleConnect(c.connector_id, req)}
                    />
                  )}
                </div>
              )}
            </div>
            );
          })}
        </div>
      )}

      {/* Not connected grid */}
      {notConnected.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 6,
        }}>
          {notConnected.map((c) => {
            const meta = getMeta(c.connector_id);
            const isExpanded = expandedId === c.connector_id;

            return (
              <div
                key={c.connector_id}
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px dashed var(--color-border)',
                  borderRadius: 6, overflow: 'hidden',
                  opacity: isExpanded ? 1 : 0.6,
                  gridColumn: isExpanded ? '1 / -1' : undefined,
                }}
              >
                {/* A real button, now that this file is small enough to
                    restructure. role="button" was the stand-in while these
                    rows lived in a four-thousand-line page: it announces the
                    same thing, but Enter and Space had to be hand-written. */}
                <button
                  type="button"
                  aria-expanded={isExpanded}
                  style={{
                    padding: '12px 14px', display: 'flex',
                    alignItems: 'center', gap: 8,
                    cursor: 'pointer', width: '100%', textAlign: 'left',
                    background: 'none', border: 'none', font: 'inherit',
                    color: 'inherit',
                  }}
                  onClick={() =>
                    setExpandedId(isExpanded ? null : c.connector_id)
                  }
                >
                  <span style={{ fontSize: 20 }}>{iconMap[c.connector_id] || '\uD83D\uDD17'}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 600,
                      color: 'var(--color-text-secondary)' }}>
                      {c.display_name}
                    </div>
                    <div style={{ fontSize: 12,
                      color: 'var(--color-text-secondary)' }}>
                      Not connected
                    </div>
                  </div>
                  <span style={{
                    color: 'var(--color-accent-purple)', fontSize: 11, fontWeight: 500,
                  }}>
                    {isExpanded ? '\u2715 Close' : '+ Add'}
                  </span>
                </button>

                {/* Inline setup panel */}
                {isExpanded && meta?.steps && (
                  <div style={{
                    borderTop: '1px solid var(--color-border)',
                    padding: 12,
                  }}>
                    {meta.steps.map((step, i) => (
                      <div
                        key={i}
                        style={{
                          background: 'var(--color-bg)',
                          border: '1px solid var(--color-border)',
                          borderRadius: 6, padding: 10,
                          marginBottom: 8,
                        }}
                      >
                        <div style={{
                          color: 'var(--color-accent-purple)', fontSize: 10,
                          fontWeight: 600, marginBottom: 3,
                        }}>
                          STEP {i + 1}
                        </div>
                        <div style={{
                          fontSize: 12, marginBottom: step.url ? 4 : 0,
                        }}>
                          {step.label}
                        </div>
                        {step.url && (
                          <a
                            href={step.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              color: 'var(--color-accent)', fontSize: 11,
                              textDecoration: 'underline',
                            }}
                          >
                            {step.urlLabel || 'Open'} {'\u2192'}
                          </a>
                        )}
                      </div>
                    ))}
                    {meta.inputFields && (
                      <InlineConnectForm
                        fields={meta.inputFields}
                        loading={loading}
                        onSubmit={(req) =>
                          handleConnect(c.connector_id, req)
                        }
                      />
                    )}
                    <div style={{
                      fontSize: 10, color: 'var(--color-text-secondary)',
                      textAlign: 'center', marginTop: 8,
                    }}>
                      {'\uD83D\uDD12'} Read-only access {'\u00B7'} No data leaves your device
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function MessagingTab({ agentId }: { agentId: string }) {
  const [bindings, setBindings] = useState<ChannelBinding[]>([]);
  const [setupType, setSetupType] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const loadBindings = useCallback(() => {
    fetchAgentChannels(agentId).then(setBindings).catch(() => setBindings([]));
  }, [agentId]);

  useEffect(() => { loadBindings(); }, [loadBindings]);

  const setField = (key: string, value: string) => {
    setFormValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSetup = async (ch: MessagingChannelConfig) => {
    // Check required fields
    const missing = ch.fields.filter(
      (f) => f.required && !formValues[f.key]?.trim(),
    );
    if (missing.length > 0) return;

    setLoading(true);
    try {
      const config: Record<string, string> = {};
      for (const f of ch.fields) {
        const v = formValues[f.key]?.trim();
        if (v) config[f.key] = v;
      }
      await bindAgentChannel(agentId, ch.type, config);
      setSetupType(null);
      setFormValues({});
      loadBindings();
    } catch { /* */ } finally { setLoading(false); }
  };

  const handleRemove = async (bindingId: string) => {
    try {
      await unbindAgentChannel(agentId, bindingId);
      loadBindings();
    } catch { /* */ }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '6px 10px',
    background: 'var(--color-bg-secondary)',
    border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)',
    fontSize: 12, boxSizing: 'border-box',
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{
        color: 'var(--color-text-secondary)',
        fontSize: 12, marginBottom: 14,
      }}>
        Connect a messaging channel so you can talk to your agent from your phone or other devices.
      </div>

      {/* SendBlue wizard — primary option */}
      <SendBlueWizard
        agentId={agentId}
        binding={bindings.find((b) => b.channel_type === 'sendblue')}
        onDone={loadBindings}
        onRemove={(id) => { unbindAgentChannel(agentId, id).then(loadBindings).catch(() => {}); }}
      />

      {/* Divider */}
      <div style={{
        fontSize: 10, color: 'var(--color-text-secondary)',
        textTransform: 'uppercase', letterSpacing: 1,
        margin: '14px 0 8px', fontWeight: 600,
      }}>
        Other messaging channels
      </div>

      {MESSAGING_CHANNELS.map((ch) => {
        const binding = bindings.find((b) => b.channel_type === ch.type);
        const cfg = (binding?.config || {}) as Record<string, unknown>;
        const isSetup = setupType === ch.type;

        // Check if required fields are filled
        const canConnect = ch.fields.every(
          (f) => !f.required || formValues[f.key]?.trim(),
        );

        return (
          <div
            key={ch.type}
            style={{
              background: 'var(--color-bg-secondary)',
              border: binding
                ? '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)'
                : '1px dashed var(--color-border)',
              borderRadius: 8, marginBottom: 10,
              overflow: 'hidden',
            }}
          >
            {/* Header row */}
            <div style={{
              display: 'flex', alignItems: 'center',
              padding: '12px 14px',
            }}>
              <span style={{ fontSize: 18, marginRight: 10 }}>{ch.icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{ch.name}</div>
                <div style={{
                  fontSize: 11,
                  color: binding ? 'var(--color-success)' : 'var(--color-text-secondary)',
                }}>
                  {binding ? ch.activeLabel(cfg) : ch.description}
                </div>
              </div>
              {binding ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    background: 'color-mix(in srgb, var(--color-success) 22%, transparent)', color: 'var(--color-success)',
                    padding: '2px 8px', borderRadius: 10,
                    fontSize: 10, fontWeight: 600,
                  }}>Active</span>
                  <button
                    onClick={() => handleRemove(binding.id)}
                    style={{
                      fontSize: 10, padding: '2px 8px',
                      background: 'transparent',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 4, cursor: 'pointer',
                    }}
                  >Remove</button>
                </div>
              ) : (
                <button
                  onClick={() => {
                    setSetupType(isSetup ? null : ch.type);
                    setFormValues({});
                  }}
                  style={{
                    fontSize: 10, padding: '3px 12px',
                    background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                    border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                  }}
                >
                  {isSetup ? 'Cancel' : 'Set Up'}
                </button>
              )}
            </div>

            {/* Active state: how to use */}
            {binding && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '10px 14px',
                background: 'var(--color-bg)',
              }}>
                <div style={{
                  fontSize: 11, color: 'var(--color-text-secondary)',
                  display: 'flex', alignItems: 'flex-start', gap: 6,
                }}>
                  <span style={{ flexShrink: 0 }}>{'\u2192'}</span>
                  <span>{ch.howToUse(cfg)}</span>
                </div>
              </div>
            )}

            {/* Setup form */}
            {isSetup && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '14px',
                background: 'var(--color-bg)',
              }}>
                {/* Setup instructions */}
                <div style={{
                  fontSize: 11, lineHeight: 1.5,
                  color: 'var(--color-text-secondary)',
                  marginBottom: 12,
                  padding: '8px 10px',
                  background: 'var(--color-bg-secondary)',
                  borderRadius: 6,
                  borderLeft: '3px solid var(--color-accent, var(--color-accent-purple))',
                }}>
                  {ch.setupSteps.map((step, i) => {
                    if (step.startsWith('COPYABLE:')) {
                      const text = step.slice(9);
                      return (
                        <div key={i} style={{ marginBottom: 6, marginTop: 4 }}>
                          <div style={{
                            position: 'relative',
                            background: 'var(--color-bg)',
                            border: '1px solid var(--color-border)',
                            borderRadius: 4, padding: '8px 10px',
                            fontSize: 10, fontFamily: 'monospace',
                            wordBreak: 'break-all', lineHeight: 1.4,
                            maxHeight: 80, overflowY: 'auto',
                          }}>
                            {text}
                            <button
                              onClick={() => { navigator.clipboard.writeText(text); }}
                              style={{
                                position: 'sticky', float: 'right', top: 0,
                                fontSize: 10, padding: '2px 8px',
                                background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                                border: 'none', borderRadius: 3,
                                cursor: 'pointer', fontWeight: 600,
                              }}
                            >Copy</button>
                          </div>
                        </div>
                      );
                    }
                    return (
                      <div key={i} style={{ marginBottom: i < ch.setupSteps.length - 1 ? 4 : 0 }}>
                        {step}
                      </div>
                    );
                  })}
                </div>

                {/* Form fields */}
                {ch.fields.map((field) => (
                  <div key={field.key} style={{ marginBottom: 8 }}>
                    <label style={{
                      display: 'block', fontSize: 11,
                      color: 'var(--color-text-secondary)',
                      marginBottom: 3, fontWeight: 500,
                    }}>
                      {field.label}{field.required ? ' *' : ''}
                    </label>
                    <input
                      type={field.type || 'text'}
                      value={formValues[field.key] || ''}
                      onChange={(e) => setField(field.key, e.target.value)}
                      placeholder={field.placeholder}
                      style={inputStyle}
                    />
                  </div>
                ))}

                {/* Connect button */}
                <button
                  onClick={() => handleSetup(ch)}
                  disabled={loading || !canConnect}
                  style={{
                    fontSize: 12, padding: '7px 20px',
                    background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                    border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                    opacity: loading || !canConnect ? 0.5 : 1,
                    marginTop: 4,
                  }}
                >
                  {loading ? 'Connecting...' : 'Connect'}
                </button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Learning tab component
// ---------------------------------------------------------------------------

