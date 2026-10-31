# OmniNexus

[中文](README.md) | English

> **A minimal and stable cross-domain reasoning operating system**: data sources, calculation formulas, transmission chains, panels, and notifications are all hot-swappable plugins.
> It only finds cross-domain transmission relations; validation is done with the user's own budget.

This is an open-source experiment that turns "pre-registered verdicts" into an engineering artifact: **the decision threshold is fixed before the data, every revision leaves a trace, and failure must be loud**. Falsification is a normal output, not an accident.

### What this is / is not

- **It is**: a methodology tool that turns cross-domain transmission hypotheses into checkable verdicts — find a relation, pre-register it, get a verdict, keep the ledger.
- **It is not**: a signal service (no buy/sell calls, no price targets); not a backtesting platform (no parameter tuning for prettier curves); not investment advice (research reference only).
- **It does not promise**: "arbitrage engine" or "real-time expectation gap" — both are retired early concepts; the project no longer issues new signal verdicts, and its 3/3 attempt budget is sealed.

---

## Current status

| Item | Fact |
|---|---|
| Engineering loop (T1) | **30 consecutive days** of unattended daily updates, 2026-09-30 → 2026-10-29, 30/30, no gaps |
| Schedule | GitHub Actions, two cron slots (UTC 00:30 / 12:30); one fully successful run per day is enough |
| Pre-registered verdicts | 3 chains, all failed (details below) |
| Attempt budget | 3/3 used; no further parameter tuning on verdict parameters |
| Data snapshots | Written to `data/` on every run; each commit is versioned history |

### Three verdicts (pre-registered)

| # | Chain | Hypothesis | Result |
|---|---|---|---|
| 1 | chain01 | AI academic heat (LLM / inference optimization) → optical module sector | ❌ No transmission: return ρ −0.108 @7 weeks / turnover ρ −0.123 @1 week |
| 2 | chain10 | Humanoid-robot academic heat → China A-share robot sector | Failed: return ρ +0.149 @20 weeks ❌ / turnover ρ +0.167 @26 weeks (grey zone) |
| 3 | chain20 | Philadelphia Semiconductor Index → China A-share semiconductor ETF (overnight fast transmission) | Failed: best k=1 in window [1,2], ρ +0.215, below the 0.3 threshold; peak k=0, ρ +0.263 is a look-ahead diagnostic, excluded from the verdict |

Verdict threshold `pass_corr = 0.3`, weak-signal band `noise_band = 0.15`. Candidate ≠ conclusion: the chain-level conclusion is decided by the author; metric badges only indicate whether a metric reaches the threshold.

## How to read a verdict

1. **Threshold before data**: the `judgement` block in `chains/*.yaml` is registered before data is written. Once frozen, any change must add a `revisions` entry and consume attempt budget (enforced by tooling, not by trust).
2. **Hash chain**: every run checks the previous commit SHA recorded in `data/streak.json`. A rewritten ledger fails loudly (`rewritten`).
3. **Degradation disclosure**: when a data source is unavailable, the existing fallback chain is used (akshare → Eastmoney direct → index proxy → single-stock proxy), and the exact path is disclosed in the dashboard's "data quality" block. Degradation is not a cover-up.
4. **Look-ahead diagnostic**: same-week co-movement at k=0 is disclosed as a diagnostic only and is never counted as a tradable conclusion.

## Repository layout

```
chains/       chain configs (pre-registration carriers) + verdict traces + run ledger
data/         daily snapshots (a snapshot is history)
omninexus/    computation layer: fetch adapters / alignment / normalization / cross-correlation / verdict engine
tools/        unattended daily entrypoint (daily_update.py) and source probes
tests/        guards: dependency direction / M0 regression / discipline tests / snapshot contract / T1 idempotency
phase0/       original scripts and outputs of the two manual phase-0 validations (audit scene)
content/      falsification retrospective long-form article
dashboard/    dashboard (Vite + React + TS, purely static snapshot reader)
scripts/      profile materialization scripts
```

> Design documents, reasoning notes, and internal audit records **are not distributed with the public repository**; they remain local to the author.

## Local reproduction

```bash
# 1. Python side (3.11)
pip install -r requirements.txt
python tools/daily_update.py          # run one full daily update

# 2. Dashboard
cd dashboard
pnpm install
pnpm dev                              # http://localhost:5173
```

On Windows, double-click `start-dashboard.bat`.

Optional environment variables:

| Variable | Purpose |
|---|---|
| `OPENALEX_API_KEY` | Free OpenAlex API key; raises quota only (without it you may hit 429 and fail that day) |
| `OPENALEX_MAILTO` | OpenAlex polite-pool email; a real contact address is recommended |

## Data sources

- Leading side: **OpenAlex** (data released under CC0 1.0).
- Lagging side: Eastmoney / Sina Finance, fetched through **AkShare** (MIT) and other open-source libraries.

The code and verdict process follow this repository's license; **rights in the data itself do not belong to this project**, and this project grants you no rights in third-party data. Verify the data source's terms of service before any commercial use of outputs.

## Disclaimer

This project is a methodology demo and a public audit trail. It does **not** constitute investment advice, an offer, or a recommendation of any kind. All results are pre-registered verdicts published as-is; past correlation does not imply future returns. You are solely responsible for any decision you make based on this repository.

## License

This repository is licensed under the **[PolyForm Noncommercial License 1.0.0](LICENSE)**:

- **The software itself may not be used commercially** — you may not turn it into a corporate product;
- **Study, research, teaching, and reproduction are fully free**, no application needed;
- **Outputs may be used commercially**: conclusions / charts / reports / datasets produced with this repository's code, data, and pipeline may be used for commercial purposes, provided you **credit the source**:

```
OmniNexus · https://github.com/An0319/OmniNexus
```

See [NOTICE](NOTICE) for details.
