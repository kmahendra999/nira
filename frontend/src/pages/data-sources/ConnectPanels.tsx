/**
 * Connecting one data source: the generic form, and Gmail's extra options.
 */

import { useEffect, useState } from 'react';
import { Upload } from 'lucide-react';
import { SOURCE_CATALOG } from '../../types/connectors';
import type {
  ConnectRequest,
  ConnectorMeta,
  OAuthSetupInfo,
} from '../../types/connectors';
import { getConnector } from '../../lib/connectors-api';

export function InlineConnectForm({
  fields,
  loading,
  disabled = false,
  onSubmit,
}: {
  fields: NonNullable<ConnectorMeta['inputFields']>;
  loading: boolean;
  disabled?: boolean;
  onSubmit: (req: ConnectRequest) => void;
}) {
  const [inputs, setInputs] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((field) => [field.name, field.defaultValue || ''])),
  );

  const update = (name: string, value: string) =>
    setInputs((p) => ({ ...p, [name]: value }));

  const allFilled = fields
    .filter((field) => field.required !== false)
    .every((field) => inputs[field.name]?.trim());
  const submitDisabled = loading || disabled || !allFilled;

  const submit = () => {
    const req: ConnectRequest = {};
    for (const f of fields) {
      if (f.name === 'email') req.email = inputs.email;
      else if (f.name === 'password') req.password = inputs.password;
      else if (f.name === 'token') req.token = inputs.token;
      else if (f.name === 'path') req.path = inputs.path;
      else if (f.name === 'host' && inputs.host?.trim()) req.host = inputs.host.trim();
      else if (f.name === 'port' && inputs.port?.trim()) req.port = Number(inputs.port);
      else if (f.name === 'security' && (inputs.security === 'tls' || inputs.security === 'starttls')) {
        req.security = inputs.security;
      }
      else req.config = { ...(req.config || {}), [f.name]: inputs[f.name] };
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
        f.type === 'select' ? (
          <select
            key={f.name}
            value={inputs[f.name] || f.defaultValue || ''}
            onChange={(e) => update(f.name, e.target.value)}
            aria-label={f.placeholder}
            style={{
              width: '100%', padding: '7px 10px',
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              borderRadius: 4, color: 'var(--color-text)',
              fontSize: 12, marginBottom: 6,
              boxSizing: 'border-box',
            }}
          >
            {(f.options || []).map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        ) : (
          <input
            key={f.name}
            value={inputs[f.name] || ''}
            onChange={(e) => update(f.name, e.target.value)}
            placeholder={f.placeholder}
            type={f.type || 'text'}
            required={f.required !== false}
            style={{
              width: '100%', padding: '7px 10px',
              background: 'var(--color-bg)',
              border: '1px solid var(--color-border)',
              borderRadius: 4, color: 'var(--color-text)',
              fontSize: 12, marginBottom: 6,
              boxSizing: 'border-box',
            }}
          />
        )
      ))}
      <button
        onClick={submit}
        disabled={submitDisabled}
        style={{
          width: '100%', padding: 8,
          background: submitDisabled ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
          color: 'var(--color-on-accent)', border: 'none',
          borderRadius: 6, fontSize: 12,
          cursor: submitDisabled ? 'default' : 'pointer',
        }}
      >
        Connect
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Generic fallback connect panel — for any backend connector that has no
// hardcoded SOURCE_CATALOG entry (no `steps`). Without this, expanding such
// a connector's "+ Add" card rendered nothing at all: no button, no input,
// no explanation, just an empty box (e.g. Spotify, Strava, Oura, GitHub
// Notifications, Google Tasks, Weather, and the Apple/News local sources).
// Branches on auth_type using the same primitives the hardcoded catalog
// entries already use (InlineConnectForm, oauth start+poll).
// ---------------------------------------------------------------------------

