# PREDICTIONS (written 16 Nov 2026, before any log was pulled)

I have not opened the Dune dashboard or any dispute data. These come from the docs
(`DOCS_FIRST.md`) and general knowledge of the scale of Polymarket. Scoring is added
after the pull, misses included. Ranges are meant to hold about 80% of the time.

Universe: OptimisticOracleV2 + ManagedOptimisticOracleV2, Polygon. Windows end at the
last block fetched.

## Numeric predictions
| # | Quantity | Prediction (range) | Reasoning |
|---|---|---|---|
| P1 | Proposals, last 30 days | 10,000 to 60,000 | Brief says >1M lifetime; recent months run heavier than average. |
| P2 | Proposals, last 90 days | 30,000 to 180,000 | Roughly 3x P1. |
| P3 | Dispute rate, 30 days | 0.05% to 0.40% | Docs headline 99.8% undisputed (all UMA, undated) implies about 0.2%. |
| P4 | Dispute rate, 90 days | 0.05% to 0.40% | Same, wider sample. |
| P5 | Disputes in 30 days | 8 to 150 | P1 x P3. |
| P6 | Overturn rate among decided, 30 days | 20% to 70% | Few decided cases, censored by the 2-day vote. Low confidence. |
| P7 | Overturn rate among decided, 90 days | 30% to 65% | Larger sample. |
| P8 | Median hours, dispute to `Settle` | 55 to 85 h | Docs: vote starts at the next 24:00 UTC boundary at least 4h after the dispute (4 to 28h wait) plus 48h of voting = 52 to 76h at the earliest, plus a lag until someone calls `settle`. |
| P9 | p90 hours, dispute to `Settle` | 90 to 220 h | Tail from unresolved votes rolling a round (+48h) and late `settle` calls. |
| P10 | Disputes per day (90-day mean) | 0.3 to 3 | P5 / 30, allowing for burstiness. |
| P11 | Open disputes now (no `Settle`, last 30 days) | 1 to 12 | Disputes from the last ~3 days cannot be settled yet, plus stragglers. |
| P12 | Share of settled disputes that are "too early" resets | 0% to 15% | Resets are rare by design. Low confidence. |
| P13 | Managed contract share of disputes, last 90 days | 40% to 95% | Polymarket is the main user and moved to the managed oracle from Aug 2025. |

## Structural predictions (pass/fail)
- S1: No dispute is settled sooner than 48h after it was raised (a vote cannot finish faster). A violation means a decoding or key error.
- S2: Every `Settle` with a non-zero disputer matches a `DisputePrice` with the same key.
- S3: Overlapping log queries return the same counts. A mismatch means the RPC truncates.
- S4: Zero `DisputePrice` / `Settle` logs on OOv3 (not queried; taken from the Dune dashboard, stated in README).

## Validation plan against the Dune dashboard
Dashboard: https://dune.com/xpertknight/uma-oracle-base-rates-vs-anecdotes (queries 7864590, 7866390).
1. Predictions above stay fixed. Only after the pull, open the dashboard's saved results (no query credits needed to read them; if it cannot be read, stop and tell Marco).
2. Pick two complete past calendar months inside both the Dune data and my 12-month dispute window. Prefer one month before and one after the managed oracle took over, to test both contracts.
3. Compare, per month and per contract: disputes (distinct request keys), `Settle` count on disputed keys, and if shown the overturn rate.
4. Pass: each figure within 2%. For counts below 50 that means an exact match or a difference I can explain key by key.
5. If it fails: first suspects are (a) UTC month edges (`evt_block_time` vs block date), (b) duplicate or re-emitted logs on one side, (c) Dune's decoded tables missing a proxy upgrade, (d) wrong address, (e) RPC truncation. Do not go on to GATE 2 until the cause is named.
6. Record the dashboard's last-refresh time, since it may lag the chain.

## Kill condition
Checked at the end of day 1. **Stop and report** if any of these holds:
- No free public Polygon RPC returns all `ProposePrice` logs for the last 90 days of both contracts in a reasonable time (set at under 3 hours of fetching in total), with overlapping re-queries agreeing on counts.
- Every free endpoint caps or silently truncates ranges in a way adaptive chunking cannot fix.
- Either address has no contract code on chain, or the first logs do not match the event signatures, and no other address can be justified from UMA's own sources.

Then the report gives: endpoints tried (and their limits and errors), what was fetched,
and the cost of a paid endpoint with archive log access, found by checking current
provider pricing. A killed study is a valid result.

## Method (one paragraph)
`eth_getLogs` per contract and event, topic0 computed from the signatures in
`DOCS_FIRST.md` and checked against a real log. Proposals for 90 days, disputes and
settles for 12 months. Adaptive block-range chunking that halves on error or on a
result cap. Raw logs go to `data/` keyed by (tx hash, log index), which makes reruns
idempotent. Each chunk is re-queried over an overlapping range to detect truncation.
Metrics follow `q1` to `q4` exactly. No wallet address is written to any output.
Free endpoint known to answer so far: `polygon-bor-rpc.publicnode.com`
(`eth_blockNumber` returned 0x5cec453). `polygon-rpc.com` answered "tenant disabled"
and `rpc.ankr.com/polygon` requires a key.
