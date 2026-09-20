/**
 * Connecting messaging channels, and the SendBlue number setup.
 */

import { useEffect, useState, useCallback } from 'react';
import {
  fetchAgentChannels,
  bindAgentChannel,
  unbindAgentChannel,
  sendblueRegisterWebhook,
  sendblueHealth,
} from '../../lib/api';
import type { ChannelBinding } from '../../lib/api';

export interface MessagingChannelConfig {
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
  {
    type: 'slack',
    name: 'Slack',
    icon: '#',
    description: 'DM your agent in any Slack workspace',
    setupSteps: [
      '1. Go to api.slack.com/apps \u2192 click "Create New App" \u2192 choose "From an app manifest"',
      '2. Select your workspace. When asked for the manifest format, choose JSON. Then paste the manifest below (click "Copy" to copy it):',
      'COPYABLE:{"display_information":{"name":"Nira"},"features":{"app_home":{"home_tab_enabled":true,"messages_tab_enabled":true,"messages_tab_read_only_enabled":false},"bot_user":{"display_name":"Nira","always_online":true}},"oauth_config":{"scopes":{"bot":["chat:write","im:write","im:read","im:history","mpim:read","mpim:history","users:read","channels:read","channels:history","channels:join","groups:read","groups:history","app_mentions:read"]}},"settings":{"event_subscriptions":{"bot_events":["message.im"]},"socket_mode_enabled":true}}',
      '3. Click "Next" \u2192 review the summary \u2192 click "Create". Then go to "Install App" in the left sidebar \u2192 click "Install to Workspace" \u2192 click "Allow"',
      '4. In the left sidebar, click "OAuth & Permissions". Copy the "Bot User OAuth Token" (starts with xoxb-...)',
      '5. In the left sidebar, click "Basic Information" \u2192 scroll to "App-Level Tokens" \u2192 click "Generate Token and Scopes" \u2192 name it "socket" \u2192 click "Add Scope" \u2192 select "connections:write" \u2192 click "Generate" \u2192 copy the token (starts with xapp-...)',
      '6. (Optional) Still in "Basic Information", scroll to "Display Information" \u2192 upload the Nira icon as the app icon',
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

// SendBlue wizard — simplified for standalone page
export interface ChannelField {
  key: string;
  label: string;
  placeholder: string;
  type?: 'text' | 'password';
  required?: boolean;
}


export function SendBlueSection({
  agentId,
  binding,
  onDone,
  onRemove,
}: {
  agentId: string;
  binding?: ChannelBinding;
  onDone: () => void;
  onRemove: (id: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [phone, setPhone] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookStatus, setWebhookStatus] = useState<'idle' | 'registering' | 'done' | 'error'>('idle');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    if (binding) {
      sendblueHealth().then(setHealth).catch(() => {});
    }
  }, [agentId, binding]);

  const registerWebhook = async () => {
    if (!webhookUrl.trim()) return;
    setWebhookStatus('registering');
    try {
      const url = webhookUrl.trim().replace(/\/+$/, '') + '/v1/channels/sendblue/webhook';
      await sendblueRegisterWebhook(apiKey.trim(), apiSecret.trim(), url);
      setWebhookStatus('done');
    } catch {
      setWebhookStatus('error');
    }
  };

  if (binding) {
    const cfg = (binding.config || {}) as Record<string, unknown>;
    return (
      <div style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
        borderRadius: 8, marginBottom: 10,
        overflow: 'hidden',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
          <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCF1'}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage + SMS</div>
            <div style={{ fontSize: 11, color: 'var(--color-success)' }}>
              Active &mdash; text {(cfg.phone_number as string) || 'your number'} to chat
            </div>
          </div>
          <button
            onClick={() => onRemove(binding.id)}
            style={{
              fontSize: 10, padding: '2px 8px',
              background: 'transparent',
              color: 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
              borderRadius: 4, cursor: 'pointer',
            }}
          >Remove</button>
        </div>
        {health && (
          <div style={{
            borderTop: '1px solid var(--color-border)',
            padding: '8px 14px', fontSize: 11,
            color: 'var(--color-text-secondary)',
          }}>
            Webhook: {health.webhook_registered ? 'registered' : 'not registered'}
            {health.phone_number && ` \u2022 ${health.phone_number}`}
          </div>
        )}
      </div>
    );
  }

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '6px 10px',
    background: 'var(--color-bg)', border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)', fontSize: 12,
    boxSizing: 'border-box',
  };

