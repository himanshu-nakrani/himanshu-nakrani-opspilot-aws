import React, { useMemo } from 'react';
import { Incident } from '../types';
import { CLASSIFICATION_ORDER, classificationTone, statusBadge } from '../lib/badges';
import { humanize } from '../lib/format';
import { eyebrow, focusRing } from '../ui/styles';

interface IncidentBreakdownProps {
  incidents: Incident[];
  activeClass: string;
  onSelectClass: (cls: string) => void;
}

/**
 * Root-cause mix and outcome counts computed from the loaded incidents.
 * Clicking a class row filters the stream.
 */
export const IncidentBreakdown: React.FC<IncidentBreakdownProps> = ({ incidents, activeClass, onSelectClass }) => {
  const { byClass, byStatus, total } = useMemo(() => {
    const cls = new Map<string, number>();
    const st = new Map<string, number>();
    for (const inc of incidents) {
      const c = inc.classification ?? 'unclassified';
      cls.set(c, (cls.get(c) ?? 0) + 1);
      st.set(inc.status, (st.get(inc.status) ?? 0) + 1);
    }
    const ordered = [
      ...CLASSIFICATION_ORDER.map((c) => [c, cls.get(c) ?? 0] as const),
      ...(cls.has('unclassified') ? [['unclassified', cls.get('unclassified') ?? 0] as const] : []),
    ];
    const statuses = Array.from(st.entries()).sort((a, b) => b[1] - a[1]);
    return { byClass: ordered, byStatus: statuses, total: incidents.length };
  }, [incidents]);

  return (
    <section aria-labelledby="breakdown-heading">
      <div className="flex items-baseline justify-between">
        <h2 id="breakdown-heading" className={eyebrow}>
          Root-cause mix
        </h2>
        <span className="font-mono text-2xs text-ink-500 tnum">n = {total}</span>
      </div>

      {/* Stacked share bar */}
      <div className="mt-3 flex h-2 rounded-sm overflow-hidden bg-ink-800" aria-hidden="true">
        {total > 0 &&
          byClass
            .filter(([, n]) => n > 0)
            .map(([c, n]) => (
              <span
                key={c}
                className={`${classificationTone(c === 'unclassified' ? null : (c as Incident['classification'])).swatch} h-full border-r border-ink-950 last:border-r-0`}
                style={{ width: `${(n / total) * 100}%` }}
              />
            ))}
      </div>

      <ul className="mt-3 -mx-2">
        {byClass.map(([c, n]) => {
          const filterable = c !== 'unclassified';
          const active = activeClass === c;
          const tone = classificationTone(filterable ? (c as Incident['classification']) : null);
          const share = total ? Math.round((n / total) * 100) : 0;
          const content = (
            <>
              <span className={`w-2 h-2 rounded-sm shrink-0 ${tone.swatch}`} aria-hidden="true" />
              <span className={`flex-1 text-left capitalize ${n === 0 ? 'text-ink-500' : 'text-ink-200'}`}>{humanize(c)}</span>
              <span className="font-mono text-2xs text-ink-500 tnum w-9 text-right">{share}%</span>
              <span className={`font-mono text-xs tnum w-6 text-right ${n === 0 ? 'text-ink-600' : 'text-ink-100'}`}>{n}</span>
            </>
          );
          return (
            <li key={c}>
              {filterable ? (
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() => onSelectClass(active ? 'all' : c)}
                  title={active ? 'Clear filter' : `Show only ${humanize(c)}`}
                  className={`w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-[13px] transition-colors duration-150 ${focusRing} ${
                    active ? 'bg-ink-800' : 'hover:bg-ink-850'
                  }`}
                >
                  {content}
                </button>
              ) : (
                <div className="flex items-center gap-2.5 px-2 py-1.5 text-[13px]">{content}</div>
              )}
            </li>
          );
        })}
      </ul>

      {byStatus.length > 0 && (
        <>
          <h3 className={`${eyebrow} mt-6`}>Outcomes</h3>
          <ul className="mt-2 grid grid-cols-2 gap-px rounded-md overflow-hidden border border-ink-800 bg-ink-800">
            {byStatus.map(([s, n]) => {
              const b = statusBadge(s);
              const Icon = b.icon;
              return (
                <li key={s} className="bg-ink-900 px-3 py-2.5">
                  <span className={`flex items-center gap-1.5 text-2xs ${b.text}`}>
                    <Icon className="w-3 h-3" aria-hidden="true" />
                    {b.label}
                  </span>
                  <span className="block mt-1 text-lg font-light tracking-[-0.02em] text-ink-50 tnum leading-none">{n}</span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
};
