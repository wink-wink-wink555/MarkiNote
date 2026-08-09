import { X } from 'lucide-react';
import { createContext, type PropsWithChildren, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { uid } from '@/shared/lib/format';

type ToastKind = 'success' | 'error' | 'info';
interface ToastItem { id: string; message: string; kind: ToastKind }
type PauseReason = 'focus' | 'pointer';
interface ToastTimer {
  handle?: number;
  remaining: number;
  startedAt: number;
  pauses: Set<PauseReason>;
}
type Notify = (message: string, kind?: ToastKind) => void;
const ToastContext = createContext<Notify>(() => undefined);

export function ToastProvider({ children }: PropsWithChildren) {
  const { t } = useTranslation();
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef(new Map<string, ToastTimer>());
  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer?.handle !== undefined) window.clearTimeout(timer.handle);
    timers.current.delete(id);
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);
  const schedule = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (!timer || timer.handle !== undefined || timer.pauses.size > 0) return;
    timer.startedAt = Date.now();
    timer.handle = window.setTimeout(() => {
      timers.current.delete(id);
      setItems((current) => current.filter((item) => item.id !== id));
    }, timer.remaining);
  }, []);
  const pause = useCallback((id: string, reason: PauseReason) => {
    const timer = timers.current.get(id);
    if (!timer) return;
    timer.pauses.add(reason);
    if (timer.handle === undefined) return;
    window.clearTimeout(timer.handle);
    timer.handle = undefined;
    timer.remaining = Math.max(0, timer.remaining - (Date.now() - timer.startedAt));
  }, []);
  const resume = useCallback((id: string, reason: PauseReason) => {
    const timer = timers.current.get(id);
    if (!timer) return;
    timer.pauses.delete(reason);
    if (timer.pauses.size > 0) return;
    if (timer.remaining <= 0) dismiss(id);
    else schedule(id);
  }, [dismiss, schedule]);
  const notify = useCallback<Notify>((message, kind = 'info') => {
    const id = uid('toast');
    setItems((current) => [...current, { id, message, kind }]);
    if (kind !== 'error') {
      const duration = kind === 'success' ? 4_500 : 6_500;
      timers.current.set(id, { remaining: duration, startedAt: Date.now(), pauses: new Set() });
      schedule(id);
    }
  }, [schedule]);
  useEffect(() => () => {
    timers.current.forEach((timer) => {
      if (timer.handle !== undefined) window.clearTimeout(timer.handle);
    });
    timers.current.clear();
  }, []);
  const value = useMemo(() => notify, [notify]);
  const region = createPortal(
    <div className="toast-region" data-modal-exempt="true">{items.map((item) => <div
      className={`toast toast-${item.kind}`}
      key={item.id}
      role={item.kind === 'error' ? 'alert' : 'status'}
      aria-atomic="true"
      onMouseEnter={() => pause(item.id, 'pointer')}
      onMouseLeave={() => resume(item.id, 'pointer')}
      onFocusCapture={() => pause(item.id, 'focus')}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) resume(item.id, 'focus');
      }}
    ><span className="toast-message">{item.message}</span><button type="button" className="toast-dismiss icon-button" onClick={() => dismiss(item.id)} aria-label={`${t('close')}: ${item.message}`}><X size={16} aria-hidden="true" /></button></div>)}</div>,
    document.body,
  );
  return <ToastContext.Provider value={value}>{children}{region}</ToastContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): Notify { return useContext(ToastContext); }
