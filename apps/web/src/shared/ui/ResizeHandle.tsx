import { type PointerEvent as ReactPointerEvent, useRef } from 'react';

interface Props {
  label: string;
  orientation?: 'vertical' | 'horizontal';
  direction?: 1 | -1;
  value: number;
  minimum: number;
  maximum: number;
  valueText?: string;
  onResize: (delta: number) => void;
  onResizeEnd?: () => void;
}

export function ResizeHandle({ label, orientation = 'vertical', direction = 1, value, minimum, maximum, valueText, onResize, onResizeEnd }: Props) {
  const previousCoordinate = useRef<number | null>(null);
  const activePointer = useRef<number | null>(null);
  const coordinate = (event: ReactPointerEvent<HTMLDivElement>) => orientation === 'vertical' ? event.clientX : event.clientY;
  const finishPointerResize = (pointerId: number) => {
    if (activePointer.current !== pointerId) return;
    activePointer.current = null;
    previousCoordinate.current = null;
    onResizeEnd?.();
  };

  return <div
    className={`resize-handle resize-${orientation}`}
    role="separator"
    aria-label={label}
    aria-orientation={orientation}
    aria-valuemin={minimum}
    aria-valuemax={maximum}
    aria-valuenow={Math.round(value)}
    aria-valuetext={valueText}
    tabIndex={0}
    onPointerDown={(event) => {
      if (event.button !== 0) return;
      activePointer.current = event.pointerId;
      previousCoordinate.current = coordinate(event);
      event.currentTarget.setPointerCapture(event.pointerId);
      event.preventDefault();
    }}
    onPointerMove={(event) => {
      if (activePointer.current !== event.pointerId || previousCoordinate.current === null || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
      const nextCoordinate = coordinate(event);
      onResize((nextCoordinate - previousCoordinate.current) * direction);
      previousCoordinate.current = nextCoordinate;
    }}
    onPointerUp={(event) => {
      if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      finishPointerResize(event.pointerId);
    }}
    onPointerCancel={(event) => finishPointerResize(event.pointerId)}
    onLostPointerCapture={(event) => finishPointerResize(event.pointerId)}
    onKeyDown={(event) => {
      const negativeKey = orientation === 'vertical' ? 'ArrowLeft' : 'ArrowUp';
      const positiveKey = orientation === 'vertical' ? 'ArrowRight' : 'ArrowDown';
      if (event.key !== negativeKey && event.key !== positiveKey) return;
      event.preventDefault();
      onResize((event.key === positiveKey ? 12 : -12) * direction);
      onResizeEnd?.();
    }}
  />;
}
