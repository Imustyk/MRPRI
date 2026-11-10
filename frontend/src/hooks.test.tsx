import { describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRequest } from "./hooks";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function Probe({
  requestKey,
  run,
}: {
  requestKey: string;
  run: (signal: AbortSignal) => Promise<string>;
}) {
  const state = useRequest(requestKey, run);
  return (
    <div>
      <output data-testid="data">{state.data ?? ""}</output>
      <output data-testid="datakey">{state.dataKey ?? ""}</output>
      <output data-testid="stale">{String(state.stale)}</output>
      <output data-testid="error">{state.error ?? ""}</output>
      <output data-testid="loading">{String(state.loading)}</output>
      <button type="button" onClick={state.reload}>
        retry
      </button>
    </div>
  );
}

describe("useRequest", () => {
  it("moves loading → success", async () => {
    const run = vi.fn(() => Promise.resolve("payload"));
    render(<Probe requestKey="k1" run={run} />);
    expect(screen.getByTestId("loading").textContent).toBe("true");
    await screen.findByText("payload");
    expect(screen.getByTestId("loading").textContent).toBe("false");
    expect(screen.getByTestId("error").textContent).toBe("");
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("discards a late response that arrives after the parameters changed", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const { rerender } = render(<Probe requestKey="k1" run={() => first.promise} />);
    rerender(<Probe requestKey="k2" run={() => second.promise} />);
    await act(async () => {
      second.resolve("second-data");
    });
    await screen.findByText("second-data");
    // The stale first request resolves afterwards and must not win.
    await act(async () => {
      first.resolve("first-data");
    });
    expect(screen.getByTestId("data").textContent).toBe("second-data");
    expect(screen.getByTestId("datakey").textContent).toBe("k2");
  });

  it("marks prior data as stale while newer parameters are in flight", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const { rerender } = render(<Probe requestKey="k1" run={() => first.promise} />);
    await act(async () => {
      first.resolve("old-data");
    });
    await screen.findByText("old-data");
    expect(screen.getByTestId("stale").textContent).toBe("false");

    rerender(<Probe requestKey="k2" run={() => second.promise} />);
    // Newer parameters are pending: old data stays visible only as stale.
    expect(screen.getByTestId("stale").textContent).toBe("true");
    expect(screen.getByTestId("loading").textContent).toBe("true");
    expect(screen.getByTestId("data").textContent).toBe("old-data");

    await act(async () => {
      second.resolve("new-data");
    });
    await screen.findByText("new-data");
    expect(screen.getByTestId("stale").textContent).toBe("false");
    expect(screen.getByTestId("datakey").textContent).toBe("k2");
  });

  it("surfaces an error and retries in place without a reload", async () => {
    const run = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce("recovered");
    const user = userEvent.setup();
    render(<Probe requestKey="k1" run={run} />);
    await screen.findByText("boom");
    expect(screen.getByTestId("data").textContent).toBe("");
    await user.click(screen.getByRole("button", { name: "retry" }));
    await screen.findByText("recovered");
    expect(screen.getByTestId("error").textContent).toBe("");
    expect(run).toHaveBeenCalledTimes(2);
  });
});
