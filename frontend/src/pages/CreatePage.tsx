import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Image as ImageIcon,
  Music,
  Film,
  Play,
  X,
  Download,
  AlertCircle,
  Clock,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  cancelGeneration,
  fetchGenerateCapabilities,
  generationResultUrl,
  listGenerationJobs,
  startGeneration,
  type GenerateCapabilities,
  type GenerateJob,
  type GenerateKind,
} from '../lib/api';

/**
 * Making an image, a sound or a short video, locally.
 *
 * The page is built around the wait, because on a machine with no GPU the
 * wait is the dominant fact: an image is tens of seconds and a video is
 * minutes. So every job shows elapsed time, a step-by-step estimate from the
 * backend, and a cancel button — and the queue keeps running if you navigate
 * away, because it lives on the server.
 */

const KINDS: Array<{
  id: GenerateKind;
  label: string;
  icon: typeof ImageIcon;
  placeholder: string;
  expect: string;
}> = [
  {
    id: 'image',
    label: 'Image',
    icon: ImageIcon,
    placeholder: 'A red bicycle against a white wall, morning light',
    expect: 'Tens of seconds with the turbo models.',
  },
  {
    id: 'audio',
    label: 'Audio',
    icon: Music,
    placeholder: 'Read this aloud, or: warm lo-fi piano loop',
    expect: 'Speech is near-instant. Music is roughly 6s of work per second of audio.',
  },
  {
    id: 'video',
    label: 'Video',
    icon: Film,
    placeholder: 'A paper boat drifting down a stream',
    expect: 'Minutes, not seconds — sixteen frames is sixty-four passes through the model.',
  },
];

function StatusPill({ job }: { job: GenerateJob }) {
  const colour =
    job.status === 'done'
      ? 'var(--color-success)'
      : job.status === 'failed'
        ? 'var(--color-error)'
        : job.status === 'cancelled'
          ? 'var(--color-text-tertiary)'
          : 'var(--color-accent)';
  return (
    <span className="text-[10px] uppercase tracking-wide" style={{ color: colour }}>
      {job.status}
    </span>
  );
}

function JobResult({ job }: { job: GenerateJob }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (job.status !== 'done') return;
    let stale = false;
    let created: string | null = null;
    generationResultUrl(job.id).then((next) => {
      if (stale) {
        if (next) URL.revokeObjectURL(next);
        return;
      }
      created = next;
      setUrl(next);
    });
    return () => {
      stale = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [job.id, job.status]);

  if (job.status !== 'done' || !url) return null;

  return (
    <div className="mt-2 flex flex-col gap-2">
      {job.kind === 'image' && (
        <img
          src={url}
          alt={job.prompt}
          className="rounded-lg max-w-full"
          style={{ background: 'var(--color-bg-tertiary)' }}
        />
      )}
      {job.kind === 'video' && (
        <video src={url} controls loop className="rounded-lg max-w-full" />
      )}
      {job.kind === 'audio' && <audio src={url} controls className="w-full" />}
      <a
        href={url}
        download={job.result || `${job.id}`}
        className="flex items-center gap-1.5 text-[11px] self-start"
        style={{ color: 'var(--color-accent)' }}
      >
        <Download size={11} /> Save
      </a>
    </div>
  );
}