  // Not active — setup wizard
  const steps = [
    {
      title: 'Get SendBlue API keys',
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            SendBlue lets your agent send and receive iMessages and SMS. You need an account and API credentials.
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <a
              href="https://sendblue.co"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', fontSize: 12, textDecoration: 'underline' }}
            >
              1. Sign up at sendblue.co &rarr;
            </a>
          </div>
          <div style={{ marginBottom: 8 }}>
            <a
              href="https://dashboard.sendblue.co/api-credentials"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', fontSize: 12, textDecoration: 'underline' }}
            >
              2. Go to your API Credentials page &rarr;
            </a>
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 6 }}>
            Copy the "API Key" and "API Secret" from the credentials page and paste them below.
          </div>
          <input value={apiKey} onChange={(e) => setApiKey(e.target.value)}
            placeholder="API Key" style={{ ...inputStyle, marginTop: 4 }} />
          <input value={apiSecret} onChange={(e) => setApiSecret(e.target.value)}
            placeholder="API Secret" type="password" style={{ ...inputStyle, marginTop: 4 }} />
        </div>
      ),
      canAdvance: apiKey.trim() && apiSecret.trim(),
    },
    {
      title: 'Enter your phone number',
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            Which phone number should SendBlue use? This is the number people will text to reach your agent.
          </div>
          <input value={phone} onChange={(e) => setPhone(e.target.value)}
            placeholder="+1XXXXXXXXXX" style={inputStyle} />
        </div>
      ),
      canAdvance: phone.trim().length >= 10,
    },
    {
      title: 'Set up webhook (ngrok tunnel)',
      content: (
        <div>
          <div style={{ fontSize: 12, marginBottom: 8 }}>
            SendBlue needs a public URL to send incoming messages to your local server. Use ngrok to create a tunnel.
          </div>
          <div style={{
            fontSize: 11, lineHeight: 1.6,
            color: 'var(--color-text-secondary)',
            padding: '8px 10px', marginBottom: 10,
            background: 'var(--color-bg-secondary)',
            borderRadius: 6,
            borderLeft: '3px solid var(--color-accent, var(--color-accent-purple))',
          }}>
            <div><strong>1.</strong> Open a terminal and run: <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>ngrok http 8000</code></div>
            <div style={{ marginTop: 4 }}><strong>2.</strong> Copy the <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>https://</code> forwarding URL (e.g. https://abc123.ngrok.io)</div>
            <div style={{ marginTop: 4 }}><strong>3.</strong> Paste it below and click "Register Webhook"</div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={webhookUrl}
              onChange={(e) => { setWebhookUrl(e.target.value); setWebhookStatus('idle'); }}
              placeholder="https://abc123.ngrok-free.app"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button
              onClick={registerWebhook}
              disabled={!webhookUrl.trim() || webhookStatus === 'registering'}
              style={{
                fontSize: 11, padding: '6px 12px', whiteSpace: 'nowrap',
                background: webhookStatus === 'done' ? 'var(--color-success)' : 'var(--color-accent-purple)',
                color: 'var(--color-on-accent)', border: 'none', borderRadius: 4,
                cursor: 'pointer', fontWeight: 600,
                opacity: !webhookUrl.trim() || webhookStatus === 'registering' ? 0.5 : 1,
              }}
            >
              {webhookStatus === 'registering' ? 'Registering...'
                : webhookStatus === 'done' ? 'Registered!'
                : webhookStatus === 'error' ? 'Retry'
                : 'Register Webhook'}
            </button>
          </div>
          {webhookStatus === 'done' && (
            <div style={{ fontSize: 11, color: 'var(--color-success)', marginTop: 6 }}>
              Webhook registered! Incoming texts will be forwarded to your agent.
            </div>
          )}
          {webhookStatus === 'error' && (
            <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>
              Failed to register webhook. Check your ngrok URL and SendBlue credentials.
            </div>
          )}
          <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
            Don't have ngrok? <a href="https://ngrok.com/download" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>Download it free</a>. You can also skip this step and register the webhook later.
          </div>
        </div>
      ),
      canAdvance: true, // webhook is optional — user can skip
    },
  ];

  const handleFinish = async () => {
    setLoading(true);
    setError('');
    try {
      await bindAgentChannel(agentId, 'sendblue', {
        api_key: apiKey.trim(),
        api_secret: apiSecret.trim(),
        phone_number: phone.trim(),
      });
      // If webhook was registered in the wizard, that's already done.
      // If not, try a best-effort registration with the provided URL.
      if (webhookUrl.trim() && webhookStatus !== 'done') {
        try {
          const url = webhookUrl.trim().replace(/\/+$/, '') + '/v1/channels/sendblue/webhook';
          await sendblueRegisterWebhook(apiKey.trim(), apiSecret.trim(), url);
        } catch { /* */ }
      }
      onDone();
      setStep(0);
      setApiKey('');
      setApiSecret('');
      setPhone('');
      setWebhookUrl('');
      setWebhookStatus('idle');
    } catch (err: any) {
      setError(err.message || 'Failed to connect');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      background: 'var(--color-bg-secondary)',
      border: '1px dashed var(--color-border)',
      borderRadius: 8, marginBottom: 10,
      overflow: 'hidden',
    }}>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={step >= 0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setStep(step === 0 && !apiKey ? -1 : 0);
          }
        }}
        style={{
          display: 'flex', alignItems: 'center',
          padding: '12px 14px', cursor: 'pointer',
        }}
        onClick={() => setStep(step === 0 && !apiKey ? -1 : 0)}
      >
        <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCF1'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage + SMS (SendBlue)</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
            Let people text your agent from any phone
          </div>
        </div>
        <span style={{ color: 'var(--color-accent-purple)', fontSize: 11, fontWeight: 500 }}>
          {step >= 0 ? 'Set Up' : '+ Add'}
        </span>
      </div>

      {step >= 0 && (
        <div style={{ borderTop: '1px solid var(--color-border)', padding: 14 }}>
          {/* Step indicator */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
            {steps.map((_, i) => (
              <div
                key={i}
                style={{
                  flex: 1, height: 3, borderRadius: 2,
                  background: i <= step ? 'var(--color-accent-purple)' : 'var(--color-border)',
                }}
              />
            ))}
          </div>

          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>
            {steps[step]?.title}
          </div>
          {steps[step]?.content}

          {error && (
            <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 6 }}>{error}</div>
          )}

          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            {step > 0 && (
              <button
                onClick={() => setStep(step - 1)}
                style={{
                  fontSize: 12, padding: '6px 16px',
                  background: 'var(--color-bg)',
                  color: 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 5, cursor: 'pointer',
                }}
              >Back</button>
            )}
            {step < steps.length - 1 ? (
              <button
                onClick={() => setStep(step + 1)}
                disabled={!steps[step]?.canAdvance}
                style={{
                  fontSize: 12, padding: '6px 16px',
                  background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                  border: 'none', borderRadius: 5,
                  cursor: 'pointer', fontWeight: 600,
                  opacity: steps[step]?.canAdvance ? 1 : 0.5,
                }}
              >Next</button>
            ) : (
              <button
                onClick={handleFinish}
                disabled={loading || !steps[step]?.canAdvance}
                style={{
                  fontSize: 12, padding: '6px 16px',
                  background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
                  border: 'none', borderRadius: 5,
                  cursor: 'pointer', fontWeight: 600,
                  opacity: loading || !steps[step]?.canAdvance ? 0.5 : 1,
                }}
              >{loading ? 'Connecting...' : 'Connect'}</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function MessagingSection({ agentId }: { agentId: string }) {
  const [bindings, setBindings] = useState<ChannelBinding[]>([]);
  const [setupType, setSetupType] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const loadBindings = useCallback(() => {
    fetchAgentChannels(agentId).then(setBindings).catch(() => setBindings([]));
  }, [agentId]);

  useEffect(() => { loadBindings(); }, [loadBindings]);

  const setField = (key: string, value: string) =>
    setFormValues((prev) => ({ ...prev, [key]: value }));

  const handleSetup = async (ch: MessagingChannelConfig) => {
    const missing = ch.fields.filter((f) => f.required && !formValues[f.key]?.trim());
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
    <div>
      {/* SendBlue */}
      <SendBlueSection
        agentId={agentId}
        binding={bindings.find((b) => b.channel_type === 'sendblue')}
        onDone={loadBindings}
        onRemove={(id) => { unbindAgentChannel(agentId, id).then(loadBindings).catch(() => {}); }}
      />

      {/* Other messaging channels */}
      {MESSAGING_CHANNELS.map((ch) => {
        const binding = bindings.find((b) => b.channel_type === ch.type);
        const cfg = (binding?.config || {}) as Record<string, unknown>;
        const isSetup = setupType === ch.type;
        const canConnect = ch.fields.every((f) => !f.required || formValues[f.key]?.trim());

        return (
          <div
            key={ch.type}
            style={{
              background: 'var(--color-bg-secondary)',
              border: binding ? '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)' : '1px dashed var(--color-border)',
              borderRadius: 8, marginBottom: 10, overflow: 'hidden',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
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
                      fontSize: 10, padding: '2px 8px', background: 'transparent',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 4, cursor: 'pointer',
                    }}
                  >Remove</button>
                </div>
              ) : (
                <button
                  onClick={() => { setSetupType(isSetup ? null : ch.type); setFormValues({}); }}
                  style={{
                    fontSize: 10, padding: '3px 12px', background: 'var(--color-accent-purple)',
                    color: 'var(--color-on-accent)', border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                  }}
                >{isSetup ? 'Cancel' : 'Set Up'}</button>
              )}
            </div>

            {binding && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '10px 14px', background: 'var(--color-bg)',
              }}>
                <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'flex-start', gap: 6 }}>
                  <span style={{ flexShrink: 0 }}>{'\u2192'}</span>
                  <span>{ch.howToUse(cfg)}</span>
                </div>
              </div>
            )}

            {isSetup && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: 14, background: 'var(--color-bg)',
              }}>
                <div style={{
                  fontSize: 11, lineHeight: 1.5,
                  color: 'var(--color-text-secondary)',
                  marginBottom: 12, padding: '8px 10px',
                  background: 'var(--color-bg-secondary)',
                  borderRadius: 6,
                  borderLeft: '3px solid var(--color-accent, var(--color-accent-purple))',
                }}>
                  {ch.setupSteps.map((s, i) => {
                    if (s.startsWith('COPYABLE:')) {
                      const text = s.slice(9);
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
                      <div key={i} style={{ marginBottom: i < ch.setupSteps.length - 1 ? 4 : 0 }}>{s}</div>
                    );
                  })}
                </div>
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
                <button
                  onClick={() => handleSetup(ch)}
                  disabled={loading || !canConnect}
                  style={{
                    fontSize: 12, padding: '7px 20px', background: 'var(--color-accent-purple)',
                    color: 'var(--color-on-accent)', border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                    opacity: loading || !canConnect ? 0.5 : 1, marginTop: 4,
                  }}
                >{loading ? 'Connecting...' : 'Connect'}</button>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Memory section
// ---------------------------------------------------------------------------

