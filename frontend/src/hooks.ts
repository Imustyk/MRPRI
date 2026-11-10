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

export type RequestState<T> = {
  /** Latest successful payload; belongs to ``dataKey``, not necessarily ``key``. */
  data: T | null;
  /** Parameter label of the payload currently held (serve as human description too). */
  dataKey: string | null;
  /** Parameters the caller is currently asking for. */
  key: string;
  loading: boolean;
  error: string | null;
  /** True while ``key`` changed but only older data is on hand — must be labelled. */
  stale: boolean;
  /** Re-run the in-flight request after an error, without a page reload. */
  reload: () => void;
};

/**
 * One independent request with unambiguous states.
 *
 * - a late response can never overwrite a newer one (the fetch is aborted and a
 *   visibility flag guards the handlers on top of that);
 * - an error is kept per request, so two requests on one page fail separately;
 * - previously loaded data survives a parameter change, but ``stale`` turns true
 *   so the caller shows it only with an explicit "updating, previous parameters"
 *   marker instead of presenting it as the answer to the new filters.
 *
 * ``key`` doubles as a human-readable description of the parameters — callers
 * pass labels such as ``"open × bids by risk"`` so the stale marker can name the
 * parameters the shown data belongs to.
 */
export function useRequest<T>(
  key: string,
  run: (signal: AbortSignal) => Promise<T>,
  enabled = true,
): RequestState<T> {
  const [state, setState] = useState<{
    data: T | null;
    dataKey: string | null;
    error: string | null;
    loading: boolean;
  }>({ data: null, dataKey: null, error: null, loading: enabled });
  const [attempt, setAttempt] = useState(0);
  const runRef = useRef(run);
  runRef.current = run;

  useEffect(() => {
    if (!enabled) {
      setState((prev) => ({ ...prev, loading: false, error: null }));
      return;
    }
    const controller = new AbortController();
    let live = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    runRef
      .current(controller.signal)
      .then((data) => {
        if (!live) return;
        setState({ data, dataKey: key, error: null, loading: false });
      })
      .catch((reason: unknown) => {
        if (!live || controller.signal.aborted) return;
        setState((prev) => ({
          ...prev,
          error: reason instanceof Error ? reason.message : String(reason),
          loading: false,
        }));
      });
    return () => {
      live = false;
      controller.abort();
    };
  }, [key, attempt, enabled]);

  return {
    ...state,
    key,
    stale: state.data !== null && state.dataKey !== key && enabled,
    reload: () => setAttempt((value) => value + 1),
  };
}
