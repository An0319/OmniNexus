# OmniNexus · Desktop Shell (F)

[中文](README.md) | English

> A **local** desktop shell around the command-line pipeline that already lives in this repo
> (`phase0/timeline/`, `phase0/registry/`). You type a query, run one fetch, register a claim, and re-check it
> when it comes due.
> The shell only moves arguments and results around — **it makes no verdicts**. All status classification
> happens in one place, `desktop/ui/src/lib/status-map.ts`.

## Read this first: it needs things on your machine

Two prerequisites. If either is missing, the app will not run — that is expected, not a bug.

| Dependency | Why |
|---|---|
| **Python 3 on your machine** | No interpreter is bundled. The shell spawns an existing Python and needs `requests` (`pip install requests`, or use the repo-root `requirements.txt`) |
| **WebView2 (Windows)** | The frontend runtime Tauri uses. Usually preinstalled on Windows 10/11; otherwise install it yourself |

Two more constraints worth stating up front:

- **The Python path is hardcoded.** `PYTHON_PATH` in `desktop/ui/src/lib/bridge.ts` and `PYTHON_FALLBACK` in
  `desktop/src-tauri/src/main.rs` both point at the author's machine. On a different machine you must change
  both, or the UI will only report "Python interpreter not found".
- **Repo root is discovered, not configured.** The shell reads `MNX_REPO_ROOT` first; otherwise it walks up from
  the current directory looking for `phase0/timeline/timeline.py`. If you move that layout, set the variable.

## What it does today

- Run one fetch for a **topic**, or for a **company / ticker**, with a date range, source list, and per-source cap.
- Show the result in one of seven tiers — completed / genuinely empty / entity zero-hit / cannot judge /
  partial coverage / failed / unknown status. **These tiers are never merged**, because "nothing was fetched"
  and "something was fetched but not recognised" are different facts.
- Every lead carries a source URL; one click hands it to your default browser. If it fails to open, the UI says
  so — it does not pretend success.
- Register a one-sentence claim together with its criteria into "my records", then re-check items once due.
  Criteria freeze at registration time; a rejected registration leaves nothing half-written.

## What it does not do (yet)

- **The extraction engine is English-only, so Chinese-language queries return no usable results.** Concretely:
  the action vocabulary in `rules_v2` is English; the "not an event" rules only match English openings; the
  Google News source pins `hl=en-US&gl=US&ceid=US:en`; and two of the four sources (ClinicalTrials.gov and the
  US Federal Register) are English-language registries by nature. A Chinese query mostly yields items the
  extractor **cannot recognise** — not "no events exist".
- **The interface is Chinese-only.** User-facing copy is centralised under `desktop/ui/src/i18n/`, so an English
  string table can be added later; that table does **not** exist yet.
- **No installer.** `bundle.active` is `false` in `tauri.conf.json`: no binary distribution, no signing, no
  auto-update. You build and run it yourself.
- **Not a background service.** Nothing is checked while the machine is off; due items are re-checked once when
  you open the app.
- **Only actually run on Windows.** Tauri is cross-platform, but the window config and the "hide the child
  process console" flag are Windows-specific. Other platforms are untested.

## Running it

Prerequisites: Node.js (Vite 8 requires `^20.19.0 || >=22.12.0`), a Rust toolchain, and the two dependencies above.

```bash
# 1. Build the frontend first (the output is embedded into the binary at cargo build time)
cd desktop/ui
npm install
npm run build

# 2. Then build and launch the shell
cd ../src-tauri
cargo run
```

For layout-only work you can run `cd desktop/ui && npm run dev` in a normal browser. There is **no process
bridge** there, so the UI will show "process bridge unavailable" — that is expected.

## Layout

```
desktop/
├── README.md / README.en.md   this file
├── src-tauri/                 Rust shell: spawns Python, streams progress lines, returns exitCode/stdout/stderr/data
├── ui/                        React + Vite + Tailwind frontend
│   ├── src/components/        design-system-aligned primitives
│   ├── src/pages/             two pages: "what to look at" / "my judgments"
│   ├── src/lib/               bridge, status-map (the single classification point), record grouping
│   └── src/i18n/              UI string table (Chinese only for now) and a term glossary
└── tools/build_dev_data.py    builds local replay data (not committed)
```

## How it relates to the rest of the repo

This shell only puts the root-level `phase0/` pipeline behind a window. It adds no new criteria and keeps no
second copy of the status vocabulary. For what the project is and is not, see the [root README](../README.md).
