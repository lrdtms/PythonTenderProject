import type { components } from "./schema";

export type Me = components["schemas"]["MeDTO"];
export type Role = Me["role"];
export type LoginInput = components["schemas"]["LoginRequest"];
export type RegisterInput = components["schemas"]["RegisterRequest"];
