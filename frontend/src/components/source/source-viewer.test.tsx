import { render, screen, within } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makePage, makePageDetail } from "@/test/fixtures";
import { createTestClient, mockApi, respond } from "@/test/render";

vi.mock("@/components/pdf/pdf-page", () => ({
  PdfPage: ({ pageNumber }: { pageNumber: number }) => <div data-testid="pdf">pdf page {pageNumber}</div>,
}));

import { PageText } from "./page-text";
import { SheetGrid } from "./sheet-grid";
import { type Source, SourceViewer } from "./source-viewer";

afterEach(() => vi.unstubAllGlobals());

const V = ids.version;
const base: Source = { page: null, sheet: null, cellRange: null, quoteStart: null, quoteEnd: null, quote: null };

function renderViewer(fileFormat: string, source: Source | null) {
  const client = createTestClient();
  return render(
    <QueryClientProvider client={client}>
      <SourceViewer versionId={V} fileFormat={fileFormat} source={source} />
    </QueryClientProvider>,
  );
}

describe("PageText", () => {
  it("marks exactly the quote span", () => {
    render(<PageText text="Note: pay on time." start={6} end={17} />);
    expect(screen.getByText("pay on time", { selector: "mark" })).toBeInTheDocument();
  });

  it("shows no mark and the quote when offsets are unusable", () => {
    const { container } = render(<PageText text="Short" start={3} end={99} quote="the quote" />);
    expect(container.querySelector("mark")).toBeNull();
    expect(screen.getByText(/not located on the page/)).toBeInTheDocument();
    expect(screen.getByText("the quote")).toBeInTheDocument();
  });

  it("renders markup in the text literally", () => {
    const { container } = render(<PageText text="<b>bold</b>" start={null} end={null} />);
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText("<b>bold</b>")).toBeInTheDocument();
  });
});

describe("SheetGrid", () => {
  const table = {
    kind: "sheet" as const,
    first_row: 10,
    rows: [["a", "b", "c", "d"], ["e", "f", "g", "h"], ["i", "j", "k", "l"]],
  };

  it("numbers rows from first_row and highlights only the cited cells", () => {
    render(<SheetGrid table={table} range="A11:C11" />);
    expect(screen.getByRole("rowheader", { name: "10" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "12" })).toBeInTheDocument();
    const selected = document.querySelectorAll("td[aria-selected]");
    expect([...selected].map((c) => c.textContent)).toEqual(["e", "f", "g"]);
  });

  it("highlights nothing for an invalid range", () => {
    render(<SheetGrid table={table} range="nonsense" />);
    expect(document.querySelectorAll("td[aria-selected]")).toHaveLength(0);
  });
});

describe("SourceViewer", () => {
  it("says the source is not available when there is none", () => {
    renderViewer("pdf", null);
    expect(screen.getByRole("status")).toHaveTextContent("Source not available");
  });

  it("says so for a PDF row without a page", () => {
    renderViewer("pdf", base);
    expect(screen.getByRole("status")).toHaveTextContent("Source not available");
  });

  it("shows the PDF page and the marked text", async () => {
    mockApi({
      [`GET /api/v1/document-versions/${V}/pages/2`]: () =>
        respond(200, makePageDetail({ page_number: 2, text: "Note: pay on time." })),
    });
    renderViewer("pdf", { ...base, page: 2, quoteStart: 6, quoteEnd: 17, quote: "pay on time" });
    expect(screen.getByTestId("pdf")).toHaveTextContent("pdf page 2");
    expect(await screen.findByText("pay on time", { selector: "mark" })).toBeInTheDocument();
  });

  it("flags a scanned page", async () => {
    mockApi({
      [`GET /api/v1/document-versions/${V}/pages/1`]: () => respond(200, makePageDetail({ text_source: "ocr", ocr_confidence: 80 })),
    });
    renderViewer("pdf", { ...base, page: 1 });
    expect(await screen.findByText("Scanned page (OCR)")).toBeInTheDocument();
  });

  it("labels a DOCX source as text only", async () => {
    mockApi({ [`GET /api/v1/document-versions/${V}/pages/1`]: () => respond(200, makePageDetail()) });
    renderViewer("docx", { ...base, page: 1 });
    expect(await screen.findByText(/Text only/)).toBeInTheDocument();
  });

  it("maps a sheet to its page and highlights the cell range", async () => {
    const fetchMock = mockApi({
      [`GET /api/v1/document-versions/${V}/pages`]: () => respond(200, [makePage({ page_number: 1, label: "Cover" }), makePage({ page_number: 2, label: "BoQ" })]),
      [`GET /api/v1/document-versions/${V}/pages/2`]: () =>
        respond(200, makePageDetail({ page_number: 2, label: "BoQ", text: "", tables: [{ kind: "sheet", first_row: 5, rows: [["x", "y"], ["z", "w"]] }] })),
    });
    renderViewer("xlsx", { ...base, sheet: "BoQ", cellRange: "A6:B6" });
    const grid = await screen.findByRole("table");
    expect([...document.querySelectorAll("td[aria-selected]")].map((c) => c.textContent)).toEqual(["z", "w"]);
    expect(within(grid).getByRole("rowheader", { name: "6" })).toBeInTheDocument();
    const detailCall = fetchMock.mock.calls.find(([u]) => String(u).includes("/pages/2"));
    expect(String(detailCall?.[0])).toMatch(/row_from=1&row_to=26/);
  });

  it("says the source is not available when the sheet is not in the page list", async () => {
    mockApi({ [`GET /api/v1/document-versions/${V}/pages`]: () => respond(200, [makePage({ label: "Other" })]) });
    renderViewer("xlsx", { ...base, sheet: "BoQ", cellRange: "A1:B1" });
    expect(await screen.findByText("Source not available for this row.")).toBeInTheDocument();
  });
});
