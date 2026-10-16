import type { components } from "./schema";

export type Me = components["schemas"]["MeDTO"];
export type Role = Me["role"];
export type LoginInput = components["schemas"]["LoginRequest"];
export type RegisterInput = components["schemas"]["RegisterRequest"];
export type Tender = components["schemas"]["TenderDTO"];
export type TenderCreate = components["schemas"]["TenderCreate"];
export type DocumentItem = components["schemas"]["DocumentDTO"];
export type DocumentVersion = components["schemas"]["VersionDTO"];
export type UploadResult = components["schemas"]["UploadResultDTO"];
export type Job = components["schemas"]["JobDTO"];
export type Run = components["schemas"]["RunDTO"];
export type KindStatus = components["schemas"]["KindStatusDTO"];
export type ExtractionStatus = components["schemas"]["ExtractionStatusDTO"];
