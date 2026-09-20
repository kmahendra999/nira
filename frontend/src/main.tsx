import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { ErrorBoundary } from './components/ErrorBoundary';
import App from './App';
import { initApiBase } from './lib/api';
import { initAnalytics } from './lib/analytics';
// Geist has been a dependency with no importer, so the app rendered in
// whatever the platform's default sans happened to be. Self-hosted rather
// than fetched from a CDN: a local-first assistant should not need the
// network to draw its own text.
import '@fontsource-variable/geist';

import './index.css';

export function prefersDark(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  );
}

/**
 * Put the resolved theme on <html> as a class.
 *
 * `system` used to add no class at all and lean on a
 * `prefers-color-scheme` block in CSS, which meant the whole dark palette
 * existed twice — once under `.dark`, once in the media query — and any
 * recolour had to be made in both or system-theme users silently kept the
 * old one. Resolving the preference here leaves CSS with a single source of
 * truth for what dark looks like.
 */
function applyTheme() {
  const root = document.documentElement;
  let theme = 'system';
  try {
    const raw = localStorage.getItem('nira-settings');
    theme = (raw ? JSON.parse(raw) : {}).theme || 'system';
  } catch {
    /* unreadable settings: fall back to the system preference */
  }
  const dark = theme === 'dark' || (theme === 'system' && prefersDark());
  root.classList.toggle('dark', dark);
  root.classList.toggle('light', !dark);
}

applyTheme();

// Fetch the API base URL from the Tauri backend before rendering.
// This ensures NIRA_PORT is defined in one place (the Rust backend).
// In non-Tauri environments this is a no-op.
initApiBase().finally(() => {
  // Kick off analytics init in the background — it's never awaited so
  // a slow/failed identity fetch never delays UI render.
  void initAnalytics();

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ErrorBoundary>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ErrorBoundary>
    </StrictMode>,
  );
});
