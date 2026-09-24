import { useEffect, useRef, useState } from 'react';
import { sound } from '../../lib/sound';

/**
 * A chamfered console panel, with framing brackets and a sweep on hover.
 *
 * The brackets are four real elements rather than pseudo-elements because
 * ::before and ::after are already spent on the bezel edge and the sweep, and
 * a corner that animates independently needs something to animate.
 */
export function ConsolePanel({
  children,
  className = '',
  brackets = true,
  audible = true,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & {
  brackets?: boolean;
  /** Set false for panels that are not themselves interactive. */
  audible?: boolean;
}) {
  return (
    <div
      className={`console-panel ${className}`}
      onMouseEnter={audible ? () => sound.play('hover') : undefined}
      {...rest}
    >
      {brackets && (
        <div className="console-brackets" aria-hidden="true">
          <span className="bracket bracket-tl" />
          <span className="bracket bracket-tr" />
          <span className="bracket bracket-bl" />
          <span className="bracket bracket-br" />
        </div>
      )}
      {children}
    </div>
  );
}

// Glyphs a value cycles through before it settles. Deliberately the shapes a
// readout could plausibly show, so the scramble looks like a value resolving
// rather than like corruption.
const GLYPHS = '0123456789ABCDEF<>/\\|#%';

/**
 * A value that resolves rather than appearing.
 *
 * Each character flickers through candidates and locks left to right, which
 * is what a decoder looks like. Bounded hard: `STEPS` frames at ~34ms is
 * about a third of a second, and a readout that takes longer than that to
 * settle is a readout you cannot read.
 *
 * Respects prefers-reduced-motion by rendering the value immediately — this
 * is exactly the sort of effect that a vestibular disorder makes unusable.
 */
export function Decode({
  value,
  className = '',
  chirp = false,
}: {
  value: string;
  className?: string;
  /** Play a blip when the value settles. Off by default — a screen full of
   *  readouts all chirping at once is noise, not feedback. */
  chirp?: boolean;
}) {
  const [shown, setShown] = useState(value);
  const [busy, setBusy] = useState(false);
  const previous = useRef(value);

  useEffect(() => {
    if (previous.current === value) return;
    previous.current = value;

    const reduced =
      typeof matchMedia === 'function' &&
      matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) {
      setShown(value);
      return;
    }

    const STEPS = 9;
    let frame = 0;
    setBusy(true);
    const timer = setInterval(() => {
      frame += 1;
      // How much of the string has locked, left to right.
      const locked = Math.floor((frame / STEPS) * value.length);
      setShown(
        value
          .split('')
          .map((ch, i) =>
            i < locked || ch === ' '
              ? ch
              : GLYPHS[Math.floor(Math.random() * GLYPHS.length)],
          )
          .join(''),
      );
      if (frame >= STEPS) {
        clearInterval(timer);
        setShown(value);
        setBusy(false);
        if (chirp) sound.play('blip');
      }
    }, 34);

    return () => {
      clearInterval(timer);
      // Never leave a half-scrambled value on screen if this unmounts.
      setShown(value);
      setBusy(false);
    };
  }, [value, chirp]);

  return (
    <span className={`${className} ${busy ? 'decoding' : ''}`.trim()}>
      {shown}
    </span>
  );
}
