"""Batch-1 lead/lag runner (energy N1 + clinical XBI).

Locked parameters (from phase0/preregistration_energy_n1.md and
phase0/preregistration_clinical_xbi.md):
  lag_range  = 0..13
  pass_window= 4..13
  pass_corr  = 0.3
  noise_band = 0.19
  z-score    = rolling 52 weeks, min_periods=26
  sample     = 2016-11-11 .. 2026-10-30 (weekly label = Friday)
  train      = 2016-11-11 .. 2022-12-30
  validation = 2023-01-06 .. 2024-12-27
  holdout    = 2025-01-03 .. 2026-10-30  (SEALED; requires --open-holdout)

Without --open-holdout the loader hard-clips every series at 2024-12-27
*before* any z-scoring or correlation.  The script never sees holdout rows.

Usage (run from the repository root):
  python phase0/run_batch1.py --gate-selftest     # prove the seal works
  python phase0/run_batch1.py --audit-only        # data audit only
  python phase0/run_batch1.py                     # train + validation xcorr
  python phase0/run_batch1.py --open-holdout      # NOT used in batch 1

Segment pairing rule: a pair counts only when both lead_z_t and lag_z_(t+k)
fall inside the segment, i.e. t <= end - k weeks.  Validation happens to equal
the holdout cutoff, so its row counts were already strict; the train segment
was not, and is corrected here (n = 295 - k instead of a flat 296).
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = Path("phase0/output")
SAMPLE_START = pd.Timestamp("2016-11-11")
SAMPLE_END = pd.Timestamp("2026-10-30")
TRAIN = (pd.Timestamp("2016-11-11"), pd.Timestamp("2022-12-30"))
VALID = (pd.Timestamp("2023-01-06"), pd.Timestamp("2024-12-27"))
HOLDOUT = (pd.Timestamp("2025-01-03"), pd.Timestamp("2026-10-30"))
CUTOFF = VALID[1]
LAGS = list(range(0, 14))


def friday_label(d: pd.Timestamp) -> pd.Timestamp:
    """Week label = the Friday of the trading week containing d."""
    return d + pd.Timedelta(days=4 - d.weekday())


def load_weekly_price(symbol: str, open_holdout: bool) -> pd.Series:
    """Weekly last adjclose per Friday label, gated at the holdout cutoff."""
    frames = []
    main = pd.read_csv(OUT / f"batch1_yahoo_{symbol}_daily.csv", parse_dates=["date"])
    base = pd.read_csv(OUT / f"batch1_yahoo_{symbol}_base.csv", parse_dates=["date"])
    frames.append(base)
    frames.append(main)
    daily = pd.concat(frames, ignore_index=True).dropna(subset=["adjclose"])
    daily = daily.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    daily["week"] = daily["date"].map(friday_label)
    weekly = daily.groupby("week")["adjclose"].last().sort_index()
    end = SAMPLE_END if open_holdout else CUTOFF
    weekly = weekly.loc[(weekly.index >= SAMPLE_START) & (weekly.index <= end)]
    return weekly.pct_change()


def load_lead_energy(open_holdout: bool) -> pd.Series:
    df = pd.read_csv(OUT / "batch1_eia_wpsr_utilization.csv", parse_dates=["week_ending"])
    s = df.set_index("week_ending")["utilization_pct"].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    end = SAMPLE_END if open_holdout else CUTOFF
    return s.loc[(s.index >= SAMPLE_START) & (s.index <= end)].astype(float)


def load_lead_clinical(open_holdout: bool) -> pd.Series:
    df = pd.read_csv(OUT / "batch1_clinical_weekly_counts.csv",
                     parse_dates=["week_monday", "week_label_friday"])
    s = df.set_index("week_label_friday")["count"].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    end = SAMPLE_END if open_holdout else CUTOFF
    return s.loc[(s.index >= SAMPLE_START) & (s.index <= end)].astype(float)


def roll_z(s: pd.Series) -> pd.Series:
    m = s.rolling(52, min_periods=26).mean()
    sd = s.rolling(52, min_periods=26).std()
    return (s - m) / sd


def seg_xcorr(lead_z: pd.Series, lag_z: pd.Series, start, end, lags=None) -> pd.DataFrame:
    rows = []
    for k in (LAGS if lags is None else lags):
        shifted = lag_z.shift(-k)
        pair = pd.concat([lead_z.rename("lead"), shifted.rename("lag")], axis=1)
        last_t = end - pd.Timedelta(weeks=k)
        pair = pair.loc[(pair.index >= start) & (pair.index <= last_t)].dropna()
        n = len(pair)
        corr = pair["lead"].corr(pair["lag"]) if n >= 3 else np.nan
        rows.append({"k": k, "n": n, "corr": corr})
    return pd.DataFrame(rows)


def build_series():
    open_holdout = ARGS.open_holdout
    data = {
        "energy_n1": (load_lead_energy(open_holdout), load_weekly_price("CRAK", open_holdout)),
        "clinical_xbi": (load_lead_clinical(open_holdout), load_weekly_price("XBI", open_holdout)),
    }
    out = {}
    for name, (lead, lag) in data.items():
        out[name] = (roll_z(lead), roll_z(lag), lead, lag)
    return out


def audit(built):
    print(json.dumps({"seal": {
        "open_holdout_flag": ARGS.open_holdout,
        "cutoff": str(CUTOFF),
        "holdout_range": [str(HOLDOUT[0]), str(HOLDOUT[1])],
    }}, ensure_ascii=False))
    for name, (lz, gz, lead, lag) in built.items():
        after_cutoff = int(((lead.index > CUTOFF).sum()) + ((lag.index > CUTOFF).sum()))
        print(json.dumps({
            "series": name,
            "lead_rows": int(len(lead)),
            "lead_min": str(lead.index.min().date()),
            "lead_max": str(lead.index.max().date()),
            "lag_rows": int(len(lag)),
            "lag_min": str(lag.index.min().date()),
            "lag_max": str(lag.index.max().date()),
            "rows_after_cutoff_loaded": after_cutoff,
            "lead_effective_min_after_z": str(lead.index[roll_z(lead).notna()].min().date()),
        }, ensure_ascii=False))
        assert after_cutoff == 0, f"{name}: holdout rows loaded without --open-holdout"
        assert lead.index.max() <= CUTOFF and lag.index.max() <= CUTOFF


def gate_selftest():
    """Prove the seal: raw files extend past cutoff, gated loader does not."""
    raw_max = []
    for fn, col in [("batch1_eia_wpsr_utilization.csv", "week_ending"),
                    ("batch1_clinical_weekly_counts.csv", "week_label_friday"),
                    ("batch1_yahoo_CRAK_daily.csv", "date"),
                    ("batch1_yahoo_XBI_daily.csv", "date")]:
        d = pd.read_csv(OUT / fn, parse_dates=[col])
        raw_max.append((fn, str(d[col].max().date())))
    print("RAW FILE MAX DATES (on disk, include holdout):")
    for fn, v in raw_max:
        print(f"  {fn}: {v}")

    global ARGS
    saved = ARGS
    ARGS = argparse.Namespace(open_holdout=False)
    built = build_series()
    print("GATED LOADER (no --open-holdout):")
    for name, (lz, gz, lead, lag) in built.items():
        print(f"  {name}: lead_max={lead.index.max().date()} lag_max={lag.index.max().date()}")
        assert lead.index.max() <= CUTOFF and lag.index.max() <= CUTOFF
    ARGS = saved
    print("PASS: gated loader's max date <= 2024-12-27; holdout rows are unreachable.")


def summarise(df, label):
    win = df[(df["k"] >= 4) & (df["k"] <= 13)]
    peak = win.loc[win["corr"].idxmax()] if len(win) else None
    best_all = df.loc[df["corr"].idxmax()]
    print(json.dumps({
        "segment": label,
        "peak_in_window": None if peak is None else {"k": int(peak["k"]), "n": int(peak["n"]),
                                                     "corr": round(float(peak["corr"]), 4)},
        "best_any_k": {"k": int(best_all["k"]), "n": int(best_all["n"]),
                       "corr": round(float(best_all["corr"]), 4)},
        "negative_in_window": bool(((win["corr"] < 0).any())),
    }, ensure_ascii=False))
    return peak


def main():
    global ARGS
    ARGS = parser.parse_args()
    if ARGS.gate_selftest:
        gate_selftest()
        return
    built = build_series()
    audit(built)
    if ARGS.audit_only:
        return

    all_rows = []
    fig, axes = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
    for ax, (name, (lz, gz, lead, lag)) in zip(axes, built.items()):
        tr = seg_xcorr(lz, gz, *TRAIN)
        va = seg_xcorr(lz, gz, *VALID)
        tr["account"], tr["segment"] = name, "train"
        va["account"], va["segment"] = name, "validation"
        all_rows += [tr, va]
        tr.to_csv(OUT / f"batch1_xcorr_{name}_train.csv", index=False)
        va.to_csv(OUT / f"batch1_xcorr_{name}_validation.csv", index=False)
        ax.plot(tr["k"], tr["corr"], marker="o", label="train")
        ax.plot(va["k"], va["corr"], marker="s", label="validation")
        ax.axvspan(4, 13, color="grey", alpha=0.12)
        ax.axhline(0, color="black", lw=0.6)
        ax.axhline(0.3, color="tab:green", ls="--", lw=0.8)
        ax.axhline(0.19, color="tab:orange", ls=":", lw=0.8)
        ax.set_title(name)
        ax.set_ylabel("Pearson r")
        ax.legend()
        print(f"\n=== {name} ===")
        print("TRAIN"); print(tr.to_string(index=False))
        summarise(tr, "train")
        print("VALIDATION"); print(va.to_string(index=False))
        summarise(va, "validation")

    axes[-1].set_xlabel("lead weeks k (lead_z_t vs lag_z_(t+k))")
    fig.tight_layout()
    fig.savefig(OUT / "batch1_xcorr_curve.png", dpi=150)

    pd.concat(all_rows).to_csv(OUT / "batch1_xcorr_all.csv", index=False)
    print("\nwrote batch1_xcorr_*.csv and batch1_xcorr_curve.png")


parser = argparse.ArgumentParser()
parser.add_argument("--open-holdout", action="store_true")
parser.add_argument("--audit-only", action="store_true")
parser.add_argument("--gate-selftest", action="store_true")
ARGS = None

if __name__ == "__main__":
    main()
