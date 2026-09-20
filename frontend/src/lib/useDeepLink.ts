/**
 * useDeepLink — delivers `nira://` URLs to the running app.
 *
 * The backend hands these out: channel_agent.py replies to a long research
 * query over Telegram/iMessage/Slack with "Full report ready — open in Nira:
 * nira://research/<session_id>". tauri.conf.json registers the scheme with the
 * OS, so clicking one launches or focuses Nira — but nothing was listening, and
 * `parseDeepLink` had no callers, so the URL was dropped on the floor every
 * time.
 *
 * Two arrival paths, and both matter: `getCurrent()` covers a cold start (the
 * link launched the app, so the event fired before React mounted) and
 * `onOpenUrl` covers an app that was already open.
 */

import { useEffect } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';

import { isTauri } from './api';
import { parseDeepLink } from './deep-link';

export function useDeepLink(): void {
  const navigate = useNavigate();

  useEffect(() => {
    // Browsers and the PWA never receive custom-scheme URLs.
    if (!isTauri()) return;

    let cancelled = false;
    let unlisten: (() => void) | undefined;

    const handle = (urls: string[] | null) => {
      const url = urls?.[0];
      if (!url) return;

      const target = parseDeepLink(url);
      if (!target) {
        toast.error('Could not open link', { description: url });
        return;
      }

      switch (target.type) {
        case 'research':
          // A real navigation at last. This used to land on the home page
          // with a toast, because the report had nowhere to be read from —
          // the full text was discarded the moment its preview was cut from
          // it, so the link promised something that no longer existed.
          navigate(`/research/${encodeURIComponent(target.id)}`);
          break;
        case 'connector':
          navigate('/data-sources');
          break;
        default:
          toast.error('Unknown link type', {
            description: `${target.type}: ${target.id}`,
          });
      }
    };

    void (async () => {
      try {
        const { getCurrent, onOpenUrl } = await import(
          '@tauri-apps/plugin-deep-link'
        );
        const launchUrls = await getCurrent();
        if (cancelled) return;
        handle(launchUrls);
        const stop = await onOpenUrl(handle);
        if (cancelled) {
          stop();
          return;
        }
        unlisten = stop;
      } catch (err) {
        // A missing plugin must not take the app down with it.
        console.warn('deep-link unavailable:', err);
      }
    })();

    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [navigate]);
}
