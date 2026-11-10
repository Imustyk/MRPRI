import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router-dom";
import Tenders, { readTenderFilters } from "./Tenders";
import type { Tender } from "../api";

const PAGE = 40;

function jsonResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    text: async () => JSON.stringify(data),
  } as unknown as Response;
}

const tenderRow: Partial<Tender> = {
  tender_id: "ocds-t1",
  ocid: "ocds-t1",
  title: "Road repairs",
  buyer_name: "City Hall",
  winner_name: "ACME",
  award_total_mdl: 1000,
  n_bidders: 3,
  risk_score: 99.1,
  risk_level: "critical",
  n_models_flagging: 3,
};

function LocationProbe() {
  const [params] = useSearchParams();
  return <div data-testid="search">{params.toString()}</div>;
}

function renderTenders(search: string) {
  return render(
    <MemoryRouter initialEntries={[`/tenders${search}`]}>
      <Routes>
        <Route
          path="/tenders"
          element={
            <>
              <Tenders />
              <LocationProbe />
            </>
          }
        />
        <Route path="/tenders/:id" element={<p>detail view</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("readTenderFilters (URL validation)", () => {
  it("keeps sane values", () => {
    const f = readTenderFilters(new URLSearchParams("q=abc&level=high&min=40&offset=80"));
    expect(f).toEqual({ q: "abc", level: "high", procedure: "", minRisk: 40, offset: 80 });
  });

  it("rejects an unknown risk band", () => {
    expect(readTenderFilters(new URLSearchParams("level=xyz")).level).toBe("");
    expect(readTenderFilters(new URLSearchParams("level=HIGH")).level).toBe("");
  });

  it("snaps the percentile to 0–95 in steps of 5 and floors junk to 0", () => {
    expect(readTenderFilters(new URLSearchParams("min=12")).minRisk).toBe(10);
    expect(readTenderFilters(new URLSearchParams("min=120")).minRisk).toBe(95);
    expect(readTenderFilters(new URLSearchParams("min=-10")).minRisk).toBe(0);
    expect(readTenderFilters(new URLSearchParams("min=abc")).minRisk).toBe(0);
    expect(readTenderFilters(new URLSearchParams("")).minRisk).toBe(0);
  });

  it("floors the offset to a whole page and clears junk", () => {
    expect(readTenderFilters(new URLSearchParams("offset=45")).offset).toBe(PAGE);
    expect(readTenderFilters(new URLSearchParams("offset=abc")).offset).toBe(0);
    expect(readTenderFilters(new URLSearchParams("offset=-40")).offset).toBe(0);
    expect(readTenderFilters(new URLSearchParams("")).offset).toBe(0);
  });
});

describe("Tenders URL state", () => {
  it("normalises invalid parameters in the address bar", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/stats")) return jsonResponse({ procedure_counts: {} });
      return jsonResponse({ total: 80, items: [tenderRow] });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderTenders("?level=bogus&min=abc&offset=xyz");
    const search = await screen.findByTestId("search");
    await waitFor(() => expect(search.textContent).toBe(""));
    // No invalid parameters survive into history (normalisation uses replace).
    expect(search.textContent).not.toContain("level=bogus");
    expect(search.textContent).not.toContain("min=abc");
  });

  it("snaps a foreign but numeric parameter instead of dropping the link", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/stats")) return jsonResponse({ procedure_counts: {} });
      return jsonResponse({ total: 80, items: [tenderRow] });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderTenders("?level=high&min=12&offset=45");
    const search = await screen.findByTestId("search");
    await waitFor(() => expect(search.textContent).toContain("min=10"));
    expect(search.textContent).toContain("offset=40");
    expect(search.textContent).toContain("level=high");
  });

  it("clears the page offset whenever a filter changes", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/stats")) return jsonResponse({ procedure_counts: {} });
      return jsonResponse({ total: 80, items: [tenderRow] });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderTenders("?offset=40");
    const search = await screen.findByTestId("search");
    await waitFor(() => expect(search.textContent).toContain("offset=40"));
    fireEvent.change(screen.getByLabelText("Priority band"), { target: { value: "high" } });
    await waitFor(() => expect(search.textContent).toContain("level=high"));
    expect(search.textContent).not.toContain("offset=");
  });

  it("pushes a page change so Back steps through pages", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/stats")) return jsonResponse({ procedure_counts: {} });
      return jsonResponse({ total: 120, items: [tenderRow] });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderTenders("");
    const search = await screen.findByTestId("search");
    await screen.findByText("Road repairs");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(search.textContent).toContain("offset=40"));
  });

  it("debounces typing into the URL instead of firing per keystroke", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/stats")) return jsonResponse({ procedure_counts: {} });
      return jsonResponse({ total: 1, items: [tenderRow] });
    });
    vi.stubGlobal("fetch", fetchMock);
    renderTenders("");
    const search = await screen.findByTestId("search");
    const input = screen.getByLabelText("Search");
    fireEvent.change(input, { target: { value: "a" } });
    fireEvent.change(input, { target: { value: "ab" } });
    // Not in the URL yet: the debounce window has not elapsed.
    expect(search.textContent).not.toContain("q=ab");
    await waitFor(() => expect(search.textContent).toContain("q=ab"), { timeout: 2000 });
    // The list request followed the URL, not the raw keystrokes.
    const calls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(calls.some((u) => u.includes("/api/tenders?") && u.includes("q=ab"))).toBe(true);
  });
});
