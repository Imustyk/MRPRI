import { useCallback, useEffect, useRef, useState } from "react";

export type Box = { width: number; height: number };

/**
 * Live size of an element, via a callback ref.
 *
 * A plain ``useRef`` + ``useEffect`` would miss the element here: the network
 * page only renders its chart container after the request resolves, so the
 * effect would run once against ``null`` and never observe anything. A callback
 * ref is invoked the moment the element mounts, which is what makes a chart
 * measure itself without forcing a window-resize event.
 *
 * ``ResizeObserver`` is optional: the size is read once on attach and the
 * observer is skipped where the API is missing, so the chart still gets a
 * usable width instead of collapsing to zero.
 */
export function useMeasure<T extends HTMLElement>(): {
  ref: (el: T | null) => void;
  width: number;
  height: number;
} {
  const [box, setBox] = useState<Box>({ width: 0, height: 0 });
  const observer = useRef<ResizeObserver | null>(null);

  const detach = useCallback(() => {
    observer.current?.disconnect();
    observer.current = null;
  }, []);

  const ref = useCallback(
    (el: T | null) => {
      detach();
      if (!el) return;
      const read = () =>
        setBox({ width: Math.round(el.clientWidth), height: Math.round(el.clientHeight) });
      read();
      if (typeof ResizeObserver === "undefined") return;
      const ro = new ResizeObserver(read);
      ro.observe(el);
      observer.current = ro;
    },
    [detach],
  );

  useEffect(() => detach, [detach]);

  return { ref, width: box.width, height: box.height };
}
