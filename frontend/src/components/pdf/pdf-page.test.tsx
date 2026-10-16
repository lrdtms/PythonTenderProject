import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const getDocument = vi.fn();
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: {},
  getDocument: (...args: unknown[]) => getDocument(...args),
}));

import { PdfPage } from "./pdf-page";

const URL_ = "/api/v1/document-versions/x/file";

afterEach(() => getDocument.mockReset());

function fakeDocument(numPages: number, renderPromise: Promise<void> = Promise.resolve()) {
  const viewport = { width: 100, height: 140 };
  const renderTask = { promise: renderPromise, cancel: vi.fn() };
  const render = vi.fn(() => renderTask);
  const getPage = vi.fn(async () => ({ getViewport: () => viewport, render }));
  return { doc: { numPages, getPage, destroy: vi.fn() }, render, renderTask, viewport };
}

function pending<T>(): Promise<T> {
  return new Promise<T>(() => {});
}

/** Lets the mocked dynamic import and any follow-up microtasks settle. */
function flush(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 50));
}

describe("PdfPage", () => {
  it("shows an error, not a blank canvas, when the file cannot be loaded", async () => {
    getDocument.mockReturnValue({
      promise: Promise.reject(new Error("Unexpected server response (401)")),
      destroy: vi.fn(),
    });
    render(<PdfPage url={URL_} pageNumber={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not display/i);
    expect(screen.getByTestId("pdf-canvas")).toHaveClass("hidden");
  });

  it("shows an error when the page cannot be fetched", async () => {
    const getPage = vi.fn(() => Promise.reject(new Error("Invalid page request")));
    getDocument.mockReturnValue({
      promise: Promise.resolve({ numPages: 2, getPage, destroy: vi.fn() }),
      destroy: vi.fn(),
    });
    render(<PdfPage url={URL_} pageNumber={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not display/i);
  });

  it("loads the same-origin URL with default credentials, renders the requested page", async () => {
    const { doc, render: renderPage, viewport } = fakeDocument(3);
    getDocument.mockReturnValue({ promise: Promise.resolve(doc), destroy: vi.fn() });
    render(<PdfPage url={URL_} pageNumber={3} />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
    expect(screen.getByTestId("pdf-canvas")).toHaveClass("invisible");

    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument();
    // Exact params: no `withCredentials`. The file is same-origin, so pdf.js's default
    // (fetch credentials "same-origin") already sends the session cookie.
    expect(getDocument).toHaveBeenCalledWith({ url: URL_ });
    expect(doc.getPage).toHaveBeenCalledWith(3);
    const canvas = screen.getByTestId("pdf-canvas");
    expect(renderPage).toHaveBeenCalledWith({ canvas, viewport });
    expect(canvas).not.toHaveClass("invisible");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not start loading when unmounted before pdfjs has been imported", async () => {
    getDocument.mockReturnValue({ promise: pending(), destroy: vi.fn() });
    const { unmount } = render(<PdfPage url={URL_} pageNumber={1} />);
    unmount();
    await flush();
    expect(getDocument).not.toHaveBeenCalled();
  });

  it("destroys the loading task when unmounted while the document loads", async () => {
    const destroy = vi.fn(() => Promise.reject(new Error("worker gone")));
    getDocument.mockReturnValue({ promise: pending(), destroy });
    const { unmount } = render(<PdfPage url={URL_} pageNumber={1} />);
    await waitFor(() => expect(getDocument).toHaveBeenCalled());
    unmount();
    expect(destroy).toHaveBeenCalled();
    await flush(); // the rejected destroy() must not surface as an unhandled rejection
  });

  it("cancels an in-flight render on unmount without showing an error", async () => {
    let rejectRender: (reason: Error) => void = () => {};
    const renderPromise = new Promise<void>((_, reject) => {
      rejectRender = reject;
    });
    const { doc, render: renderPage, renderTask } = fakeDocument(1, renderPromise);
    renderTask.cancel.mockImplementation(() => rejectRender(new Error("Rendering cancelled")));
    getDocument.mockReturnValue({ promise: Promise.resolve(doc), destroy: vi.fn() });
    const { unmount, container } = render(<PdfPage url={URL_} pageNumber={1} />);
    await waitFor(() => expect(renderPage).toHaveBeenCalled());
    unmount();
    expect(renderTask.cancel).toHaveBeenCalled();
    await flush();
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
  it("loads the document once when only the page changes", async () => {
    const { doc } = fakeDocument(3);
    getDocument.mockReturnValue({ promise: Promise.resolve(doc), destroy: vi.fn() });
    const { rerender } = render(<PdfPage url={URL_} pageNumber={1} />);
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    rerender(<PdfPage url={URL_} pageNumber={2} />);
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    expect(getDocument).toHaveBeenCalledTimes(1);
    expect(doc.getPage).toHaveBeenLastCalledWith(2);
  });
  it("says so, and draws nothing, when the page is past the end of the document", async () => {
    const { doc, render: renderPage } = fakeDocument(3);
    getDocument.mockReturnValue({ promise: Promise.resolve(doc), destroy: vi.fn() });
    render(<PdfPage url={URL_} pageNumber={9} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This document has no page 9.");
    expect(screen.getByTestId("pdf-canvas")).toHaveClass("hidden");
    expect(doc.getPage).not.toHaveBeenCalled();
    expect(renderPage).not.toHaveBeenCalled();
  });
});
