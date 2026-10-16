import { useQuery } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { documentsQueryOptions } from "@/api/documents";
import { ids, makeDocument, makeVersion } from "@/test/fixtures";
import { FakeXhr } from "@/test/fake-xhr";
import { meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { NewVersion } from "./new-version";
import { UploadForm } from "./upload-form";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

const UPLOAD_URL = `/api/v1/tenders/${ids.tender}/documents`;
const WRITE = meWith(["read", "upload_documents"]);

beforeEach(() => {
  FakeXhr.instances = [];
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
});
afterEach(() => vi.unstubAllGlobals());

function pdf(name = "pack.pdf", size = 2048): File {
  const file = new File(["%PDF-1.4"], name, { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

function DocumentsObserver() {
  useQuery(documentsQueryOptions(ids.tender));
  return null;
}

function result() {
  return { document: makeDocument(), version: makeVersion(), job_id: ids.job };
}

describe("UploadForm", () => {
  it("uploads with the kind and optional title, shows progress, then refreshes the documents and resets", async () => {
    let docs = 0;
    mockApi({ [`GET /api/v1/tenders/${ids.tender}/documents`]: () => (docs++, respond(200, [])) }, WRITE);
    renderSignedIn(
      <>
        <DocumentsObserver />
        <UploadForm tenderId={ids.tender} />
      </>,
    );
    await waitFor(() => expect(docs).toBe(1)); // initial load
    await userEvent.selectOptions(await screen.findByLabelText(/document type/i), "boq");
    await userEvent.type(screen.getByLabelText(/title/i), "Main BoQ");
    await userEvent.upload(screen.getByLabelText(/file/i), pdf("boq.pdf"));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    const xhr = FakeXhr.last;
    expect([xhr.method, xhr.url]).toEqual(["POST", UPLOAD_URL]);
    expect(xhr.headers["X-Requested-With"]).toBe("IntelTPS");
    const form = xhr.body as FormData;
    expect(form.get("kind")).toBe("boq");
    expect(form.get("title")).toBe("Main BoQ");
    expect((form.get("file") as File).name).toBe("boq.pdf");
    xhr.progress(512, 2048);
    expect(await screen.findByRole("progressbar", { name: /upload/i })).toHaveAttribute("value", "0.25");
    xhr.respond(201, result());
    await waitFor(() => expect(docs).toBe(2)); // refreshed after the upload
    expect(await screen.findByText(/uploaded/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/title/i)).toHaveValue("");
  });

  it("catches the same mistakes the server would, before any request is sent", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    const input = await screen.findByLabelText(/file/i);
    await userEvent.upload(input, pdf("huge.pdf", 26 * 1024 * 1024));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The file is larger than the 25 MB limit.");
    // user-event drops files the input's `accept` would reject unless told not to (a browser user can still pick "all files")
    await userEvent.setup({ applyAccept: false }).upload(input, new File(["x"], "virus.exe"));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unsupported file type. Upload a PDF, XLSX, CSV or DOCX file.");
    expect(FakeXhr.instances).toHaveLength(0);
  });

  it("requires a file to be chosen", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await userEvent.click(await screen.findByRole("button", { name: /upload/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/choose a file/i);
    expect(FakeXhr.instances).toHaveLength(0);
  });

  it.each([
    [422, "validation_error", "The file content does not match its extension."],
    [403, "limit_exceeded", "Your plan's upload limit has been reached."],
    [409, "tender_archived", "This tender is archived."],
  ])("shows the server's refusal (%s %s) and lets the user try again", async (status, code, message) => {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await userEvent.upload(await screen.findByLabelText(/file/i), pdf());
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    FakeXhr.last.respond(status, { error: { code, message } });
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: /upload/i })).toBeEnabled();
  });

  it("disables the button during the upload so it cannot be sent twice", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await userEvent.upload(await screen.findByLabelText(/file/i), pdf());
    const button = screen.getByRole("button", { name: /upload/i });
    await userEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    await userEvent.click(button);
    expect(FakeXhr.instances).toHaveLength(1);
  });

  it("renders nothing for a user without upload_documents", async () => {
    mockApi({}, meWith(["read"], "reviewer"));
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await waitFor(() => expect(screen.queryByLabelText(/file/i)).not.toBeInTheDocument());
  });
});

