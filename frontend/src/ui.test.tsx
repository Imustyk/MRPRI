import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RequestPanel } from "./ui";
import type { RequestState } from "./hooks";

function makeState(over: Partial<RequestState<string>>): RequestState<string> {
  return {
    data: null,
    dataKey: null,
    key: "new params",
    loading: false,
    error: null,
    stale: false,
    reload: vi.fn(),
    ...over,
  };
}

describe("RequestPanel", () => {
  it("announces loading with the requested parameters", () => {
    render(
      <RequestPanel state={makeState({ loading: true })} describe={(k) => k}>
        {(data) => <p>{data}</p>}
      </RequestPanel>,
    );
    // One of the live regions is the spinner's; find the announcement among them.
    const texts = screen.getAllByRole("status").map((el) => el.textContent ?? "").join(" ");
    expect(texts).toContain("new params");
    expect(texts).toContain("Loading");
  });

  it("hides results behind an error with a retry, no old data as the answer", async () => {
    const reload = vi.fn();
    const user = userEvent.setup();
    let children = 0;
    render(
      <RequestPanel
        state={makeState({ error: "boom", data: "old", dataKey: "old params", loading: false, reload })}
        describe={(k) => k}
      >
        {() => {
          children += 1;
          return <p>result</p>;
        }}
      </RequestPanel>,
    );
    expect(screen.getByText("boom")).toBeTruthy();
    expect(screen.queryByText("result")).toBeNull();
    expect(children).toBe(0);
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("shows an explicit updating marker naming both parameter sets while stale", () => {
    render(
      <RequestPanel
        state={makeState({ data: "old result", dataKey: "old params", loading: true, stale: true })}
        describe={(k) => k}
      >
        {(data) => <p>{data}</p>}
      </RequestPanel>,
    );
    expect(screen.getByText("old result")).toBeTruthy();
    const banner = document.querySelector(".stale-note")!;
    expect(banner.textContent).toContain("old params");
    expect(banner.textContent).toContain("new params");
  });

  it("renders the empty state for an empty payload instead of an empty chart", () => {
    render(
      <RequestPanel
        state={makeState({ data: "x", dataKey: "new params" })}
        describe={(k) => k}
        isEmpty={() => true}
        emptyTitle="Nothing here"
        emptyHint="Try other filters"
      >
        {() => <p>result</p>}
      </RequestPanel>,
    );
    expect(screen.getByText("Nothing here")).toBeTruthy();
    expect(screen.queryByText("result")).toBeNull();
  });

  it("renders children with the payload once ready", () => {
    render(
      <RequestPanel state={makeState({ data: "fresh", dataKey: "new params" })} describe={(k) => k}>
        {(data) => <p>{data}</p>}
      </RequestPanel>,
    );
    expect(screen.getByText("fresh")).toBeTruthy();
    const texts = screen.getAllByRole("status").map((el) => el.textContent ?? "").join(" ");
    expect(texts).toContain("new params");
  });
});
