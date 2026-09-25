import { useEffect, useState } from 'react';
import { FileText, Image as ImageIcon, AlertCircle } from 'lucide-react';
import { attachmentPreviewUrl } from '../../lib/api';
import type { MessageAttachment } from '../../types';

/**
 * What was attached to a message, shown under it in the transcript.
 *
 * Image previews are fetched rather than linked. The server requires a Bearer
 * token and an `<img src>` cannot carry one, so pointing the tag straight at
 * the endpoint would 401 and render as a broken image. Fetch through apiFetch,
 * turn the blob into an object URL, and revoke it on unmount.
 *
 * Attachments expire after an hour, and an exported conversation carries only
 * metadata — the bytes stayed on the machine that received them. Both cases
 * land here as "no preview", which is why a missing image is a normal state
 * with an icon rather than an error.
 */
function Thumbnail({ attachment }: { attachment: MessageAttachment }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (attachment.kind !== 'image') return;
    let revoked = false;
    let objectUrl: string | null = null;

    attachmentPreviewUrl(attachment.id)
      .then((next) => {
        if (revoked) {
          if (next) URL.revokeObjectURL(next);
          return;
        }
        objectUrl = next;
        if (next) setUrl(next);
        else setFailed(true);
      })
      .catch(() => !revoked && setFailed(true));

    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachment.id, attachment.kind]);

  if (attachment.kind !== 'image' || failed) return null;
  if (!url) {
    return (
      <div
        className="w-full h-24 rounded-lg animate-pulse"
        style={{ background: 'var(--color-bg-tertiary)' }}
      />
    );
  }
  return (
    <img
      src={url}
      alt={attachment.filename}
      className="w-full max-h-48 object-contain rounded-lg"
      style={{ background: 'var(--color-bg-tertiary)' }}
    />
  );
}

export function AttachmentChips({
  attachments,
}: {
  attachments: MessageAttachment[];
}) {
  if (!attachments.length) return null;

  const images = attachments.filter((a) => a.kind === 'image');
  const documents = attachments.filter((a) => a.kind !== 'image');

  return (
    <div className="flex flex-col gap-1.5 mt-2">
      {images.map((attachment) => (
        <div key={attachment.id} className="flex flex-col gap-1">
          <Thumbnail attachment={attachment} />
          <span
            className="flex items-center gap-1.5 text-[11px]"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            <ImageIcon size={11} />
            {attachment.filename}
          </span>
        </div>
      ))}

      {documents.map((attachment) => (
        <span
          key={attachment.id}
          className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] self-start"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-secondary)',
          }}
          title={attachment.notes?.length ? attachment.notes.join(' ') : undefined}
        >
          {attachment.error ? (
            <AlertCircle size={11} style={{ color: 'var(--color-error)' }} />
          ) : (
            <FileText size={11} style={{ color: 'var(--color-accent)' }} />
          )}
          <span className="max-w-[220px] truncate">{attachment.filename}</span>
          {attachment.truncated && (
            // The model saw part of this file. Saying so here is the only
            // place the reader can find out after the fact.
            <span style={{ color: 'var(--color-text-tertiary)' }}>· shortened</span>
          )}
        </span>
      ))}
    </div>
  );
}
