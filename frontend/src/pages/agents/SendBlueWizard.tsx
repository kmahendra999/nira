/**
 * The SendBlue setup wizard — iMessage and SMS, step by step.
 *
 * 485 lines of AgentsPage that touch nothing else on it: its own multi-step
 * flow with its own state, there only because that is where it was written.
 */

import { useEffect, useState } from 'react';
import {
  bindAgentChannel,
  unbindAgentChannel,
  sendblueVerify,
  sendblueRegisterWebhook,
  sendblueTest,
  sendblueHealth,
} from '../../lib/api';
import type { ChannelBinding } from '../../lib/api';
import { Send, Copy, Check } from 'lucide-react';

export function SendBlueWebhookStep({
  apiKey, apiSecret, selectedNumber,
}: {
  apiKey: string; apiSecret: string; selectedNumber: string;
}) {
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookStatus, setWebhookStatus] = useState<'idle' | 'registering' | 'done' | 'error'>('idle');

  const registerWebhook = async () => {
    if (!webhookUrl.trim()) return;
    setWebhookStatus('registering');
    try {
      const url = webhookUrl.trim().replace(/\/+$/, '') + '/v1/channels/sendblue/webhook';
      await sendblueRegisterWebhook(apiKey, apiSecret, url);
      setWebhookStatus('done');
    } catch {
      setWebhookStatus('error');
    }
  };

  return (
    <div style={{ borderTop: '1px solid var(--color-border)', padding: 14, background: 'var(--color-bg)' }}>
      <div style={{
        background: 'color-mix(in srgb, var(--color-success) 10%, var(--color-bg))', border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
        borderRadius: 6, padding: 12, marginBottom: 12, textAlign: 'center',
      }}>
        <div style={{ fontSize: 11, color: 'var(--color-success)', fontWeight: 600, marginBottom: 4 }}>
          {'\u2713'} Your agent is now reachable via iMessage / SMS
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-success)' }}>{selectedNumber}</div>
      </div>

      {/* Webhook / ngrok step */}
      <div style={{ marginTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <span style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>4</span>
          <span style={{ fontSize: 12, fontWeight: 600 }}>Set up webhook to receive texts</span>
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
          <div style={{ marginTop: 4 }}><strong>2.</strong> Copy the <code style={{ color: 'var(--color-accent)', background: 'var(--color-bg)', padding: '1px 4px', borderRadius: 3 }}>https://</code> forwarding URL</div>
          <div style={{ marginTop: 4 }}><strong>3.</strong> Paste it below and click "Register Webhook"</div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            value={webhookUrl}
            onChange={(e) => { setWebhookUrl(e.target.value); setWebhookStatus('idle'); }}
            placeholder="https://abc123.ngrok-free.app"
            style={{
              flex: 1, padding: '7px 10px', background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)', borderRadius: 4,
              color: 'var(--color-text)', fontSize: 12, boxSizing: 'border-box' as const,
            }}
          />
          <button
            onClick={registerWebhook}
            disabled={!webhookUrl.trim() || webhookStatus === 'registering'}
            style={{
              fontSize: 11, padding: '7px 14px', whiteSpace: 'nowrap' as const,
              background: webhookStatus === 'done' ? 'var(--color-success)' : 'var(--color-accent-purple)',
              color: 'var(--color-on-accent)', border: 'none', borderRadius: 5,
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
            Failed to register. Check your ngrok URL and try again.
          </div>
        )}
        <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 8 }}>
          Don't have ngrok? <a href="https://ngrok.com/download" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>Download it free</a>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SendBlue setup wizard — guided multi-step flow
// ---------------------------------------------------------------------------

