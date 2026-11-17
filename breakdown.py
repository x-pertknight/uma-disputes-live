"""Breakdowns of the overturned set: by settled value, by event cluster, by requester,
plus the key-integrity check.

Price scale: every price here is the raw int256 from the logs. Polymarket requests use
1e18 as the unit: 0 = first outcome, 1e18 = second outcome, 0.5e18 = the midpoint answer
("50-50 / unknown"). min int256 = "too early" (a reset, never counted as overturned).
The proposed price comes from the DisputePrice event, so these tables cover all 12 months.
"""
import collections
import datetime as dt
import re

import decode
from metrics import TOO_EARLY

ONE = 10 ** 18
HALF = ONE // 2
GAP_SECONDS = 600       # disputes at most 10 minutes apart can belong to one cluster
STOP = {"will", "team", "total", "spread", "over", "under", "game", "match", "first", "second",
        "half", "points", "goals", "assists", "score", "winner", "other", "more", "than", "with",
        "from", "that", "this", "have", "been", "series", "round", "quarter", "win", "wins"}


def matured(disputes, head_ts, seconds=7 * 86400):
    """Disputes at least 7 days old at the last block. Monthly tables use only these, so a young
    month is not made of the fast votes alone."""
    return {k: d for k, d in disputes.items() if d["time"] <= head_ts - seconds}