export function CreatePage() {
  const [kind, setKind] = useState<GenerateKind>('image');
  const [prompt, setPrompt] = useState('');
  const [capabilities, setCapabilities] = useState<GenerateCapabilities | null>(null);
  const [jobs, setJobs] = useState<GenerateJob[]>([]);
  const [model, setModel] = useState('');
  const [audioMode, setAudioMode] = useState<'speech' | 'music'>('music');
  const [seconds, setSeconds] = useState(10);
  const [frames, setFrames] = useState(16);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    fetchGenerateCapabilities().then(setCapabilities).catch(() => setCapabilities(null));
  }, []);

  // Poll while anything is in flight, and stop when nothing is. A fixed
  // interval would keep a CPU-bound box busy answering questions about work
  // that finished an hour ago.
  const refresh = useCallback(async () => {
    const next = await listGenerationJobs(20);
    setJobs(next);
    return next;
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const busy = jobs.some((j) => j.status === 'queued' || j.status === 'running');
    if (!busy) {
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    if (pollRef.current) return;
    pollRef.current = window.setInterval(() => void refresh(), 2000);
    return () => {
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [jobs, refresh]);

  const active = KINDS.find((k) => k.id === kind)!;
  const support = capabilities?.[kind];
  const unavailable = capabilities && support && !support.available;

  const models = useMemo(() => {
    if (kind === 'image') return capabilities?.image.models ?? [];
    if (kind === 'video') return capabilities?.video.models ?? [];
    return [];
  }, [capabilities, kind]);

  const submit = useCallback(async () => {
    const text = prompt.trim();
    if (!text) return;
    setStarting(true);
    try {
      const options: Record<string, unknown> = {};
      if (model) options.model = model;
      if (kind === 'audio') {
        options.mode = audioMode;
        if (audioMode === 'music') options.seconds = seconds;
      }
      if (kind === 'video') options.frames = frames;

      const job = await startGeneration(kind, text, options);
      setJobs((current) => [job, ...current]);
      setPrompt('');
    } catch (err: any) {
      toast.error(err?.message ?? 'Could not start', { duration: 8000 });
    } finally {
      setStarting(false);
    }
  }, [prompt, kind, model, audioMode, seconds, frames]);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-8 flex flex-col gap-6">
        <div>
          <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
            Create
          </h2>
          <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
            Images, audio and video, generated on this machine. Nothing is sent
            anywhere.
          </p>
        </div>

        {/* Kind */}
        <div className="flex gap-2">
          {KINDS.map((option) => {
            const Icon = option.icon;
            const selected = option.id === kind;
            return (
              <button
                key={option.id}
                onClick={() => {
                  setKind(option.id);
                  setModel('');
                }}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm cursor-pointer transition-colors"
                style={{
                  background: selected
                    ? 'var(--color-accent-subtle)'
                    : 'var(--color-bg-secondary)',
                  border: `1px solid ${selected ? 'var(--color-accent)' : 'var(--color-border)'}`,
                  color: selected ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                }}
              >
                <Icon size={14} />
                {option.label}
              </button>
            );
          })}
        </div>

        {unavailable && (
          <div
            className="text-xs px-3 py-2 rounded-lg flex items-start gap-2"
            style={{ color: 'var(--color-error)', border: '1px solid var(--color-error)' }}
          >
            <AlertCircle size={13} className="shrink-0 mt-0.5" />
            <span>{support?.reason}</span>
          </div>
        )}

        {/* Prompt */}
        <div className="flex flex-col gap-2">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit();
            }}
            placeholder={active.placeholder}
            rows={3}
            className="w-full rounded-xl px-3 py-2.5 text-sm outline-none resize-none"
            style={{
              background: 'var(--color-input-bg)',
              border: '1px solid var(--color-input-border)',
              color: 'var(--color-text)',
            }}
          />
          <div className="flex items-center gap-2 flex-wrap">
            {models.length > 0 && (
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="text-xs px-2 py-1.5 rounded-lg cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
                title="Which model"
              >
                <option value="">Default</option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                    {m.download_gb ? ` · ${m.download_gb} GB` : ''}
                  </option>
                ))}
              </select>
            )}

            {kind === 'audio' && (
              <>
                <select
                  value={audioMode}
                  onChange={(e) => setAudioMode(e.target.value as 'speech' | 'music')}
                  className="text-xs px-2 py-1.5 rounded-lg cursor-pointer"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                >
                  <option value="music">Music / sound</option>
                  <option value="speech">Speech</option>
                </select>
                {audioMode === 'music' && (
                  <label
                    className="flex items-center gap-1.5 text-xs"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  >
                    {seconds}s
                    <input
                      type="range"
                      min={3}
                      max={capabilities?.audio.max_seconds ?? 30}
                      value={seconds}
                      onChange={(e) => setSeconds(parseInt(e.target.value))}
                      className="w-24 cursor-pointer accent-[var(--color-accent)]"
                    />
                  </label>
                )}
              </>
            )}

            {kind === 'video' && (
              <label
                className="flex items-center gap-1.5 text-xs"
                style={{ color: 'var(--color-text-tertiary)' }}
              >
                {frames} frames
                <input
                  type="range"
                  min={8}
                  max={capabilities?.video.max_frames ?? 32}
                  step={8}
                  value={frames}
                  onChange={(e) => setFrames(parseInt(e.target.value))}
                  className="w-24 cursor-pointer accent-[var(--color-accent)]"
                />
              </label>
            )}

            <button
              onClick={() => void submit()}
              disabled={!prompt.trim() || starting || !!unavailable}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer disabled:opacity-40 disabled:cursor-default ml-auto"
              style={{ background: 'var(--color-accent)', color: 'white' }}
            >
              <Play size={12} /> Generate
            </button>
          </div>
          <p className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
            {active.expect}
          </p>
        </div>

        {/* Jobs */}
        <div className="flex flex-col gap-2">
          {jobs.length === 0 && (
            <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              Nothing generated yet.
            </p>
          )}
          {jobs.map((job) => (
            <div
              key={job.id}
              className="rounded-xl px-3 py-2.5"
              style={{
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
              }}
            >
              <div className="flex items-start gap-2">
                <div className="flex-1 min-w-0">
                  <div
                    className="text-xs truncate"
                    style={{ color: 'var(--color-text)' }}
                    title={job.prompt}
                  >
                    {job.prompt}
                  </div>
                  <div
                    className="flex items-center gap-2 mt-0.5 text-[11px]"
                    style={{ color: 'var(--color-text-tertiary)' }}
                  >
                    <StatusPill job={job} />
                    <span>{job.kind}</span>
                    {job.elapsed_seconds != null && (
                      <span className="flex items-center gap-1">
                        <Clock size={9} />
                        {job.elapsed_seconds < 60
                          ? `${Math.round(job.elapsed_seconds)}s`
                          : `${Math.floor(job.elapsed_seconds / 60)}m ${Math.round(job.elapsed_seconds % 60)}s`}
                      </span>
                    )}
                    {!!job.queue_position && <span>#{job.queue_position + 1} in queue</span>}
                  </div>
                  {job.detail && (job.status === 'running' || job.status === 'queued') && (
                    <div
                      className="text-[11px] mt-1"
                      style={{ color: 'var(--color-text-secondary)' }}
                    >
                      {job.detail}
                    </div>
                  )}
                  {job.error && (
                    <div className="text-[11px] mt-1" style={{ color: 'var(--color-error)' }}>
                      {job.error}
                    </div>
                  )}
                </div>

                {(job.status === 'running' || job.status === 'queued') && (
                  <button
                    onClick={async () => {
                      await cancelGeneration(job.id);
                      void refresh();
                    }}
                    className="p-1 rounded cursor-pointer shrink-0"
                    style={{ color: 'var(--color-text-tertiary)' }}
                    title="Cancel"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>

              {job.progress != null &&
                (job.status === 'running' || job.status === 'queued') && (
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

              <JobResult job={job} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
