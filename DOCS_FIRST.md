# DOCS_FIRST: what UMA documents vs what this study must measure

Read on 16 Nov 2026, before any log was fetched. Local copies of every page were
saved outside the repo during reading. Facts marked **[source-code]** come from the
contract source on GitHub, not from the prose docs.

## 1. Documented

### 1.1 The request, propose, dispute, settle flow
| Step | What the docs / source say | Source |
|---|---|---|
| Request | A requester contract calls `requestPrice` with an identifier, timestamp and ancillary data. It can set a reward, bond, liveness. Event: `RequestPrice`. | Quick Start; OOv2 source |
| Propose | A proposer posts a price and a bond. "Each request can only be proposed once." Proposal enters a challenge period (liveness). Event: `ProposePrice`. | How UMA's oracle works; OOv2 source |
| Dispute | Anyone can dispute during liveness. "Each proposal can only be disputed once." The dispute is forwarded to the DVM. Event: `DisputePrice`. | How UMA's oracle works |
| No dispute | Proposal is settled as correct after liveness. | How UMA's oracle works |
| DVM vote | Commit period 24h, reveal period 24h. Rounds transition at 24:00 UTC. A dispute must be at least 4h old to enter a round. Needs a 65% majority of staked UMA, otherwise the vote does not resolve. | How UMA's oracle works |
| Settle | Anyone calls `settle` after liveness (undisputed) or after the DVM answer exists (disputed). Event: `Settle` carries the final `price` and `payout`. Settlement is a separate transaction, so it can lag the DVM answer. | OOv2 source `_settle` **[source-code]** |
| Request states | Invalid, Requested, Proposed, Expired, Disputed, Resolved, Settled. | `OptimisticOracleV2Interface.sol` **[source-code]** |
| Overturn | In `_settle`, for a Resolved request: `disputeSuccess = resolvedPrice != proposedPrice`. The disputer is paid when the proposal was wrong. | OOv2 source **[source-code]** |
| "Too early" | `TOO_EARLY_RESPONSE = type(int256).min`. A proposer cannot propose it. It can only come back from the DVM, as a reset. | OOv2 source **[source-code]** |
| Headline claim | "The optimistic oracle resolves ... currently 99.8%" of requests without dispute. This is across all UMA, all chains, no date. | How UMA's oracle works |

### 1.2 Event signatures (identical in both contracts)
`ManagedOptimisticOracleV2` inherits `OptimisticOracleV2`, and its own new events
(`CustomBondSet`, `CustomLivenessSet`, `RequestRulesUpdated`, whitelist updates) are
admin events we do not need. **[source-code]**

```
ProposePrice(address indexed requester, address indexed proposer, bytes32 identifier,
             uint256 timestamp, bytes ancillaryData, int256 proposedPrice,
             uint256 expirationTimestamp, address currency)
DisputePrice(address indexed requester, address indexed proposer, address indexed disputer,
             bytes32 identifier, uint256 timestamp, bytes ancillaryData, int256 proposedPrice)
Settle(address indexed requester, address indexed proposer, address indexed disputer,
       bytes32 identifier, uint256 timestamp, bytes ancillaryData, int256 price, uint256 payout)
```
Request key = (requester, identifier, timestamp, ancillaryData). `requester` is
indexed (a topic). The other three key fields sit in the data section, and
`ancillaryData` is a dynamic `bytes`, so decoding must follow ABI offsets.
Source: `UMAprotocol/protocol`, `optimistic-oracle-v2/interfaces/OptimisticOracleV2Interface.sol`.

### 1.3 Contract addresses (Polygon, chain id 137)
| Contract | Address | Where it comes from |
|---|---|---|
| OptimisticOracleV2 | `0xee3afe347d5c74317041e2618c49534daf887c24` | UMA's own network file `packages/core/networks/137.json` (linked from docs.uma.xyz "Network addresses" for Polygon) |
| ManagedOptimisticOracleV2 (proxy) | `0x2C0367a9DB231dDeBd88a94b4f6461a6e47C58B1` | UMA docs, "Proposing Programmatically" page; UMIP-189 ("approve the ManagedOptimisticOracleV2 at 0x2C03..."); UMAprotocol/managed-oracle runbook and manifest |

