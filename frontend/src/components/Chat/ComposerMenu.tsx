import { useEffect, useRef, useState } from 'react';
import {
  Plus,
  Paperclip,
  Image as ImageIcon,
  Music,
  Film,
  X,
} from 'lucide-react';

/**
 * The "+" in the composer: attach something, or make something.
 *
 * One menu for both because from where the user sits they are the same
 * gesture — "bring a thing into this conversation". Upload sits above a
 * divider, the three generators below, matching the shape people already
 * know from other assistants.
 *
 * Generation is offered here rather than only on the Create page so that a
 * generated image lands in the conversation it was asked for, next to the
 * sentence that asked.
 */

export type CreateKind = 'image' | 'audio' | 'video';

interface Props {
  onUpload: () => void;
  onCreate: (kind: CreateKind) => void;
  /** Kinds this install cannot do, with the reason, so they can say why. */
  unavailable?: Partial<Record<CreateKind, string>>;
  disabled?: boolean;
}

const CREATE_ITEMS: Array<{
  kind: CreateKind;
  label: string;
  icon: typeof ImageIcon;
}> = [
  { kind: 'image', label: 'Create image', icon: ImageIcon },
  { kind: 'audio', label: 'Create music', icon: Music },
  { kind: 'video', label: 'Create video', icon: Film },
];

export function ComposerMenu({ onUpload, onCreate, unavailable, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on an outside click or Escape. Both, because a menu that traps the
  // pointer is worse than one that never opened.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const item = (
    key: string,
    label: string,
    Icon: typeof ImageIcon,
    onClick: () => void,
    reason?: string,
  ) => (
    <button
      key={key}
      onClick={() => {
        if (reason) return;
        setOpen(false);
        onClick();
      }}
      disabled={!!reason}
      title={reason}
      className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-left
        transition-colors cursor-pointer bg-transparent hover:bg-bg-secondary
        disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
      style={{ color: 'var(--color-text)' }}
    >
      <Icon size={16} style={{ color: 'var(--color-text-secondary)' }} />
      {label}
    </button>
  );

  return (
    <div className="relative shrink-0" ref={rootRef}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        className="p-1.5 rounded-full transition-colors cursor-pointer disabled:opacity-50"
        style={{
          background: open ? 'var(--color-bg-tertiary)' : 'transparent',
          color: 'var(--color-text-secondary)',
        }}
        title="Attach a file, or create an image, music or video"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {open ? <X size={16} /> : <Plus size={16} />}
      </button>

      {open && (
        <div
          role="menu"
          // Above the composer: the composer sits at the bottom of the window,
          // so a menu below it would open off-screen.
          className="absolute bottom-full left-0 mb-2 w-56 rounded-2xl p-1.5 z-50"
          style={{
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-lg, 0 10px 40px rgba(0,0,0,0.25))',
            backdropFilter: 'blur(var(--glass-blur, 20px))',
          }}
        >
          {item('upload', 'Upload files', Paperclip, onUpload)}

          <div
            className="my-1.5 mx-1"
            style={{ borderTop: '1px solid var(--color-border-subtle, var(--color-border))' }}
          />

          {CREATE_ITEMS.map(({ kind, label, icon }) =>
            item(kind, label, icon, () => onCreate(kind), unavailable?.[kind]),
          )}
        </div>
      )}
    </div>
  );
}
