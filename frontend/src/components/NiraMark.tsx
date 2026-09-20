/**
 * The Nira mark, for use inside the app.
 *
 * The same geometry as `src-tauri/icons/nira-mark.svg`, which generates every
 * icon file. Kept as a component rather than an `<img>` of that file so it
 * takes the current accent colour: the icon on your desktop is fixed orange,
 * but in the app the mark should follow the theme like everything else.
 *
 * Filled shapes rather than a stroked path, matching the source for the same
 * reason — see the comment in that file — and because `currentColor` on a
 * fill is the simplest way to let a parent recolour it.
 */
export function NiraMark({ size = 32 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 1024 1024"
      role="img"
      aria-label="Nira"
      fill="none"
    >
      {/* The diagonal first, so the stems overlap its corners. */}
      <path
        d="M 372.6 252.2 L 724.6 716.2 L 651.4 771.8 L 299.4 307.8 Z"
        fill="currentColor"
      />
      <rect x="290" y="234" width="92" height="556" rx="46" fill="currentColor" />
      <rect x="642" y="234" width="92" height="556" rx="46" fill="currentColor" />
      {/* The one point of light. Lightened rather than a second token, so it
          stays legible whatever colour the parent sets. */}
      <circle cx="688" cy="280" r="30" fill="currentColor" opacity="0.55" />
    </svg>
  );
}
