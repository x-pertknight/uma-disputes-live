# PREDICTIONS_ADDENDUM (written 16 Nov 2026, before any log was pulled)

`PREDICTIONS.md` is unchanged. Conditions added before the data pull:

1. **No wallet addresses in anything publishable.** Full raw logs (which carry the
   indexed `proposer` and `disputer`) live only in `data/raw_local/`, which is in
   `.gitignore`. Publishable data keeps: request key hash, tx hash, log index, block,
   timestamp, requester contract, prices, question text. Requester contracts
   (adapters) are public protocol contracts and may be named.
2. **Right-censoring.** The headline overturn rate uses a matured cohort: disputes at
   least 7 days old at the last block. The count of immature disputes left out is
   shown. The raw 30-day figure appears only next to it.
3. **Split by requester.** Share of proposals and of disputes per requester contract,
   top five plus "other". If a first dispute leads to a new request for the same
   question, the README says so; all rates are per request, not per market.
4. **"Open" means "no Settle event yet".** It does not mean the vote is undecided.
5. **Scale check before the full pull.** One recent day of `ProposePrice` per
   contract, extrapolated to 90-day volume and fetch time. Recorded below.

## Added structural prediction
- S5: A matured overturn cohort has fewer decided disputes than the raw 30-day count.
  Pass if immature count is reported and non-negative.

## Scale check record
Recorded 16 Nov 2026, ~20:45 UTC. P1/P2 are not edited.

**Endpoint finding first.** `polygon-bor-rpc.publicnode.com` capped `eth_getLogs` at
1,000 blocks, then at 10 blocks once a long job was running, so it is not usable for
bulk pulls. `polygon.gateway.tenderly.co` served 50,000-block ranges (18,099 logs in
5.7 s) and rejects ranges above that by result size (adaptive splitting handles it).
QuickNode's public endpoint served 10,000 blocks but returned HTTP 413 at 50,000.
polygon-rpc.com, Ankr, blastapi, nodies, omniatech: unusable (disabled, key needed, 403
or 521). Other names did not resolve.

**One day** = 43,200 blocks ending 1,000 blocks behind head (blocks 97,393,329 to
97,436,528). It covered 64,798 s (0.75 day): Polygon blocks are now about 1.5 s.
| Contract | ProposePrice logs | Fetch time | Per full day (x1.333) | 90-day estimate |
|---|---|---|---|---|
| OOv2 | 111 | 1.5 s | about 148 | about 13,000 |
| ManagedOOv2 | 10,269 | 4.3 s | about 13,700 | about 1,230,000 |
| Total | 10,380 | 5.8 s | about 13,850 | **about 1.25 million** |

Topic0 matched on every log, address matched on every log, and both addresses hold
contract code (the managed one is a 163-byte proxy, as expected for a proxy).

**Verdict against P1/P2.** 90-day proposals of about 1.25M are roughly 7x above the top
of P2 (30,000 to 180,000). P1 (10,000 to 60,000 for 30 days) is about 7x too low too
(30 days is about 415,000). One day is one sample and may be a busy day (sports
markets); the full pull gives the real count. The prediction is scored as a miss if the
full pull confirms the order of magnitude.

**Outcome of the full pull (added afterwards).** The 90-day count was 3,005,636, about
2.4x this estimate. One day was an unrepresentative sample: volume rises through the
window (about 22,000 a day in the last week of the pull, 54,000 at the busiest stretch,
14,000 on the sampled day). Lesson: a one-day extrapolation under-sizes a growing series;
sample at least three days spread over the window.

**Fetch time.** About 1.25M logs at about 1,800 logs/s is about 12 minutes of query
time. 12 months is about 21M blocks, which is about 420 calls of 50,000 blocks per
event per contract for disputes and settles. Kill condition (3 h) is **not met**.
Continue.

**Consequence for storage.** About 3.2 KB per raw log would make about 4 GB for
proposals. Proposals are therefore reduced to compact rows while fetching (no
proposer address, no question text): block, tx hash, log index, requester, request key
hash, proposed price. Disputes and settles are few and are kept in full in
`data/raw_local/` (ignored by git) plus a stripped publishable CSV.
