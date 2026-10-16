import { describe, expect, it } from "vitest";

import {
  documentKindLabel,
  isTerminalJob,
  jobErrorText,
  jobStatusLabel,
  jobTone,
  kindLabel,
  processingStatusLabel,
  tenderStatusLabel,
  warningText,
} from "./status-text";

describe("status text", () => {
  it("knows the terminal job statuses", () => {
    for (const s of ["succeeded", "succeeded_with_warnings", "failed", "cancelled"]) {
      expect(isTerminalJob(s)).toBe(true);
    }
    for (const s of ["queued", "running", undefined, ""]) expect(isTerminalJob(s)).toBe(false);
  });

  it("labels every known status in plain words and never shows a raw code for an unknown one", () => {
    expect(jobStatusLabel("running")).toBe("Processing");
    expect(jobStatusLabel("succeeded_with_warnings")).toBe("Done, with warnings");
    expect(processingStatusLabel("ready_with_warnings")).toBe("Ready, with warnings");
    expect(tenderStatusLabel("in_review")).toBe("In review");
    expect(documentKindLabel("boq")).toBe("Bill of quantities");
    expect(kindLabel("requirements")).toBe("Requirements");
    expect(jobStatusLabel("weird_new_status")).toBe("Unknown status");
    expect(jobTone("failed")).toBe("danger");
    expect(jobTone("succeeded")).toBe("success");
  });

  it("explains job failures in plain words", () => {
    expect(jobErrorText("PDF_ENCRYPTED")).toMatch(/password/i);
    expect(jobErrorText("FILE_CORRUPT")).toMatch(/damaged|cannot be read/i);
    expect(jobErrorText("LLM_UNAVAILABLE")).toMatch(/AI/);
    expect(jobErrorText("TENDER_ARCHIVED")).toMatch(/archived/i);
    expect(jobErrorText("SOMETHING_NEW")).toBe("Processing failed. Try again, or upload the file again.");
    expect(jobErrorText(null)).toBe("Processing failed. Try again, or upload the file again.");
  });

  it("explains warnings, including page lists and counts, and survives odd input", () => {
    expect(warningText({ code: "OCR_FAILED", pages: [12, 13, 14] })).toBe(
      "Pages 12, 13, 14 could not be read.",
    );
    expect(warningText({ code: "OCR_FAILED", pages: [2] })).toBe("Page 2 could not be read.");
    expect(warningText({ code: "OCR_LOW_CONFIDENCE", pages: [3] })).toMatch(/page 3/i);
    expect(warningText({ code: "EVIDENCE_UNVERIFIED", count: 2 })).toMatch(/2 requirements/);
    expect(warningText({ code: "FILTER_LOW_YIELD" })).toMatch(/deep scan/i);
    expect(warningText({ code: "BOQ_NEEDS_MANUAL_ENTRY", pages: [4] })).toMatch(/manually/i);
    expect(warningText({ code: "DUPLICATE_OF_REVIEWED", count: 1 })).toMatch(/1 /);
    expect(warningText({ code: "NOT_A_KNOWN_CODE" })).toBe("Warning: NOT_A_KNOWN_CODE");
    expect(warningText(null)).toBe("Warning");
    expect(warningText("text")).toBe("Warning");
  });
});
