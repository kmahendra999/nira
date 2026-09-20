import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowLeft, FileText } from 'lucide-react';

import {
  fetchRecentResearch,
  fetchResearchReport,
  type ResearchReport,
} from '../lib/api';

function when(seconds: number): string {
  if (!seconds) return '';
  return new Date(seconds * 1000).toLocaleString();
}

/**
 * The destination of a `nira://research/<id>` link.
 *
 * Those links have been going out over Telegram, Slack and iMessage since the
 * channel agent existed, and they led nowhere: the desktop app parsed the URL,
 * shrugged, and showed a toast saying a report was ready. It was not — the
 * full text had been discarded the moment its preview was cut from it. Now it
 * is stored, and this is where it opens.
 */
export function ResearchPage() {
  const { id } = useParams<{ id?: string }>();
  const navigate = useNavigate();

  const [report, setReport] = useState<ResearchReport | null>(null);
  const [recent, setRecent] = useState<ResearchReport[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      if (id) {
        setReport(await fetchResearchReport(id));
      } else {
        setRecent(await fetchRecentResearch());
        setReport(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load that report');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <Shell><p className="text-text-secondary">Loading…</p></Shell>;
  }

  if (error) {
    return (
      <Shell>
        <p className="text-error">{error}</p>
        <button
          onClick={() => navigate('/research')}
          className="mt-4 text-sm underline text-accent"
        >
          See recent reports
        </button>
      </Shell>
    );
  }

  if (report) {
    return (
      <Shell>
        <button
          onClick={() => navigate('/research')}
          className="flex items-center gap-1.5 text-sm mb-6 text-text-secondary
            hover:text-text transition-colors"
        >
          <ArrowLeft size={14} /> All reports
        </button>
        <h1 className="text-xl font-semibold">{report.query}</h1>
        <p className="text-xs mt-1 mb-6 text-text-tertiary">
          {when(report.created_at)}
          {report.channel ? ` · from ${report.channel}` : ''}
        </p>
        <div className="prose max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.report}</ReactMarkdown>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <h1 className="text-xl font-semibold">Research</h1>
      <p className="text-sm mt-2 mb-6 text-text-secondary">
        Long answers sent to you over a messaging channel are kept here.
      </p>
      {recent.length === 0 ? (
        <p className="text-sm text-text-tertiary">
          Nothing yet. Ask a deep question from Telegram, Slack or iMessage and
          the full report will appear here.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {recent.map((entry) => (
            <li key={entry.id}>
              <button
                onClick={() => navigate(`/research/${entry.id}`)}
                className="w-full text-left p-4 rounded-lg border border-border
                  bg-bg-secondary hover:border-accent transition-colors"
              >
                <div className="flex items-center gap-2">
                  <FileText size={14} className="text-accent shrink-0" />
                  <span className="font-medium text-sm">{entry.query}</span>
                </div>
                <p className="text-xs mt-2 text-text-secondary line-clamp-2">
                  {entry.preview}
                </p>
                <p className="text-[11px] mt-2 text-text-tertiary">
                  {when(entry.created_at)}
                  {entry.channel ? ` · ${entry.channel}` : ''}
                </p>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-8 py-10">{children}</div>
    </div>
  );
}
