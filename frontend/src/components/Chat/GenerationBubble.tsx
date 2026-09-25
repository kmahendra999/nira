import { useEffect, useState } from 'react';
import { X, Download, AlertCircle } from 'lucide-react';
import {
  cancelGeneration,
  fetchGenerationJob,
  generationResultUrl,
  type GenerateJob,
} from '../../lib/api';

/**
 * A generation job, shown where it was asked for.
 *
 * Polls rather than holding a result, because the job outlives the component:
 * a video takes minutes, and the user can navigate away, reload, or reopen
 * the conversation tomorrow. Only the job id is persisted with the message,
 * so this is the only place that knows whether the file still exists.
 *
 * Polling stops the moment the job reaches a terminal state — a finished
 * conversation must not keep asking a CPU-bound machine about work that
 * ended.
 */
export function GenerationBubble({
  jobId,
  kind,
}: {
  jobId: string;
  kind: 'image' | 'audio' | 'video';
}) {
  const [job, setJob] = useState<GenerateJob | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    let stopped = false;
    let timer: number | null = null;

    const tick = async () => {
      try {
        const next = await fetchGenerationJob(jobId);
        if (stopped) return;
        setJob(next);
        if (next.status === 'queued' || next.status === 'running') {
          timer = window.setTimeout(tick, 2000);
        }
      } catch {
        // The job has aged out of the queue's history, or this conversation
        // came from another machine. Either way the file is not reachable.
        if (!stopped) setGone(true);
      }
    };
    void tick();

    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId]);

  useEffect(() => {
    if (job?.status !== 'done') return;
    let stale = false;
    let created: string | null = null;
    generationResultUrl(jobId).then((next) => {
      if (stale) {
        if (next) URL.revokeObjectURL(next);
        return;
      }
      created = next;
      if (next) setUrl(next);
      else setGone(true);
    });
    return () => {
      stale = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [jobId, job?.status]);

  if (gone) {
    return (
      <div
        className="flex items-center gap-2 text-xs px-3 py-2 rounded-xl"
        style={{ color: 'var(--color-text-tertiary)', border: '1px solid var(--color-border)' }}
      >
        <AlertCircle size={13} />
        That {kind} is no longer available.
      </div>
    );
  }

  if (!job) {
    return (
      <div
        className="h-24 w-64 rounded-xl animate-pulse"
        style={{ background: 'var(--color-bg-tertiary)' }}
      />
    );
  }

  if (job.status === 'failed') {
    return (
      <div
        className="text-xs px-3 py-2 rounded-xl"
        style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}
      >
        {job.error || `Could not create that ${kind}.`}
      </div>
    );
  }

  if (job.status === 'cancelled') {
    return (
      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        Cancelled.
      </div>
    );
  }

  if (job.status !== 'done') {
    const seconds = job.elapsed_seconds ?? 0;
    return (
      <div
        className="rounded-xl px-3 py-2.5 w-full max-w-sm"
        style={{
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
        }}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {job.detail || 'Starting…'}
          </span>
          <button
            onClick={() => void cancelGeneration(jobId)}
            className="p-1 rounded cursor-pointer shrink-0"
            style={{ color: 'var(--color-text-tertiary)' }}
            title="Stop"
          >
            <X size={12} />
          </button>
        </div>
        {job.progress != null && (
          <div
            className="h-1 rounded-full mt-2 overflow-hidden"
            style={{ background: 'var(--color-bg-tertiary)' }}
          >
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.round(job.progress * 100)}%`,
                background: 'var(--color-accent)',
              }}
            />
          </div>
        )}
        <div className="text-[10px] mt-1.5" style={{ color: 'var(--color-text-tertiary)' }}>
          {seconds < 60
            ? `${Math.round(seconds)}s elapsed`
            : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s elapsed`}
        </div>
      </div>
    );
  }

  if (!url) {
    return (
      <div
        className="h-24 w-64 rounded-xl animate-pulse"
        style={{ background: 'var(--color-bg-tertiary)' }}
      />
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      {kind === 'image' && (
        <img src={url} alt={job.prompt} className="rounded-xl max-w-full" />
      )}
      {kind === 'video' && (
        <video src={url} controls loop className="rounded-xl max-w-full" />
      )}
      {kind === 'audio' && <audio src={url} controls className="w-full max-w-sm" />}
      <a
        href={url}
        download={job.result || jobId}
        className="flex items-center gap-1.5 text-[11px] self-start"
        style={{ color: 'var(--color-accent)' }}
      >
        <Download size={11} /> Save
      </a>
    </div>
  );
}
