import { X } from 'lucide-react';
import { type PropsWithChildren, useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

interface ModalProps extends PropsWithChildren {
  open: boolean;
  title: string;
  onClose: () => void;
  size?: 'small' | 'medium' | 'large';
  dismissible?: boolean;
}

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export function Modal({ open, title, onClose, size = 'medium', dismissible = true, children }: ModalProps) {
  const { t } = useTranslation();
  const titleId = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  const dismissibleRef = useRef(dismissible);
  dismissibleRef.current = dismissible;
  useEffect(() => { closeRef.current = onClose; }, [onClose]);

  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    const backdrop = node?.parentElement;
    if (!node || !backdrop) return undefined;

    const background = [...document.body.children]
      .filter((element): element is HTMLElement => (
        element instanceof HTMLElement
        && element !== backdrop
        && !element.hasAttribute('data-modal-exempt')
      ))
      .map((element) => ({
        element,
        inert: element.getAttribute('inert'),
        ariaHidden: element.getAttribute('aria-hidden'),
      }));
    background.forEach(({ element }) => {
      element.setAttribute('inert', '');
      element.setAttribute('aria-hidden', 'true');
    });

    const isTopmost = () => [...document.querySelectorAll('.modal-backdrop')].at(-1) === backdrop;
    const focusables = () => {
      const exempt = [...document.querySelectorAll<HTMLElement>('[data-modal-exempt="true"]')]
        .flatMap((root) => [...root.querySelectorAll<HTMLElement>(focusableSelector)]);
      return [...new Set([...node.querySelectorAll<HTMLElement>(focusableSelector), ...exempt])]
        .filter((element) => (
          !element.hidden
          && element.getAttribute('aria-hidden') !== 'true'
          && !element.closest('[inert]')
        ));
    };
    let userMovedFocus = false;
    let automaticFallback: HTMLElement | null = null;
    const markFocusIntent = () => { userMovedFocus = true; };
    node.addEventListener('pointerdown', markFocusIntent, true);
    node.addEventListener('keydown', markFocusIntent, true);
    const keydown = (event: KeyboardEvent) => {
      if (!isTopmost() || event.defaultPrevented) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        if (dismissibleRef.current) closeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusables();
      if (!items.length) {
        event.preventDefault();
        node.focus();
        return;
      }
      const first = items[0]!;
      const last = items.at(-1)!;
      const current = document.activeElement;
      if (event.shiftKey && (current === first || !items.includes(current as HTMLElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (current === last || !items.includes(current as HTMLElement))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', keydown);
    const prefersInitialFocus = window.matchMedia('(pointer: fine) and (min-width: 761px)').matches;
    const focusPreferred = () => {
      if (!prefersInitialFocus || userMovedFocus) return false;
      const preferred = node.querySelector<HTMLElement>('[data-modal-initial-focus]');
      if (!preferred) return false;
      const current = document.activeElement;
      if (current === automaticFallback || current === node || !node.contains(current)) preferred.focus();
      return true;
    };
    let preferredObserver: MutationObserver | null = null;
    if (prefersInitialFocus) {
      preferredObserver = new MutationObserver(() => {
        if (focusPreferred()) preferredObserver?.disconnect();
      });
    }
    preferredObserver?.observe(node, { childList: true, subtree: true });
    const focusTimer = window.setTimeout(() => {
      if (node.contains(document.activeElement)) return;
      if (focusPreferred()) {
        preferredObserver?.disconnect();
        return;
      }
      automaticFallback = focusables()[0] ?? node;
      automaticFallback.focus();
    }, 0);

    return () => {
      window.clearTimeout(focusTimer);
      preferredObserver?.disconnect();
      node.removeEventListener('pointerdown', markFocusIntent, true);
      node.removeEventListener('keydown', markFocusIntent, true);
      document.removeEventListener('keydown', keydown);
      background.forEach(({ element, inert, ariaHidden }) => {
        if (inert === null) element.removeAttribute('inert'); else element.setAttribute('inert', inert);
        if (ariaHidden === null) element.removeAttribute('aria-hidden'); else element.setAttribute('aria-hidden', ariaHidden);
      });
      if (previous?.isConnected) previous.focus();
    };
  }, [open]);
  if (!open) return null;
  return createPortal(
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (dismissible && event.target === event.currentTarget) onClose();
    }}>
      <div className={`modal modal-${size}`} ref={dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <header className="modal-header"><h2 id={titleId}>{title}</h2><button type="button" className="icon-button" disabled={!dismissible} onClick={onClose} aria-label={t('close')}><X size={18} aria-hidden="true" /></button></header>
        {children}
      </div>
    </div>, document.body,
  );
}
