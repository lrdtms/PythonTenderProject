export const MAX_UPLOAD_MB = 25;
export const ACCEPT = ".pdf,.xlsx,.csv,.docx";
const EXTENSIONS = new Set(["pdf", "xlsx", "csv", "docx"]);

/** The same checks and wording as the server, so most mistakes are caught before the upload. The
 * server still decides (it also checks that the content matches the extension). */
export function validateFile(file: File): string | null {
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `The file is larger than the ${MAX_UPLOAD_MB} MB limit.`;
  const dot = file.name.lastIndexOf(".");
  const extension = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : "";
  if (!EXTENSIONS.has(extension)) return "Unsupported file type. Upload a PDF, XLSX, CSV or DOCX file.";
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
