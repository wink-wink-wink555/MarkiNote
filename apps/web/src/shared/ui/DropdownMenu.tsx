import {
  type KeyboardEvent,
  type Ref,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';

export interface DropdownMenuItem {
  id: string;
  label: ReactNode;
  icon?: ReactNode;
  className?: string;
  disabled?: boolean;
  onSelect: () => void;
}

interface DropdownMenuProps {
  label: string;
  trigger: ReactNode;
  items: readonly DropdownMenuItem[];
  align?: 'start' | 'end';
  disabled?: boolean;
  className?: string;
  triggerClassName?: string;
  menuClassName?: string;
  buttonRef?: Ref<HTMLButtonElement>;
}

interface MenuPosition {
  left: number;
  top: number;
}

const VIEWPORT_GUTTER = 8;
const TRIGGER_GAP = 6;
const TABBABLE_SELECTOR = [
  'a[href]',
  'button:not(:disabled)',
  'input:not(:disabled)',
  'select:not(:disabled)',
  'textarea:not(:disabled)',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * A compact, portal-backed action menu.
 *
 * Keeping the menu in `document.body` avoids clipping inside scrollable file
 * lists. Focus restoration happens before an item's action runs, so a dialog
 * opened by that action can capture and later restore focus to the trigger.
 */
export function DropdownMenu({
  label,
  trigger,
  items,
  align = 'start',
  disabled = false,
  className = '',
  triggerClassName = '',
  menuClassName = '',
  buttonRef,
}: DropdownMenuProps) {
  const triggerId = useId();
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const initialFocusPending = useRef(false);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition | null>(null);
  const [activeIndex, setActiveIndex] = useState(-1);
  const setTriggerRef = useCallback((node: HTMLButtonElement | null) => {
    triggerRef.current = node;
    if (typeof buttonRef === 'function') buttonRef(node);
    else if (buttonRef) buttonRef.current = node;
  }, [buttonRef]);

  const positionMenu = useCallback(() => {
    const triggerElement = triggerRef.current;
    const menuElement = menuRef.current;
    if (!triggerElement || !menuElement) return;

    const triggerRect = triggerElement.getBoundingClientRect();
    const menuRect = menuElement.getBoundingClientRect();
    const availableWidth = Math.max(0, window.innerWidth - VIEWPORT_GUTTER * 2);
    const availableHeight = Math.max(0, window.innerHeight - VIEWPORT_GUTTER * 2);
    const menuWidth = Math.min(menuRect.width, availableWidth);
    const menuHeight = Math.min(menuRect.height, availableHeight);

    const preferredLeft = align === 'end'
      ? triggerRect.right - menuWidth
      : triggerRect.left;
    const left = Math.min(
      Math.max(preferredLeft, VIEWPORT_GUTTER),
      Math.max(VIEWPORT_GUTTER, window.innerWidth - menuWidth - VIEWPORT_GUTTER),
    );

    const below = triggerRect.bottom + TRIGGER_GAP;
    const above = triggerRect.top - menuHeight - TRIGGER_GAP;
    const top = below + menuHeight <= window.innerHeight - VIEWPORT_GUTTER
      ? below
      : above >= VIEWPORT_GUTTER
        ? above
        : Math.min(
          Math.max(below, VIEWPORT_GUTTER),
          Math.max(VIEWPORT_GUTTER, window.innerHeight - menuHeight - VIEWPORT_GUTTER),
        );

    setPosition({ left, top });
  }, [align]);

  const closeAndRestoreFocus = useCallback(() => {
    setOpen(false);
    setPosition(null);
    initialFocusPending.current = false;
    triggerRef.current?.focus();
  }, []);

  const moveFocusFromTrigger = (reverse: boolean) => {
    const triggerElement = triggerRef.current;
    if (!triggerElement) return;
    const candidates = [...document.querySelectorAll<HTMLElement>(TABBABLE_SELECTOR)]
      .filter((element) => (
        !element.hidden
        && element.getAttribute('aria-hidden') !== 'true'
        && !element.closest('[inert]')
        && !menuRef.current?.contains(element)
      ));
    const triggerIndex = candidates.indexOf(triggerElement);
    const target = candidates[triggerIndex + (reverse ? -1 : 1)];
    if (target) target.focus();
    else triggerElement.blur();
  };

  const enabledIndexes = items.flatMap((item, index) => item.disabled ? [] : [index]);
  const openMenu = (edge: 'first' | 'last') => {
    const nextIndex = edge === 'last' ? enabledIndexes.at(-1) : enabledIndexes[0];
    setActiveIndex(nextIndex ?? -1);
    setPosition(null);
    initialFocusPending.current = true;
    setOpen(true);
  };

  useLayoutEffect(() => {
    if (!open) return;
    positionMenu();
  }, [open, positionMenu]);

  useLayoutEffect(() => {
    if (!open || !position || !initialFocusPending.current) return;
    initialFocusPending.current = false;
    const target = activeIndex >= 0
      ? menuRef.current?.querySelector<HTMLButtonElement>(`[data-menu-index="${activeIndex}"]`)
      : menuRef.current;
    target?.focus();
  }, [activeIndex, open, position]);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) return;
      if (!menuRef.current?.contains(event.target) && !triggerRef.current?.contains(event.target)) {
        closeAndRestoreFocus();
      }
    };
    document.addEventListener('pointerdown', closeOutside);
    window.addEventListener('resize', positionMenu);
    document.addEventListener('scroll', positionMenu, true);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      window.removeEventListener('resize', positionMenu);
      document.removeEventListener('scroll', positionMenu, true);
    };
  }, [closeAndRestoreFocus, open, positionMenu]);

  const navigate = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeAndRestoreFocus();
      return;
    }
    if (event.key === 'Tab') {
      event.preventDefault();
      setOpen(false);
      setPosition(null);
      initialFocusPending.current = false;
      // The menu is portaled to document.body, so explicitly continue from
      // the trigger's place in the page rather than from the portal subtree.
      moveFocusFromTrigger(event.shiftKey);
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    if (!enabledIndexes.length) return;
    event.preventDefault();
    const currentEnabledIndex = enabledIndexes.indexOf(activeIndex);
    const nextEnabledIndex = event.key === 'Home' ? 0
      : event.key === 'End' ? enabledIndexes.length - 1
        : event.key === 'ArrowDown' ? (currentEnabledIndex + 1) % enabledIndexes.length
          : (currentEnabledIndex - 1 + enabledIndexes.length) % enabledIndexes.length;
    const nextIndex = enabledIndexes[nextEnabledIndex]!;
    setActiveIndex(nextIndex);
    menuRef.current?.querySelector<HTMLButtonElement>(`[data-menu-index="${nextIndex}"]`)?.focus();
  };

  const menu = open ? createPortal(
    <div
      ref={menuRef}
      id={menuId}
      role="menu"
      data-modal-exempt="true"
      aria-labelledby={triggerId}
      tabIndex={-1}
      className={`menu-popover menu-popover-portal ${align === 'end' ? 'align-right' : ''} ${menuClassName}`.trim()}
      style={{
        position: 'fixed',
        left: position?.left ?? 0,
        right: 'auto',
        top: position?.top ?? 0,
        visibility: position ? 'visible' : 'hidden',
      }}
      onKeyDown={navigate}
      onBlurCapture={() => {
        window.setTimeout(() => {
          const active = document.activeElement;
          if (active && !menuRef.current?.contains(active) && active !== triggerRef.current) {
            setOpen(false);
            setPosition(null);
          }
        }, 0);
      }}
    >
      {items.map((item, index) => (
        <button
          key={item.id}
          type="button"
          role="menuitem"
          data-menu-index={index}
          tabIndex={!item.disabled && index === activeIndex ? 0 : -1}
          className={item.className}
          disabled={item.disabled}
          onFocus={() => setActiveIndex(index)}
          onClick={() => {
            closeAndRestoreFocus();
            item.onSelect();
          }}
        >
          {item.icon ? <span className="menu-item-icon" aria-hidden="true">{item.icon}</span> : null}
          <span>{item.label}</span>
        </button>
      ))}
    </div>,
    document.body,
  ) : null;

  return <div className={`dropdown-menu action-menu ${className}`.trim()}>
    <button
      ref={setTriggerRef}
      id={triggerId}
      type="button"
      className={`dropdown-menu-trigger ${triggerClassName}`.trim()}
      aria-label={label}
      aria-haspopup="menu"
      aria-expanded={open}
      aria-controls={open ? menuId : undefined}
      disabled={disabled}
      onClick={() => {
        if (open) closeAndRestoreFocus();
        else openMenu('first');
      }}
      onKeyDown={(event) => {
        if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
        event.preventDefault();
        openMenu(event.key === 'ArrowUp' ? 'last' : 'first');
      }}
    >
      {trigger}
    </button>
    {menu}
  </div>;
}
