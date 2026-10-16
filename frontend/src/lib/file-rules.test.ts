import { describe, expect, it } from "vitest";

import { ACCEPT, MAX_UPLOAD_MB, formatBytes, validateFile } from "./file-rules";

function fileOf(name: string, size: number): File {
  const file = new File(["x"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("validateFile (mirrors the server's messages)", () => {
  it("accepts supported types within the limit, in any case", () => {
    for (const name of ["a.pdf", "b.XLSX", "c.csv", "d.DocX"]) expect(validateFile(fileOf(name, 10))).toBeNull();
    expect(validateFile(fileOf("a.pdf", MAX_UPLOAD_MB * 1024 * 1024))).toBeNull();
  });

  it("rejects an empty file, an oversize file and an unsupported extension", () => {
    expect(validateFile(fileOf("a.pdf", 0))).toBe("The file is empty.");
    expect(validateFile(fileOf("a.pdf", MAX_UPLOAD_MB * 1024 * 1024 + 1))).toBe(
      "The file is larger than the 25 MB limit.",
    );
    expect(validateFile(fileOf("a.exe", 10))).toBe("Unsupported file type. Upload a PDF, XLSX, CSV or DOCX file.");
    expect(validateFile(fileOf("noextension", 10))).toBe(
      "Unsupported file type. Upload a PDF, XLSX, CSV or DOCX file.",
    );
  });

  it("formats sizes and exposes the accept list", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(ACCEPT).toBe(".pdf,.xlsx,.csv,.docx");
  });
});
