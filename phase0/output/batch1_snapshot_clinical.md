# Snapshot note: ClinicalTrials.gov industry interventional studies

- endpoint: https://clinicaltrials.gov/api/v2/studies
- filter_advanced: AREA[LeadSponsorClass]INDUSTRY AND AREA[StudyType]INTERVENTIONAL AND AREA[StudyFirstPostDate]RANGE[2016-11-07,2026-10-30]
- params: pageSize=1000, pageToken pagination, fields=NCTId,StudyFirstPostDate,LeadSponsorClass,LeadSponsorName,StudyType
- fetched_at_utc: 2026-11-07T06:55:15Z
- note_updated_utc: 2026-11-07T07:12:35Z
- records: 56443
- pages_fetched: 57
- www_pages_flushed: 57
- first_post_date_missing_or_unparsable: 0
- coverage_first_post_date: 2016-11-07 .. 2026-10-30
- weekly_buckets: 521 (one week is a confirmed true zero)
- weekly_bucket_range: 2016-11-07 .. 2026-10-26
- true_zero_week: 2024-09-13 (direct API range query returned 0 studies)
- bucket_rule: Monday..Sunday, label = Friday of that week
- holdout: rows for 2025-01-03 .. 2026-10-30 exist on disk in this raw file, but no computation or inspection has been performed on them; the batch-1 runner hard-clips every series at 2024-12-27 unless `--open-holdout` is passed

## Record-count reconciliation (60,780 vs 56,443)

Preregistration §9 recorded `totalCount=60780` for `INDUSTRY AND INTERVENTIONAL AND StudyFirstPostDate RANGE[2016-01-01,2026-11-06]`. The batch-1 fetch used the locked sample window `RANGE[2016-11-07,2026-10-30]` and returned 56,443.

Direct API `totalCount` queries on 2026-11-07 decompose the difference exactly:

| range | totalCount |
|---|---|
| 2016-01-01 .. 2026-11-06 (prereg §9 availability probe) | 60,780 |
| **2016-11-07 .. 2026-10-30 (locked sample, actually fetched)** | **56,443** |
| 2016-01-01 .. 2016-11-06 (excluded head) | 4,181 |
| 2026-10-31 .. 2026-11-06 (excluded tail) | 156 |
| head + fetched + tail | 60,780 |

- Difference = **4,337 = 4,181 + 156**, entirely a date-window difference.
- **No pagination loss**: the number of fetched record rows (56,443) equals the API `totalCount` for the same filter, across all 57 pages.
- **No filter drift**: same `LeadSponsorClass=INDUSTRY` + `StudyType=INTERVENTIONAL` predicate in both counts.
- The prereg's 60,780 was not an estimate; it is the availability probe's `totalCount` on a wider window. Preregistration text left unchanged.