export function SendBlueWizard({
  agentId,
  binding,
  onDone,
  onRemove,
}: {
  agentId: string;
  binding: ChannelBinding | undefined;
  onDone: () => void;
  onRemove: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [step, setStep] = useState<'idle' | 'creds' | 'verifying' | 'verified' | 'connecting' | 'done' | 'test'>('idle');
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [numbers, setNumbers] = useState<string[]>([]);
  const [selectedNumber, setSelectedNumber] = useState('');
  const [error, setError] = useState('');
  const [testNumber, setTestNumber] = useState('');
  const [testSent, setTestSent] = useState(false);

  const [healthy, setHealthy] = useState(true);
  const [reconnecting, setReconnecting] = useState(false);

  const isActive = !!binding;
  const activeNumber = (binding?.config?.from_number as string) || '';

  // Check health on mount when active
  useEffect(() => {
    if (!isActive) return;
    sendblueHealth().then((h) => setHealthy(h.ready)).catch(() => setHealthy(false));
  }, [isActive]);

  const handleReconnect = async () => {
    if (!binding) return;
    setReconnecting(true);
    try {
      // Re-bind to re-create the bridge
      const cfg = binding.config || {};
      await unbindAgentChannel(agentId, binding.id);
      await bindAgentChannel(agentId, 'sendblue', cfg as Record<string, unknown>);
      setHealthy(true);
      onDone();
    } catch { /* */ } finally { setReconnecting(false); }
  };

  const cardStyle: React.CSSProperties = {
    background: 'var(--color-bg-secondary)',
    border: isActive ? '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)' : '1px dashed var(--color-border)',
    borderRadius: 8, marginBottom: 10, overflow: 'hidden',
  };

  const btnPrimary: React.CSSProperties = {
    fontSize: 12, padding: '7px 18px', background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)',
    border: 'none', borderRadius: 5, cursor: 'pointer', fontWeight: 600,
  };

  const btnSecondary: React.CSSProperties = {
    fontSize: 11, padding: '5px 14px', background: 'transparent',
    color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)',
    borderRadius: 4, cursor: 'pointer',
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '7px 10px', background: 'var(--color-bg-secondary)',
    border: '1px solid var(--color-border)', borderRadius: 4,
    color: 'var(--color-text)', fontSize: 12, boxSizing: 'border-box',
  };

  const handleVerify = async () => {
    setError('');
    setStep('verifying');
    try {
      const result = await sendblueVerify(apiKey, apiSecret);
      if (result.valid && result.numbers.length > 0) {
        setNumbers(result.numbers);
        setSelectedNumber(result.numbers[0]);
        setStep('verified');
      } else if (result.valid) {
        // Free tier / shared line — no dedicated number returned
        // Move to verified step so user can enter the number manually
        setNumbers([]);
        setSelectedNumber('');
        setStep('verified');
      } else {
        setError('Invalid credentials. Check your API key and secret.');
        setStep('creds');
      }
    } catch (e) {
      setError((e as Error).message);
      setStep('creds');
    }
  };

  const handleConnect = async () => {
    setError('');
    setStep('connecting');
    try {
      // 1. Bind the channel
      await bindAgentChannel(agentId, 'sendblue', {
        api_key_id: apiKey,
        api_secret_key: apiSecret,
        from_number: selectedNumber,
      });
      // 2. Try to auto-register webhook (best effort)
      try {
        const webhookUrl = `${window.location.origin}/webhooks/sendblue`;
        await sendblueRegisterWebhook(apiKey, apiSecret, webhookUrl);
      } catch {
        // Non-fatal — user may need to set up ngrok manually
      }
      setStep('done');
      onDone();
    } catch (e) {
      setError((e as Error).message);
      setStep('verified');
    }
  };

  const handleTest = async () => {
    if (!testNumber.trim()) return;
    setError('');
    try {
      const cfg = binding?.config || {};
      await sendblueTest(
        (cfg.api_key_id as string) || apiKey,
        (cfg.api_secret_key as string) || apiSecret,
        activeNumber || selectedNumber,
        testNumber.trim(),
      );
      setTestSent(true);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  // Active state
  if (isActive && !expanded) {
    return (
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
          <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCAC'}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage / SMS</div>
            <div style={{ fontSize: 11, color: healthy ? 'var(--color-success)' : 'var(--color-warning)' }}>
              {healthy ? `Active on ${activeNumber}` : `Disconnected — ${activeNumber}`}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {!healthy && (
              <button
                onClick={handleReconnect}
                disabled={reconnecting}
                style={{ ...btnPrimary, fontSize: 10, padding: '3px 10px' }}
              >
                {reconnecting ? '...' : 'Reconnect'}
              </button>
            )}
            <span style={{
              background: healthy ? 'color-mix(in srgb, var(--color-success) 22%, transparent)' : 'color-mix(in srgb, var(--color-warning) 18%, var(--color-bg))',
              color: healthy ? 'var(--color-success)' : 'var(--color-warning)',
              padding: '2px 8px', borderRadius: 10, fontSize: 10, fontWeight: 600,
            }}>{healthy ? 'Active' : 'Disconnected'}</span>
            <button onClick={() => setExpanded(true)} style={btnSecondary}>
              Details
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Active + expanded (show how to use + test)
  if (isActive && expanded) {
    return (
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px' }}>
          <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCAC'}</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage / SMS</div>
            <div style={{ fontSize: 11, color: 'var(--color-success)' }}>Active on {activeNumber}</div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setExpanded(false)} style={btnSecondary}>Collapse</button>
            <button onClick={() => onRemove(binding!.id)} style={{ ...btnSecondary, color: 'var(--color-error)' }}>Remove</button>
          </div>
        </div>
        <div style={{ borderTop: '1px solid var(--color-border)', padding: 14, background: 'var(--color-bg)' }}>
          <div style={{ fontSize: 12, marginBottom: 10, lineHeight: 1.6 }}>
            {'\u2192'} Text <strong>{activeNumber}</strong> from any phone to talk to your agent.
            Responses arrive as iMessage (blue bubbles) when possible, SMS otherwise.
          </div>

          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 8, fontWeight: 600 }}>
            Send a test message
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={testNumber}
              onChange={(e) => { setTestNumber(e.target.value); setTestSent(false); }}
              placeholder="Your phone number (+1...)"
              style={{ ...inputStyle, flex: 1 }}
            />
            <button
              onClick={handleTest}
              disabled={!testNumber.trim() || testSent}
              style={{ ...btnPrimary, opacity: !testNumber.trim() ? 0.5 : 1 }}
            >
              {testSent ? 'Sent!' : 'Send Test'}
            </button>
          </div>
          {error && <div style={{ color: 'var(--color-error)', fontSize: 11, marginTop: 6 }}>{error}</div>}
        </div>
      </div>
    );
  }

  // Not active — setup wizard
  return (
    <div style={cardStyle}>
      {/* Header */}
      <div
        role="button"
        tabIndex={0}
        aria-expanded={step !== 'idle'}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setStep(step === 'idle' ? 'creds' : 'idle');
          }
        }}
        style={{ display: 'flex', alignItems: 'center', padding: '12px 14px', cursor: 'pointer' }}
        onClick={() => setStep(step === 'idle' ? 'creds' : 'idle')}
      >
        <span style={{ fontSize: 18, marginRight: 10 }}>{'\uD83D\uDCAC'}</span>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>iMessage / SMS</div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>
            Your agent gets its own phone number — text it via iMessage or SMS
          </div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); setStep(step === 'idle' ? 'creds' : 'idle'); }}
          style={{ fontSize: 10, padding: '3px 12px', background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)', border: 'none', borderRadius: 5, cursor: 'pointer', fontWeight: 600 }}
        >
          {step === 'idle' ? 'Set Up' : 'Cancel'}
        </button>
      </div>

      {/* Step 1: Sign up + enter credentials */}
      {(step === 'creds' || step === 'verifying') && (
        <div style={{ borderTop: '1px solid var(--color-border)', padding: 14, background: 'var(--color-bg)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>1</span>
            <span style={{ fontSize: 12, fontWeight: 600 }}>Create a SendBlue account</span>
          </div>
          <button
            onClick={() => window.open('https://dashboard.sendblue.com/company-signup', '_blank')}
            style={{ ...btnPrimary, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 6 }}
          >
            Open SendBlue signup {'\u2192'}
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>2</span>
            <span style={{ fontSize: 12, fontWeight: 600 }}>Paste your API credentials</span>
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 8 }}>
            Go to your{' '}
            <a href="https://dashboard.sendblue.co/api-credentials" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}>
              SendBlue API Credentials page
            </a>{' '}
            and copy the API Key and API Secret.
          </div>

          <div style={{ marginBottom: 8 }}>
            <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 3, fontWeight: 500 }}>
              API Key ID *
            </label>
            <input value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="Your API key ID" style={inputStyle} />
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 3, fontWeight: 500 }}>
              API Secret Key *
            </label>
            <input value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} placeholder="Your API secret key" type="password" style={inputStyle} />
          </div>

          {error && <div style={{ color: 'var(--color-error)', fontSize: 11, marginBottom: 8 }}>{error}</div>}

          <button
            onClick={handleVerify}
            disabled={!apiKey.trim() || !apiSecret.trim() || step === 'verifying'}
            style={{ ...btnPrimary, opacity: !apiKey.trim() || !apiSecret.trim() ? 0.5 : 1 }}
          >
            {step === 'verifying' ? 'Verifying...' : 'Verify & Find Number'}
          </button>
        </div>
      )}

      {/* Step 2: Number found — confirm + connect */}
      {(step === 'verified' || step === 'connecting') && (
        <div style={{ borderTop: '1px solid var(--color-border)', padding: 14, background: 'var(--color-bg)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ background: 'var(--color-success)', color: 'var(--color-on-accent)', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>{'\u2713'}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-success)' }}>Credentials verified</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)', borderRadius: '50%', width: 20, height: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, fontWeight: 700, flexShrink: 0 }}>3</span>
            <span style={{ fontSize: 12, fontWeight: 600 }}>Your agent's phone number</span>
          </div>

          {numbers.length > 1 ? (
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 3, fontWeight: 500 }}>
                Select a number for your agent
              </label>
              <select
                value={selectedNumber}
                onChange={(e) => setSelectedNumber(e.target.value)}
                style={{ ...inputStyle, padding: '8px 10px' }}
              >
                {numbers.map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          ) : numbers.length === 1 ? (
            <div style={{
              background: 'var(--color-bg-secondary)', border: '1px solid color-mix(in srgb, var(--color-success) 22%, transparent)',
              borderRadius: 6, padding: '10px 12px', marginBottom: 12,
              display: 'flex', alignItems: 'center', gap: 8,
            }}>
              <span style={{ fontSize: 20 }}>{'\uD83D\uDCF1'}</span>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--color-success)' }}>{selectedNumber}</div>
                <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>This will be your agent's phone number</div>
              </div>
            </div>
          ) : (
            <div style={{ marginBottom: 12 }}>
              <div style={{
                fontSize: 11, color: 'var(--color-text-secondary)',
                marginBottom: 8, lineHeight: 1.5,
                padding: '8px 10px', background: 'var(--color-bg-secondary)',
                borderRadius: 6, borderLeft: '3px solid var(--color-accent-purple)',
              }}>
                Copy the phone number shown under <strong>"Send from"</strong> in your SendBlue dashboard
                and paste it below. On the free tier this is a shared number.
              </div>
              <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-secondary)', marginBottom: 3, fontWeight: 500 }}>
                SendBlue phone number *
              </label>
              <input
                value={selectedNumber}
                onChange={(e) => setSelectedNumber(e.target.value)}
                placeholder="+16452468235"
                style={inputStyle}
              />
            </div>
          )}

          {error && <div style={{ color: 'var(--color-error)', fontSize: 11, marginBottom: 8 }}>{error}</div>}

          <button
            onClick={handleConnect}
            disabled={step === 'connecting' || !selectedNumber.trim()}
            style={{ ...btnPrimary, opacity: !selectedNumber.trim() ? 0.5 : 1 }}
          >
            {step === 'connecting' ? 'Connecting...' : 'Activate Phone Number'}
          </button>
        </div>
      )}

      {/* Step 3: Done — success + webhook setup */}
      {step === 'done' && (
        <SendBlueWebhookStep
          apiKey={apiKey}
          apiSecret={apiSecret}
          selectedNumber={selectedNumber}
        />
      )}
    </div>
  );
}

