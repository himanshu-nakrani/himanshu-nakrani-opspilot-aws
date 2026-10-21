import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Modal } from './Modal';

afterEach(cleanup);

// jsdom has no layout, so offsetParent is always null; give every element one
// so the trap's visibility filter behaves like a real browser.
Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
  configurable: true,
  get() {
    return this.parentNode;
  },
});

const renderDrawer = () =>
  render(
    <Modal isOpen onClose={() => {}} title="Agent runs" variant="drawer">
      <button type="button">Real action</button>
      <ol>
        <li><button type="button" tabIndex={0}>span selected</button></li>
        <li><button type="button" tabIndex={-1}>span roving</button></li>
      </ol>
    </Modal>
  );

describe('Modal focus trap', () => {
  it('wraps Tab from the last tabbable control, ignoring tabIndex=-1 buttons', () => {
    renderDrawer();
    const close = screen.getByRole('button', { name: 'Close dialog' });
    const lastTabbable = screen.getByRole('button', { name: 'span selected' });
    expect(document.activeElement).toBe(close);
    lastTabbable.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(close);
  });

  it('wraps Shift+Tab from the first control to the last tabbable one', () => {
    renderDrawer();
    const close = screen.getByRole('button', { name: 'Close dialog' });
    close.focus();
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'span selected' }));
  });
});
