# Dependency audit

Spec requirement: "Dependency and vulnerability monitoring" (base spec section 4.3). Run on 15 Oct 2026 against the scaffold.

## Results

| Ecosystem | Command | Result |
|---|---|---|
| Python (runtime) | `pip-audit` on the locked, non-dev dependencies | No known vulnerabilities |
| Node (runtime) | `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities |
| Node (everything) | `npm audit` | 5 high, all in one dev-only chain (below) |

## Accepted: `braces` chain (dev only)

`eslint-config-next@16.4.1` -> `@next/eslint-plugin-next` -> `fast-glob@3.3.1` -> `micromatch@4.0.8` -> `braces@3.0.3` (GHSA-vfj7-8cjw-p6xm, denial of service through deeply nested glob patterns).

- **No patched release exists.** The advisory covers `braces <= 3.0.3`, and 3.0.3 is the latest published version, so an `overrides` entry cannot fix it.
- **`npm audit fix --force` is wrong here.** It proposes downgrading `eslint-config-next` to 14.2.35, a different major version than the Next.js 16 we use.
- **Not exposed at runtime.** The chain is a devDependency used by ESLint to match file globs from our own config. It is not in the production image (the frontend Docker image copies only the standalone build output), and no user input reaches it.

Decision: accept and document. CI gates on the runtime audit only. Re-check when a patched `braces` or a new `eslint-config-next` is released (`npm audit` after `npm update`).
