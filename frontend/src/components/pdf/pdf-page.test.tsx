import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const getDocument = vi.fn();
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: {},
  getDocument: (...args: unknown[]) => getDocument(...args),
}));

import { PdfPage } from "./pdf-page";

afterEach(() => getDocument.mockReset());

function fakeDocument(numPages: number) {
  const render = vi.fn(() => ({ promise: Promise.resolve() }));
  const getPage = vi.fn(async () => ({
    getViewport: () => ({ width: 100, height: 140 }),
    render,
  }));
  return { numPages, getPage, destroy: vi.fn() };
}

describe("PdfPage", () => {
  it("shows an error, not a blank canvas, when the file cannot be loaded", async () => {
    getDocument.mockReturnValue({
      promise: Promise.reject(new Error("Unexpected server response (401)")),
      destroy: vi.fn(),
    });
    render(<PdfPage url="/api/v1/document-versions/x/file" pageNumber={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not display/i);
  });

  it("clamps an out-of-range page number to the last page", async () => {
    const doc = fakeDocument(3);
    getDocument.mockReturnValue({ promise: Promise.resolve(doc), destroy: vi.fn() });
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never;
    render(<PdfPage url="/api/v1/document-versions/x/file" pageNumber={99} />);
    await waitFor(() => expect(doc.getPage).toHaveBeenCalledWith(3));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
