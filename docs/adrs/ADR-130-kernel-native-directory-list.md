# ADR-130: kernel-native `/api/directory_list` — workspace directory listing

- **Status:** Ratified (2026-09-25)
- **Scope:** v2 Stage 11.14 (endpoint split, directory family)
- **Supersedes:** none

## Context

The panels-page **Knowledge** tab (`ui/app/tektos-ultima/panels/page.tsx`,
`KnowledgeTab`) proxied `:8020/api/directory_list` — the *standalone* engine
listing the **standalone repo root** (`tektos-ultima-v1`), not the kernel's
own workspace. The kernel had no equivalent endpoint.

Recon also found a latent UI bug: the tab's Type column checks
`e["is_dir"]`, but the standalone API returns `type: "dir" | "file"` and no
`is_dir` — so every row rendered "file" (directories included).

## Decision

### D1 — `GET /api/directory_list` lists the kernel's own workspace
The endpoint lists the **kernel's cwd** (its workspace root,
`~/dev/kosmos-lms`) — the kernel-native referent, mirroring how the other
Stage 11 endpoints report the kernel's own state rather than the standalone
engine's.

- `?path=` (optional, relative to the workspace root; default = root)
- `?depth=` 1 (default) or 2 (clamped; `os.lstat` + bounded recursion)
- **Traversal guard:** the resolved target must stay inside the workspace
  root → `400` otherwise (`/etc`, `../../etc` rejected).
- `404` for a path that is not a directory.
- Bounded at `_DIRECTORY_MAX_ENTRIES = 500` with a `truncated` flag so a
  wide tree cannot blow up the response.

### D2 — element schema: :8020-compatible **plus** `is_dir`
Each entry: `{name, path, parent, type: "dir"|"file", is_dir, size, mtime,
depth}`. `is_dir` is added (redundant with `type`) specifically to fix the
latent UI bug — the tab's existing `e["is_dir"]` check now works, and the
size column renders for files.

### D3 — tab re-point (drop-in)
The panels page's `g()` helper gained the same optional `base` parameter
added to the ops page in ADR-129 (default `GATEWAY`, so the other tabs are
untouched). `loadDir` now calls `g("/api/directory_list", "")` — the
kernel-native base. No parse/render change needed.

## Consequences

- The Knowledge tab now shows the **kernel's own** workspace tree instead of
  the standalone repo's — the correct referent for a kernel-owned dashboard.
- The directory listing is a read-only, bounded, path-constrained view of the
  kernel workspace (no writes, no symlink-following beyond `lstat`, depth ≤ 2,
  ≤ 500 entries).
- The `is_dir` field closes a long-standing silent UI defect (Type column
  wrong for directories) that the re-point surfaced.