Not used: `OptimisticOracleV3` (`0x5953...AD3D`, same file), excluded as in the Dune
dashboard. The legacy v1 `OptimisticOracle` (`0xBb1A...Da49`) is also in the file and
is also outside the stated universe.

**Open point on the managed address.** It is *not* in `networks/137.json` and not on
the docs "Network addresses" page. It is confirmed by three UMA-owned places (docs
page, UMIP-189, managed-oracle repo), so I take it as official, but it is not in the
single list the brief names. Before the pull I will check that both addresses have
contract code and that the first returned log matches the event topic.

### 1.4 UMIP that introduced the managed oracle
UMIP-189, "Approve new ManagedOptimisticOracleV2 Deployment" (created 29 Jul 2025).
A modified OOv2 for a single integration (Polymarket), with an owner and request
managers who can set bond, liveness and the proposer whitelist. Disputes still go to
the DVM. It was registered on the Polygon Registry. A web search snippet says it
passed on 6 Aug 2025; I have not confirmed that date from a primary source.
Consequence: the managed oracle has no history before about Aug 2025, so the
12-month dispute window is complete for it but only part of it applies.

### 1.5 Proposer whitelist (context, not used in metrics)
Managed requests can restrict who proposes (default whitelist: 5+ proposals and >95%
accuracy over 6 months, per UMA docs). This is a reason the managed contract's
dispute rate may differ from OOv2's. Disputing stays permissionless.

## 2. Not documented: must be measured
| Question | Why the docs do not answer it |
|---|---|
| Dispute rate on Polygon OOv2 + Managed, last 30 / 90 days | Docs give only an all-UMA 99.8% figure with no window. |
| Overturn rate among decided disputes | Not published. Small counts, so wide error. |
| Time from dispute to `Settle` | Docs give the vote schedule, not the delay to the settle transaction. Someone must call `settle`. |
| Disputes open now | Needs live logs. |
| Volume of proposals per 90 days | Brief says "over a million lifetime"; the recent rate is unknown. |
| Whether RPC returns complete ranges | Provider behaviour, not UMA's. Checked by overlapping re-queries. |
| Whether the Dune dashboard's definitions match mine | Compared on two past months at validation. |

## 3. Things I expect to catch me (to test, not assume)
- **Polymarket reset behaviour is not in the UMA docs I read.** I believe the
  Polymarket adapter re-requests after a first dispute, which would create a new key
  (new timestamp). If so, one market can produce two proposals and the dispute rate
  per proposal is not per market. The study metric stays per request, as defined.
- **Right-censoring.** A DVM vote takes at least about 2 days, so recent disputes have
  no `Settle` yet. The 30-day overturn rate uses only the decided subset and will be
  biased toward whatever resolves fast. State it next to the number.
- **Settle lag.** A dispute can be resolved by the DVM and still show as "open" because
  nobody has called `settle`. "Open" here means no `Settle` event, not "DVM undecided".
- **SQL points to mirror or flag.** In `q1`, windows filter on proposal time, and
  decided/overturned need a `Settle`. `q3` includes resets and flags them. Mirror as is;
  any deviation is listed in the README.
- **Ancillary data is bytes.** Decode as UTF-8 with `errors="replace"`. Do not assume
  it is always valid text.

## 4. Sources
- https://docs.uma.xyz/protocol-overview/how-does-umas-oracle-work
- https://docs.uma.xyz/developers/optimistic-oracle and its Quick Start page
- https://docs.uma.xyz/developers/managedoptimisticoraclev2 (and "Proposing Programmatically", "Default Proposer Whitelist")
- https://docs.uma.xyz/resources/network-addresses
- https://raw.githubusercontent.com/UMAprotocol/protocol/master/packages/core/networks/137.json
- `OptimisticOracleV2.sol` and `OptimisticOracleV2Interface.sol` in UMAprotocol/protocol (`packages/core/contracts/optimistic-oracle-v2/`)
- `ManagedOptimisticOracleV2.sol` and `script/production/README.md` in UMAprotocol/managed-oracle
- https://discourse.uma.xyz/t/umip-189-approve-new-managedoptimisticoraclev2-deployment/2229