export function GenericConnectPanel({
  connectorId,
  displayName,
  authType,
  loading,
  disabled = false,
  onConnect,
  onOAuthStart,
}: {
  connectorId: string;
  displayName: string;
  authType: string;
  loading: boolean;
  disabled?: boolean;
  onConnect: (req: ConnectRequest) => void;
  onOAuthStart: () => void;
}) {
  const [oauthSetup, setOauthSetup] = useState<OAuthSetupInfo | null>(null);
  const [feedUrls, setFeedUrls] = useState('');

  useEffect(() => {
    if (authType !== 'oauth') return;
    let cancelled = false;
    getConnector(connectorId)
      .then((info) => {
        if (!cancelled) setOauthSetup(info.oauth_setup ?? null);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [connectorId, authType]);

  if (authType === 'local') {
    if (connectorId === 'news_rss') {
      const feeds = feedUrls
        .split('\n')
        .map((url) => url.trim())
        .filter(Boolean)
        .map((url) => ({ url }));
      return (
        <div>
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
            Add one RSS or Atom feed URL per line.
          </div>
          <textarea
            value={feedUrls}
            onChange={(event) => setFeedUrls(event.target.value)}
            placeholder={'https://example.com/feed.xml\nhttps://example.org/rss'}
            rows={4}
            style={{ width: '100%', padding: '7px 10px', background: 'var(--color-bg)', border: '1px solid var(--color-border)', borderRadius: 4, color: 'var(--color-text)', fontSize: 12, marginBottom: 6, boxSizing: 'border-box' }}
          />
          <button
            onClick={() => onConnect({ config: { feeds } })}
            disabled={loading || disabled || feeds.length === 0}
            style={{ width: '100%', padding: 8, background: loading || disabled || feeds.length === 0 ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)', color: 'var(--color-on-accent)', border: 'none', borderRadius: 6, fontSize: 12, cursor: loading || disabled || feeds.length === 0 ? 'default' : 'pointer' }}
          >
            {loading ? 'Connecting...' : 'Save feeds'}
          </button>
        </div>
      );
    }
    return (
      <div>
        <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
          {displayName} reads data directly from this device. Grant access if
          prompted, then connect.
        </div>
        <button
          onClick={() => onConnect({})}
          disabled={loading || disabled}
          style={{
            width: '100%', padding: 8,
            background: loading || disabled ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
            color: 'var(--color-on-accent)', border: 'none',
            borderRadius: 6, fontSize: 12,
            cursor: loading || disabled ? 'default' : 'pointer',
          }}
        >
          {loading ? 'Connecting...' : `Connect ${displayName}`}
        </button>
      </div>
    );
  }

  if (authType === 'token') {
    return (
      <div>
        <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
          Enter your {displayName} API token.
        </div>
        <InlineConnectForm
          fields={connectorId === 'weather'
            ? [
                { name: 'token', placeholder: 'OpenWeather API key', type: 'password' },
                { name: 'location', placeholder: 'City, country (for example: Boston,US)', type: 'text' },
              ]
            : [{ name: 'token', placeholder: `${displayName} API token`, type: 'password' }]}
          loading={loading}
          disabled={disabled}
          onSubmit={onConnect}
        />
      </div>
    );
  }

  // auth_type === 'oauth' (default for anything else without a catalog entry)
  if (oauthSetup?.has_credentials) {
    return (
      <div>
        <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
          OAuth app credentials are already configured. Continue directly to
          {oauthSetup.provider ? ` ${oauthSetup.provider}` : ' the provider'} sign-in.
        </div>
        <button
          onClick={onOAuthStart}
          disabled={loading || disabled}
          style={{
            width: '100%', padding: 8,
            background: loading || disabled ? 'var(--color-disabled-bg)' : 'var(--color-accent-purple)',
            color: 'var(--color-on-accent)', border: 'none',
            borderRadius: 6, fontSize: 12,
            cursor: loading || disabled ? 'default' : 'pointer',
          }}
        >
          {loading ? 'Connecting...' : `Continue with ${oauthSetup.provider || displayName}`}
        </button>
      </div>
    );
  }

  return (
    <div>
      {oauthSetup && !oauthSetup.has_credentials && (
        <div style={{
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          borderRadius: 6, padding: 10, marginBottom: 10,
        }}>
          <div style={{ color: 'var(--color-accent-purple)', fontSize: 10, fontWeight: 600, marginBottom: 3 }}>
            SETUP REQUIRED
          </div>
          <div style={{ fontSize: 12, marginBottom: 6 }}>{oauthSetup.setup_hint}</div>
          <a
            href={oauthSetup.setup_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: 'var(--color-accent)', fontSize: 11, textDecoration: 'underline' }}
          >
            Open developer dashboard &rarr;
          </a>
        </div>
      )}
      <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 10 }}>
        Paste the Client ID and Client Secret from the app you created above.
      </div>
      <InlineConnectForm
        fields={[
          { name: 'email', placeholder: 'Client ID', type: 'text' },
          { name: 'password', placeholder: 'Client Secret', type: 'password' },
        ]}
        loading={loading}
        disabled={disabled}
        onSubmit={onConnect}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upload / Paste form
// ---------------------------------------------------------------------------

export function GmailOAuthAdvanced({
  loading,
  disabled = false,
  onConnect,
}: {
  loading: boolean;
  disabled?: boolean;
  onConnect: (req: ConnectRequest) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ marginTop: 12 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={disabled}
        style={{
          background: 'transparent',
          border: 'none',
          padding: 0,
          fontSize: 11,
          color: 'var(--color-text-tertiary)',
          cursor: disabled ? 'default' : 'pointer',
          opacity: disabled ? 0.5 : 1,
          textDecoration: 'underline',
        }}
      >
        {open ? 'Hide advanced' : 'Advanced: Connect with Google OAuth'}
      </button>
      {open && (
        <div
          style={{
            marginTop: 8,
            padding: 10,
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
          }}
        >
          <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginBottom: 8 }}>
            For developers with an existing Google Cloud project. Enable the
            Gmail API and create a Desktop OAuth client at{' '}
            <a
              href="https://console.cloud.google.com/apis/credentials"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--color-accent)', textDecoration: 'underline' }}
            >
              Google Cloud Credentials →
            </a>{' '}
            then paste the Client ID and Client Secret below.
          </div>
          <InlineConnectForm
            fields={[
              { name: 'email', placeholder: 'Client ID', type: 'text' },
              { name: 'password', placeholder: 'Client Secret', type: 'password' },
            ]}
            loading={loading}
            disabled={disabled}
            onSubmit={onConnect}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Data Sources section
// ---------------------------------------------------------------------------

// Sync status display component with progress bar
