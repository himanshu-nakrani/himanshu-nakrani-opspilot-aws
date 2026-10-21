/** Shared class recipes so every control speaks the same visual language. */

export const focusRing =
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal-400';

const btnBase =
  'inline-flex items-center justify-center gap-1.5 rounded-md text-xs font-medium transition-colors duration-150 disabled:opacity-50 disabled:cursor-not-allowed';

export const btn = {
  primary: `${btnBase} h-8 px-3 bg-ink-50 text-ink-950 hover:bg-white ${focusRing}`,
  secondary: `${btnBase} h-8 px-3 border border-ink-800 bg-ink-900 text-ink-200 hover:text-ink-50 hover:bg-ink-850 hover:border-ink-700 ${focusRing}`,
  accent: `${btnBase} h-8 px-3 border border-signal-500/40 bg-signal-500/15 text-signal-200 hover:bg-signal-500/25 hover:text-signal-200 ${focusRing}`,
  ghost: `${btnBase} h-8 w-8 text-ink-300 hover:text-ink-50 hover:bg-ink-800 ${focusRing}`,
};

/** Small all-caps label used for section and metric headings. */
export const eyebrow = 'text-2xs font-medium uppercase tracking-[0.1em] text-ink-400';

export const chip = 'inline-flex items-center gap-1 px-1.5 py-px text-2xs font-medium rounded border';

/** Larger status/attribute badge for detail views. Pair with a tone from lib/badges. */
export const badge = 'inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md border';

export const panel = 'rounded-lg border border-ink-800 bg-ink-900';
