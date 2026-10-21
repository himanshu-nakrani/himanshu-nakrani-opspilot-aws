import React, { useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  headerExtra?: React.ReactNode;
  footer?: React.ReactNode;
  children: React.ReactNode;
  /** center = dialog, drawer = right-hand sheet */
  variant?: 'center' | 'drawer';
  size?: 'md' | 'lg';
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input:not([disabled]), select, [tabindex]:not([tabindex="-1"])';

/**
 * Accessible overlay shared by every dialog and drawer:
 * role="dialog" + aria-modal + aria-labelledby, Esc and backdrop close,
 * focus trap, focus restore and body scroll lock.
 */
export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  description,
  icon,
  headerExtra,
  footer,
  children,
  variant = 'center',
  size = 'lg',
}) => {
  const titleId = useId();
  const descId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!isOpen) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const panel = panelRef.current;
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel)?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab' || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement
      );
      if (items.length === 0) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === firstEl || document.activeElement === panel)) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = prevOverflow;
      previouslyFocused?.focus?.();
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const isDrawer = variant === 'drawer';
  const panelClass = isDrawer
    ? 'w-full max-w-md h-full border-l motion-safe:animate-slide-in'
    : `w-full ${size === 'lg' ? 'max-w-4xl' : 'max-w-2xl'} max-h-[92vh] sm:max-h-[88vh] rounded-t-lg sm:rounded-lg border motion-safe:animate-rise-in`;

  return (
    <div
      className={`fixed inset-0 z-50 bg-ink-950/85 motion-safe:animate-fade-in flex ${
        isDrawer ? 'justify-end' : 'items-end sm:items-center justify-center sm:p-6'
      }`}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={`bg-ink-900 border-ink-700 flex flex-col shadow-[0_24px_64px_-16px_rgba(0,0,0,0.6)] overflow-hidden focus:outline-none ${panelClass}`}
      >
        <div className="px-5 py-4 border-b border-ink-800 flex items-start justify-between gap-4">
          <div className="flex items-start gap-2.5 min-w-0">
            {icon}
            <div className="min-w-0">
              <h2 id={titleId} className="text-[15px] font-semibold tracking-[-0.015em] text-ink-50">
                {title}
              </h2>
              {description && (
                <div id={descId} className="text-xs text-ink-400 mt-0.5">
                  {description}
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {headerExtra}
            <button
              type="button"
              onClick={onClose}
              aria-label="Close dialog"
              className="p-1.5 text-ink-400 hover:text-ink-50 rounded-md hover:bg-ink-800 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-signal-400"
            >
              <X className="w-5 h-5" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="p-5 sm:p-6 overflow-y-auto flex-1 space-y-6">{children}</div>

        {footer && (
          <div className="px-5 py-3 border-t border-ink-800 bg-ink-950/40 flex flex-wrap items-center justify-between gap-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
};
