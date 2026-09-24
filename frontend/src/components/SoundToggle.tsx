import { useEffect, useState } from 'react';
import { Volume2, VolumeX } from 'lucide-react';
import { sound } from '../lib/sound';

/**
 * The off switch, where it can be found without looking for it.
 *
 * Audio that cannot be silenced in one obvious click is audio that gets the
 * whole tab muted instead, which takes the notifications with it.
 */
export function SoundToggle() {
  const [on, setOn] = useState(sound.enabled);

  useEffect(() => sound.subscribe(setOn), []);

  return (
    <button
      type="button"
      onClick={() => {
        // Unlock first: this click is a user gesture, so the confirmation
        // tone for turning sound *on* can play immediately rather than
        // arriving on the next interaction.
        sound.unlock();
        const next = !on;
        sound.setEnabled(next);
        if (next) sound.play('confirm');
      }}
      onMouseEnter={() => sound.play('hover')}
      className="hud-focusable p-2 rounded-md transition-colors cursor-pointer"
      style={{ color: on ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }}
      aria-pressed={on}
      aria-label={on ? 'Mute interface sounds' : 'Unmute interface sounds'}
      title={on ? 'Interface sounds on' : 'Interface sounds off'}
    >
      {on ? <Volume2 size={16} /> : <VolumeX size={16} />}
    </button>
  );
}