def month_of(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m")


def price_class(proposed, settled):
    """How an overturned request moved. Only call for decided requests."""
    if settled == proposed:
        return "upheld"
    if settled == HALF:
        return "to_midpoint"
    if proposed == HALF:
        return "from_midpoint"
    if {proposed, settled} == {0, ONE}:
        return "flipped"
    return "other"


def periods(disputes, head_ts):
    """Yield (label, predicate on dispute time): each month, plus the last 90 days."""
    months = sorted({month_of(d["time"]) for d in disputes.values()})
    for m in months:
        yield m, (lambda t, m=m: month_of(t) == m)
    yield "last 90d", (lambda t: t >= head_ts - 90 * 86400)


def value_classes(disputes, settles, head_ts):
    rows = []
    for label, inside in periods(disputes, head_ts):
        c = collections.Counter()
        for k, d in disputes.items():
            s = settles.get(k)
            if inside(d["time"]) and s and s["price"] != TOO_EARLY:
                c["decided"] += 1
                c[price_class(d["price"], s["price"])] += 1
                if price_class(d["price"], s["price"]) == "flipped":
                    c["flip_0_to_1" if d["price"] == 0 else "flip_1_to_0"] += 1
        over = c["decided"] - c["upheld"]
        rows.append({"period": label, "decided": c["decided"], "overturned": over,
                     "flipped_to_opposite": c["flipped"], "flip_0_to_1e18": c["flip_0_to_1"],
                     "flip_1e18_to_0": c["flip_1_to_0"], "to_midpoint": c["to_midpoint"],
                     "from_midpoint": c["from_midpoint"], "other": c["other"]})
    return rows


# ---- clusters -------------------------------------------------------------

def tokens(anc):
    title = decode.parse_question(anc)[0]
    return {w for w in re.findall(r"[^\W\d_]{4,}", title) if w[0].isupper() and w.lower() not in STOP}


def cluster_ids(disputes, need_shared_word=True):
    """Single-linkage clusters: same requester, within 10 minutes, a shared capitalised
    title word (team or player name). Returns {key: cluster number}."""
    items = sorted(disputes.items(), key=lambda kv: kv[1]["time"])
    parent = list(range(len(items)))
    toks = [tokens(d["ancillary"]) for _, d in items]

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (_, di) in enumerate(items):
        j = i - 1
        while j >= 0 and di["time"] - items[j][1]["time"] <= GAP_SECONDS:
            if items[j][1]["requester"] == di["requester"] and (toks[i] & toks[j] or not need_shared_word):
                parent[find(i)] = find(j)
            j -= 1
    return {k: find(i) for i, (k, _) in enumerate(items)}


def cluster_table(disputes, settles, head_ts):
    """Per period: overturn rate per request and per cluster.
    Rule: a cluster counts as overturned when MORE than half of its decided requests were
    overturned; an exact tie counts as upheld. `per_cluster_pct_ties_overturned` counts ties as
    overturned instead, to show how much the rule matters."""
    cid = cluster_ids(disputes)
    loose = cluster_ids(disputes, need_shared_word=False)   # sensitivity: time and requester only
    first = {}
    for k, d in disputes.items():
        c = cid[k]
        first[c] = min(first.get(c, d["time"]), d["time"])
    rows = []
    for label, inside in periods(disputes, head_ts):
        dec = collections.defaultdict(lambda: [0, 0])   # cluster -> [decided, overturned]
        for k, d in disputes.items():
            s = settles.get(k)
            if s and s["price"] != TOO_EARLY and inside(first[cid[k]]):
                dec[cid[k]][0] += 1
                dec[cid[k]][1] += s["price"] != d["price"]
        n, o = sum(v[0] for v in dec.values()), sum(v[1] for v in dec.values())
        maj = sum(1 for v in dec.values() if v[1] * 2 > v[0])
        maj_ties = sum(1 for v in dec.values() if v[1] * 2 >= v[0])
        big = sum(v[1] for v in dec.values() if v[0] >= 5)
        loose_rate = _cluster_rate(disputes, settles, loose, inside)
        rows.append({"period": label, "decided_requests": n, "overturned_requests": o,
                     "per_request_pct": _pct(o, n), "clusters": len(dec), "clusters_mostly_overturned": maj,
                     "per_cluster_pct": _pct(maj, len(dec)), "largest_cluster": max((v[0] for v in dec.values()), default=0),
                     "overturns_in_clusters_of_5plus_pct": _pct(big, o),
                     "per_cluster_pct_ties_overturned": _pct(maj_ties, len(dec)),
                     "per_cluster_pct_time_only_linking": loose_rate})
    return rows


def _cluster_rate(disputes, settles, cid, inside):
    """Share of clusters (by first dispute time) whose decided requests are mostly overturned."""
    first, dec = {}, collections.defaultdict(lambda: [0, 0])
    for k, d in disputes.items():
        first[cid[k]] = min(first.get(cid[k], d["time"]), d["time"])
    for k, d in disputes.items():
        s = settles.get(k)
        if s and s["price"] != TOO_EARLY and inside(first[cid[k]]):
            dec[cid[k]][0] += 1
            dec[cid[k]][1] += s["price"] != d["price"]
    return _pct(sum(1 for v in dec.values() if v[1] * 2 > v[0]), len(dec))


def _pct(a, b):
    return round(100 * a / b, 1) if b else None


# ---- requester ------------------------------------------------------------

def by_requester(disputes, settles, head_ts, labels):
    rows = []
    for label, inside in (("last 90d", lambda t: t >= head_ts - 90 * 86400), ("12 months", lambda t: True)):
        c = collections.defaultdict(collections.Counter)
        for k, d in disputes.items():
            if not inside(d["time"]):
                continue
            r, s = c[d["requester"]], settles.get(k)
            r["disputes"] += 1
            if s and s["price"] == TOO_EARLY:
                r["resets"] += 1
            elif s:
                r["decided"] += 1
                r["overturned"] += s["price"] != d["price"]
        for rq, r in sorted(c.items(), key=lambda kv: -kv[1]["disputes"]):
            rows.append({"period": label, "requester": rq, "what_it_is": labels.get(rq, "unlabelled"),
                         "disputes": r["disputes"], "resets": r["resets"], "decided": r["decided"],
                         "overturned": r["overturned"], "overturn_pct": _pct(r["overturned"], r["decided"])})
    return rows


# ---- key integrity --------------------------------------------------------

def key_integrity(raw_settles, raw_disputes, props, disputes):
    """No key with two Settle or two DisputePrice logs, and proposed prices agree."""
    sc = collections.Counter((r["contract"], decode.decode_log("Settle", r["log"])["key"]) for r in raw_settles)
    dc = collections.Counter((r["contract"], decode.decode_log("DisputePrice", r["log"])["key"]) for r in raw_disputes)
    both = [k for k in disputes if k in props]
    mismatch = sum(1 for k in both if props[k]["price"] != disputes[k]["price"])
    return {"keys_with_2plus_settle_logs": sum(1 for v in sc.values() if v > 1),
            "keys_with_2plus_dispute_logs": sum(1 for v in dc.values() if v > 1),
            "settle_keys": len(sc), "dispute_keys": len(dc),
            "disputes_with_a_proposal_row_in_window": len(both),
            "proposed_price_differs_between_proposal_and_dispute_event": mismatch}


# ---- first vs later disputes, proposer concentration ------------------------

def by_dispute_order(disputes, settles, head_ts, adapters):
    """First dispute on a question vs second or later, for requesters whose verified source
    resets the market on the first dispute (`adapters`, from data/adapter_reset_logic.json).
    Order = by request timestamp among disputes on the same question text and requester inside
    our 12 months of logs, so a question first disputed earlier shows up here as a first dispute.
    Matured cohort only. Shares are of settled disputes."""
    old = matured({k: d for k, d in disputes.items() if d["requester"] in adapters}, head_ts)
    seq = collections.defaultdict(list)
    for k, d in disputes.items():
        if d["requester"] in adapters:
            seq[d["qhash"]].append((d["req_ts"], k))
    later = {k for v in seq.values() for _, k in sorted(v)[1:]}
    rows = []
    for label, inside in periods(disputes, head_ts):
        c = {"first": collections.Counter(), "later": collections.Counter()}
        for k, d in old.items():
            s = settles.get(k)
            if not inside(d["time"]) or not s:
                continue
            g = c["later" if k in later else "first"]
            g["settled"] += 1
            g["reset" if s["price"] == TOO_EARLY else ("overturned" if s["price"] != d["price"] else "upheld")] += 1
        row = {"period": label}
        for name, g in c.items():
            row.update({f"{name}_settled": g["settled"], f"{name}_reset_pct": _pct(g["reset"], g["settled"]),
                        f"{name}_overturned_pct": _pct(g["overturned"], g["settled"]),
                        f"{name}_upheld_pct": _pct(g["upheld"], g["settled"]),
                        f"{name}_decided_overturn_pct": _pct(g["overturned"], g["overturned"] + g["upheld"]),
                        f"{name}_decided": g["overturned"] + g["upheld"]})
        rows.append(row)
    return rows


def concentration(disputes, settles, head_ts):
    """Aggregate only, by dispute month (matured cohort): the share of overturned requests held by
    the three proposers with the most, and the share of all disputes raised by the three disputers
    with the most. Wallet addresses are used to count and are never written out."""
    old = matured(disputes, head_ts)
    rows = []
    for label, inside in periods(disputes, head_ts):
        over, disp = collections.Counter(), collections.Counter()
        for k, d in old.items():
            if not inside(d["time"]):
                continue
            disp[d["disputer"]] += 1
            s = settles.get(k)
            if s and s["price"] != TOO_EARLY and s["price"] != d["price"]:
                over[d["proposer"]] += 1
        rows.append({"period": label, "disputes": sum(disp.values()), "distinct_disputers": len(disp),
                     "top3_disputers_share_of_disputes_pct": _pct(sum(v for _, v in disp.most_common(3)), sum(disp.values())),
                     "overturned": sum(over.values()), "distinct_proposers_overturned": len(over),
                     "top3_proposers_share_of_overturns_pct": _pct(sum(v for _, v in over.most_common(3)), sum(over.values()))})
    return rows


def requester_by_month(disputes, settles, labels, min_disputes=5):
    """Overturn rate per requester contract and dispute month (rows with few disputes dropped)."""
    c = collections.defaultdict(collections.Counter)
    for k, d in disputes.items():
        g, s = c[(month_of(d["time"]), d["requester"])], settles.get(k)
        g["disputes"] += 1
        if s and s["price"] == TOO_EARLY:
            g["resets"] += 1
        elif s:
            g["decided"] += 1
            g["overturned"] += s["price"] != d["price"]
    return [{"month": m, "requester": rq, "what_it_is": labels.get(rq, "unlabelled"), "disputes": g["disputes"],
             "resets": g["resets"], "decided": g["decided"], "overturned": g["overturned"],
             "overturn_pct": _pct(g["overturned"], g["decided"])}
            for (m, rq), g in sorted(c.items()) if g["disputes"] >= min_disputes]


def outcome_shares(disputes, settles, head_ts):
    """Of the settled disputes in each period (matured cohort): share reset ("too early"),
    overturned, upheld (proposer confirmed). `to_midpoint` is the part of settled disputes whose
    final price is the 0.5e18 midpoint; it is reported on its own and is not an error count.
    Disputes under 7 days old are counted in `younger_than_7d` and left out of every share."""
    old = matured(disputes, head_ts)
    rows = []
    for label, inside in list(periods(disputes, head_ts)) + [("12 months", lambda t: True)]:
        c = collections.Counter()
        for k, d in disputes.items():
            if not inside(d["time"]):
                continue
            s = settles.get(k)
            if k not in old:
                c["young"] += 1
            elif not s:
                c["no_settle"] += 1
            else:
                c["settled"] += 1
                c["reset" if s["price"] == TOO_EARLY else ("overturned" if s["price"] != d["price"] else "upheld")] += 1
                c["to_midpoint"] += s["price"] == HALF
        n = c["settled"]
        rows.append({"period": label, "settled_disputes": n, "reset": c["reset"], "overturned": c["overturned"],
                     "upheld": c["upheld"], "reset_pct": _pct(c["reset"], n), "overturned_pct": _pct(c["overturned"], n),
                     "upheld_pct": _pct(c["upheld"], n), "decided_overturn_pct": _pct(c["overturned"], c["overturned"] + c["upheld"]),
                     "settled_at_midpoint": c["to_midpoint"], "settled_at_midpoint_pct": _pct(c["to_midpoint"], n),
                     "mature_without_settle": c["no_settle"], "younger_than_7d": c["young"]})
    return rows


def line_bursts(disputes, settles, head_ts, types, first_month="2026-07"):
    """Decided betting-line disputes from `first_month`, grouped into bursts (same requester, within 10
    minutes, no title test). Returns counts, the largest burst, and the overturn rate without bursts of 10+."""
    old = matured(disputes, head_ts)
    cid = cluster_ids(old, need_shared_word=False)
    g = collections.defaultdict(list)
    for k, d in old.items():
        s = settles.get(k)
        if types[k] == "line" and s and s["price"] != TOO_EARLY and month_of(d["time"]) >= first_month:
            g[cid[k]].append((d["time"], s["price"] != d["price"]))
    allv = [x for v in g.values() for x in v]
    big = max(g.values(), key=len)
    small = [x for v in g.values() if len(v) < 10 for x in v]
    return {"decided_lines": len(allv), "bursts": len(g), "overturned_pct": _pct(sum(b for _, b in allv), len(allv)),
            "largest_burst": len(big), "largest_burst_day": month_day(big[0][0]), "largest_burst_overturned": sum(b for _, b in big),
            "rate_without_bursts_10plus_pct": _pct(sum(b for _, b in small), len(small)), "decided_without_bursts_10plus": len(small)}


def month_day(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")


def later_pooled(order_rows, split="2026-07"):
    """Later disputes, overturned of decided, pooled before and from `split` (months only)."""
    out = {}
    for name, rows in (("before", [r for r in order_rows if r["period"][:2] == "20" and r["period"] < split]),
                       ("after", [r for r in order_rows if r["period"][:2] == "20" and r["period"] >= split])):
        n = sum(r["later_decided"] for r in rows)
        o = sum(round(r["later_decided_overturn_pct"] * r["later_decided"] / 100) for r in rows if r["later_decided"])
        out[name] = {"decided": n, "overturned": o, "pct": _pct(o, n)}
    return out
