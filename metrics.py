"""Metrics mirroring study4-sql q1..q4, plus the matured cohort and requester split.

Definitions (same as the Dune dashboard):
  request key         (requester, identifier, timestamp, ancillaryData); we also keep
                      the contract in the join, which only matters if one key appeared twice
  dispute rate        disputed requests / proposed requests
  decided             disputed, has a Settle event, settled price is not "too early"
  overturned          decided and settled price differs from the proposed price
  "open"              disputed and no Settle event yet (the vote is not read)
All rates are per request, not per market.
"""
import collections
import csv
import json
import math

import decode
import fetch
import times

TOO_EARLY = -(2 ** 255)          # min int256: the DVM's reset answer
MATURE_SECONDS = 7 * 86400       # a dispute counts as matured once it is 7 days old
DAY = 86400


def percentile(values, q):
    """Linear-interpolated percentile (Dune's approx_percentile differs slightly)."""
    v = sorted(values)
    if not v:
        return None
    pos = (len(v) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def load_proposals(cutoff_block):
    """(contract, key) -> row, for proposals at or after cutoff_block. Counts duplicates."""
    rows, dups = {}, 0
    with open(f"{fetch.RAW}/proposals.csv") as f:
        for r in csv.DictReader(f):
            if int(r["block"]) < cutoff_block:
                continue
            k = (r["contract"], r["key"])
            if k in rows:
                dups += 1
                continue
            rows[k] = {"block": int(r["block"]), "requester": r["requester"],
                       "qhash": r["qhash"], "req_ts": int(r["req_ts"]), "price": int(r["price"])}
    return rows, dups


def load_disputes():
    """Decoded disputes with block time, de-duplicated on (contract, key)."""
    raw = fetch.read_jsonl("disputes_raw")
    ts = times.get({int(r["log"]["blockNumber"], 16) for r in raw})
    out, dups = {}, 0
    for r in raw:
        d = decode.decode_log("DisputePrice", r["log"])
        k = (r["contract"], d["key"])
        if k in out:
            dups += 1
            continue
        d.update(contract=r["contract"], time=ts[d["block"]])
        out[k] = d
    return out, dups


def load_settles():
    """(contract, key) -> decoded Settle with block time."""
    raw = fetch.read_jsonl("settles_raw")
    ts = times.get({int(r["log"]["blockNumber"], 16) for r in raw})
    out = {}
    for r in raw:
        d = decode.decode_log("Settle", r["log"])
        d.update(contract=r["contract"], time=ts[d["block"]])
        out[(r["contract"], d["key"])] = d
    return out


def window_rates(label, props, disputes, settles, head_ts):
    """One row of the rates table for the proposals in `props` (already window-filtered)."""
    n = len(props)
    disp = [(k, disputes[k]) for k in props if k in disputes]
    row = {"window": label, "proposals": n, "disputes": len(disp)}
    row["dispute_rate_pct"] = round(100 * len(disp) / n, 4) if n else None
    for name, only_mature in (("all", False), ("matured", True)):
        decided = over = resets = unsettled = 0
        for k, d in disp:
            if only_mature and d["time"] > head_ts - MATURE_SECONDS:
                continue
            s = settles.get(k)
            if s is None:
                unsettled += 1
            elif s["price"] == TOO_EARLY:
                resets += 1
            else:
                decided += 1
                over += s["price"] != props[k]["price"]
        row[f"{name}_decided"], row[f"{name}_overturned"] = decided, over
        row[f"{name}_resets"], row[f"{name}_no_settle"] = resets, unsettled
        row[f"{name}_overturn_pct"] = round(100 * over / decided, 1) if decided else None
    row["immature_excluded"] = sum(1 for _, d in disp if d["time"] > head_ts - MATURE_SECONDS)
    return row


def open_disputes(disputes, settles, head_ts, days=30):
    """Disputes from the last `days` days with no Settle event yet (q2)."""
    rows = []
    for k, d in disputes.items():
        if d["time"] >= head_ts - days * DAY and k not in settles:
            rows.append({"key": k, "oracle": d["contract"], "disputed_at": d["time"],
                         "hours_open": round((head_ts - d["time"]) / 3600, 1),
                         "question": decode.question_text(d["ancillary"])})
    return sorted(rows, key=lambda r: -r["disputed_at"])


def settle_hours_by_month(disputes, settles):
    """Hours from dispute to Settle, grouped by dispute month (q3). Pass the matured disputes.
    `no_settle_yet` counts disputes of that month with no Settle log, which the hours cannot include."""
    import datetime as dt
    groups, open_n = collections.defaultdict(list), collections.Counter()
    for k, d in disputes.items():
        month = dt.datetime.fromtimestamp(d["time"], dt.timezone.utc).strftime("%Y-%m")
        s = settles.get(k)
        if s:
            groups[month].append(((s["time"] - d["time"]) / 3600, s["price"] == TOO_EARLY))
        else:
            open_n[month] += 1
    out = []
    for m in sorted(groups):
        hrs = [h for h, _ in groups[m]]
        out.append({"month": m, "settled_disputes": len(hrs), "resets": sum(r for _, r in groups[m]),
                    "median_hours": round(percentile(hrs, .5), 1), "p90_hours": round(percentile(hrs, .9), 1),
                    "min_hours": round(min(hrs), 1), "max_settled_hours": round(max(hrs), 1),
                    "no_settle_yet": open_n[m]})
    return out


def stuck_disputes(disputes, settles, head_ts, types, limit=10):
    """Matured disputes with no Settle log, longest open first (requester contract, not wallets)."""
    rows = [{"oracle": d["contract"], "requester": d["requester"], "disputed_at": d["time"],
             "hours_open": round((head_ts - d["time"]) / 3600, 1), "market_type": types[k]}
            for k, d in disputes.items() if k not in settles]
    return sorted(rows, key=lambda r: -r["hours_open"])[:limit], len(rows)


def overturn_by_month(disputes, settles):
    """Per dispute month: resets, decided, overturned. The proposed price comes from the
    DisputePrice event itself, so this covers all 12 months, not just the 90-day proposals."""
    import datetime as dt
    g = collections.defaultdict(lambda: collections.Counter())
    for k, d in disputes.items():
        c = g[dt.datetime.fromtimestamp(d["time"], dt.timezone.utc).strftime("%Y-%m")]
        c["disputes"] += 1
        s = settles.get(k)
        if s is None:
            c["no_settle"] += 1
        elif s["price"] == TOO_EARLY:
            c["resets"] += 1
        else:
            c["decided"] += 1
            c["overturned"] += s["price"] != d["price"]
    return [{"month": mo, "disputes": c["disputes"], "no_settle_yet": c["no_settle"], "resets": c["resets"],
             "decided": c["decided"], "overturned": c["overturned"],
             "overturn_pct": round(100 * c["overturned"] / c["decided"], 1) if c["decided"] else None}
            for mo, c in sorted(g.items())]


def monthly_counts(disputes):
    """Disputes per UTC calendar month and contract, for the Dune comparison."""
    import datetime as dt
    c = collections.Counter()
    for (contract, _), d in disputes.items():
        c[(dt.datetime.fromtimestamp(d["time"], dt.timezone.utc).strftime("%Y-%m"), contract)] += 1
    return [{"month": m, "oracle": o, "disputes": n} for (m, o), n in sorted(c.items())]


def daily_disputes(disputes, head_ts, days=90):
    """Disputes per UTC day and contract over the last `days` days (q4)."""
    import datetime as dt
    c = collections.Counter()
    for (contract, _), d in disputes.items():
        if d["time"] >= head_ts - days * DAY:
            c[(dt.datetime.fromtimestamp(d["time"], dt.timezone.utc).strftime("%Y-%m-%d"), contract)] += 1
    return [{"day": day, "oracle": o, "disputes": n} for (day, o), n in sorted(c.items())]


def requester_split(props, disputes, top=5):
    """Share of proposals and of disputed requests by requester contract (top N + other)."""
    p = collections.Counter(r["requester"] for r in props.values())
    d = collections.Counter(props[k]["requester"] for k in props if k in disputes)
    rows = []
    for rq, n in p.most_common(top):
        rows.append({"requester": rq, "proposals": n, "disputes": d.get(rq, 0)})
    rest = [rq for rq in p if rq not in {r["requester"] for r in rows}]
    rows.append({"requester": "other", "proposals": sum(p[r] for r in rest), "disputes": sum(d.get(r, 0) for r in rest)})
    tp, td = sum(p.values()), sum(d.values())
    for r in rows:
        r["proposal_share_pct"] = round(100 * r["proposals"] / tp, 2) if tp else None
        r["dispute_share_pct"] = round(100 * r["disputes"] / td, 2) if td else None
        r["dispute_rate_pct"] = round(100 * r["disputes"] / r["proposals"], 4) if r["proposals"] else None
    return rows


def rerequest_stats(props, disputes):
    """How many disputed requests were followed by a later request for the same question."""
    by_q = collections.defaultdict(list)
    for r in props.values():
        by_q[r["qhash"]].append(r["req_ts"])
    disp = [k for k in props if k in disputes]
    again = sum(1 for k in disp if any(t > props[k]["req_ts"] for t in by_q[props[k]["qhash"]]))
    multi = sum(1 for v in by_q.values() if len(v) > 1)
    return {"disputed_requests": len(disp), "followed_by_new_request": again,
            "questions": len(by_q), "questions_with_2plus_requests": multi, "requests": len(props)}