describe("UploadForm stale messages", () => {
  async function failFirst() {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await userEvent.upload(await screen.findByLabelText(/file/i), pdf());
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    FakeXhr.last.respond(422, { error: { code: "validation_error", message: "The file content does not match its extension." } });
    expect(await screen.findByRole("alert")).toHaveTextContent("does not match");
  }

  it("clears an old server error when another file is chosen", async () => {
    await failFirst();
    await userEvent.upload(screen.getByLabelText(/file/i), pdf("other.pdf"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows only the validation message after a server error, and the old error never comes back", async () => {
    await failFirst();
    await userEvent.setup({ applyAccept: false }).upload(screen.getByLabelText(/file/i), new File(["x"], "virus.exe"));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent("Unsupported file type");
    await userEvent.upload(screen.getByLabelText(/file/i), pdf("good.pdf"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("hides the success message when another file is chosen", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await userEvent.upload(await screen.findByLabelText(/file/i), pdf());
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    FakeXhr.last.respond(201, result());
    expect(await screen.findByText(/uploaded/i)).toBeInTheDocument();
    await userEvent.upload(screen.getByLabelText(/file/i), pdf("next.pdf"));
    expect(screen.queryByText(/uploaded/i)).not.toBeInTheDocument();
  });

  it("rejects an empty file and does not send a whitespace-only title", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await userEvent.upload(await screen.findByLabelText(/file/i), pdf("empty.pdf", 0));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The file is empty.");
    expect(FakeXhr.instances).toHaveLength(0);
    await userEvent.upload(screen.getByLabelText(/file/i), pdf("ok.pdf"));
    await userEvent.type(screen.getByLabelText(/title/i), "   ");
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    expect((FakeXhr.last.body as FormData).has("title")).toBe(false);
  });
});

describe("NewVersion", () => {
  it("uploads a new version of an existing document to its own endpoint", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<NewVersion tenderId={ids.tender} documentId={ids.document} />);
    await userEvent.upload(await screen.findByLabelText(/new version/i), pdf("v2.pdf"));
    await waitFor(() => expect(FakeXhr.instances).toHaveLength(1));
    expect([FakeXhr.last.method, FakeXhr.last.url]).toEqual(["POST", `/api/v1/documents/${ids.document}/versions`]);
    expect((FakeXhr.last.body as FormData).get("kind")).toBeNull();
    FakeXhr.last.respond(201, result());
    expect(await screen.findByText(/uploaded/i)).toBeInTheDocument();
  });

  it("validates the file before sending and shows server errors", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<NewVersion tenderId={ids.tender} documentId={ids.document} />);
    await userEvent.setup({ applyAccept: false }).upload(await screen.findByLabelText(/new version/i), new File(["x"], "bad.txt"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unsupported file type/i);
    expect(FakeXhr.instances).toHaveLength(0);
  });

  it("shows a 422 from the server and lets the same file be chosen again", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<NewVersion tenderId={ids.tender} documentId={ids.document} />);
    const file = pdf("v2.pdf");
    await userEvent.upload(await screen.findByLabelText(/new version/i), file);
    await waitFor(() => expect(FakeXhr.instances).toHaveLength(1));
    FakeXhr.last.respond(422, { error: { code: "validation_error", message: "The file content does not match its extension." } });
    expect(await screen.findByRole("alert")).toHaveTextContent("does not match");
    await userEvent.upload(screen.getByLabelText(/new version/i), file);
    await waitFor(() => expect(FakeXhr.instances).toHaveLength(2));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("clears a validation message when a valid file replaces the bad one, and shows progress", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<NewVersion tenderId={ids.tender} documentId={ids.document} />);
    await userEvent.setup({ applyAccept: false }).upload(await screen.findByLabelText(/new version/i), new File(["x"], "bad.txt"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unsupported file type/i);
    await userEvent.upload(screen.getByLabelText(/new version/i), pdf("v2.pdf"));
    await waitFor(() => expect(FakeXhr.instances).toHaveLength(1));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    FakeXhr.last.progress(1, 4);
    expect(await screen.findByRole("progressbar", { name: /upload/i })).toHaveAttribute("value", "0.25");
    FakeXhr.last.respond(201, result());
    expect(await screen.findByText(/uploaded/i)).toBeInTheDocument();
    expect(screen.getAllByRole("status")).toHaveLength(1);
    await userEvent.upload(screen.getByLabelText(/new version/i), pdf("v3.pdf"));
    expect(screen.queryByText(/uploaded/i)).not.toBeInTheDocument();
  });
});
