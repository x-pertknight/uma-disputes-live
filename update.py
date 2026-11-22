"""One command: fetch new logs, verify, rebuild the tables, rewrite the README numbers.

    python3 update.py            # incremental; safe to run repeatedly
    python3 update.py --no-verify   # skip the overlap re-queries
"""
import json
import sys
import time

import breakdown
import fetch
import markets
import metrics
import report
import sync
import verify

DAY = 86400


def structural_checks(props, disputes, settles, pdups, ddups):
    """S1/S2 from PREDICTIONS.md plus duplicate counts."""
    fastest = min(((settles[k]["time"] - d["time"]) / 3600 for k, d in disputes.items() if k in settles),
                  default=None)
    return {
        "duplicate_proposal_keys": pdups,
        "duplicate_dispute_keys": ddups,
        "settles_without_matching_dispute": sum(1 for k in settles if k not in disputes),
        "disputes_in_window_without_proposal_row": sum(1 for k in disputes if k not in props),
        "fastest_dispute_to_settle_hours": None if fastest is None else round(fastest, 1),
    }


def requester_labels():
    """What each requester contract is (data/requester_labels.json, from Sourcify and Polymarket docs)."""
    return {a: v["what_it_is"] for a, v in json.load(open("data/requester_labels.json")).items()}


def outcome_pools(rows):
    """Pooled outcome shares of all settled disputes: Nov 2025 to Jun 2026, and July 2026 onward."""
    out = {}
    for name, sel in (("before", lambda p: p < "2026-07"), ("after", lambda p: p >= "2026-07")):
        rs = [r for r in rows if r["period"][:2] == "20" and sel(r["period"])]
        n = sum(r["settled_disputes"] for r in rs)
        out[name] = {"n": n, **{f"{k}_pct": round(100 * sum(r[k] for r in rs) / n, 1) for k in ("reset", "overturned", "upheld")}}
    return out


def settle_pool(old, settles):
    """Median and p90 hours from dispute to Settle over all matured, settled disputes (12 months)."""
    hrs = [(settles[k]["time"] - d["time"]) / 3600 for k, d in old.items() if k in settles]
    return {"n": len(hrs), "median": round(metrics.percentile(hrs, .5), 1), "p90": round(metrics.percentile(hrs, .9), 1)}


def order_excluded(old, settles, adapters):
    """Settled matured disputes on requester contracts outside the first-vs-later table, per requester."""
    import collections
    c = collections.Counter(d["requester"] for k, d in old.items() if k in settles and d["requester"] not in adapters)
    return {"total": sum(c.values()), "by_requester": c.most_common()}


def build(state, verification):
    head, head_ts = state["head_block"], state["head_ts"]
    cut90 = fetch.block_at(head_ts - 90 * DAY, head)
    cut30 = fetch.block_at(head_ts - 30 * DAY, head)
    props, pdups = metrics.load_proposals(cut90)
    props30 = {k: v for k, v in props.items() if v["block"] >= cut30}
    disputes, ddups = metrics.load_disputes()
    settles = metrics.load_settles()
    t90 = head_ts - 90 * DAY
    recent = {k: d for k, d in disputes.items() if d["time"] >= t90}
    old = breakdown.matured(disputes, head_ts)          # monthly tables use disputes at least 7 days old
    types = markets.type_of(disputes)
    checked = json.load(open("data/adapter_reset_logic.json"))
    adapters = {a for a, v in checked.items() if isinstance(v, dict) and v["confirmed"]}
    cell = markets.cells(old, settles, types)
    mix, base = markets.mix_table(cell)
    ctx = {
        "head_block": head, "head_ts": head_ts, "run_ts": int(time.time()),
        "mix": mix, "mix_base": base, "unclassified_pct": markets.unclassified_share(types), "all_disputes": len(types),
        "adapter_listed": sum(1 for a in adapters if "(listed in Polymarket" in requester_labels().get(a, "")),
        "pooled_adj_base": markets.pooled_adjusted(cell, markets.BASE_FIRST, markets.BASE_LAST),
        "pooled": {"base": markets.pooled(cell, markets.BASE_FIRST, markets.BASE_LAST),
                   "all": markets.pooled(cell, "0000-00", "9999-99"),
                   "after": markets.pooled(cell, "2026-07", "9999-99")},
        "pooled_adjusted": markets.pooled_adjusted(cell, "2026-07", "9999-99"),
        "type_base": markets.type_summary(cell, markets.BASE_FIRST, markets.BASE_LAST),
        "type_after": markets.type_summary(cell, "2026-07", "9999-99"),
        "labels": requester_labels(),
        "bursts": breakdown.line_bursts(disputes, settles, head_ts, types),
        "later_pooled": breakdown.later_pooled(breakdown.by_dispute_order(disputes, settles, head_ts, adapters)),
        "outcome_pools": outcome_pools(breakdown.outcome_shares(disputes, settles, head_ts)),
        "order_excluded": order_excluded(old, settles, adapters),
        "adapter_count": len(adapters),
        "disputes_by_adapter_pct": round(100 * sum(1 for d in disputes.values() if d["requester"] in adapters) / len(disputes), 1),
        "concentration": breakdown.concentration(disputes, settles, head_ts),
        "rates": [metrics.window_rates("30d", props30, disputes, settles, head_ts),
                  metrics.window_rates("90d", props, disputes, settles, head_ts)],
        "split": metrics.requester_split(props, disputes),
        "rerequest": metrics.rerequest_stats(props, disputes),
        "open": [dict(o, market_type=types[o["key"]], venue=markets.venue(disputes[o["key"]]["ancillary"]))
                 for o in metrics.open_disputes(disputes, settles, head_ts)],
        "settle_months": metrics.settle_hours_by_month(old, settles),
        "stuck": metrics.stuck_disputes(old, settles, head_ts, types),
        "settle_pool": settle_pool(old, settles),
        "overturn_months": metrics.overturn_by_month(old, settles),
        "value_classes": breakdown.value_classes(old, settles, head_ts),
        "clusters": breakdown.cluster_table(old, settles, head_ts),
        "order": breakdown.by_dispute_order(disputes, settles, head_ts, adapters),
        "outcomes": breakdown.outcome_shares(disputes, settles, head_ts),
        "req_month": breakdown.requester_by_month(old, settles, requester_labels()),
        "by_requester": breakdown.by_requester(old, settles, head_ts, requester_labels()),
        "key_integrity": breakdown.key_integrity(fetch.read_jsonl("settles_raw"), fetch.read_jsonl("disputes_raw"), props, disputes),
        "daily": metrics.daily_disputes(disputes, head_ts),
        "monthly": metrics.monthly_counts(disputes),
        "checks": structural_checks(props, disputes, settles, pdups, ddups),
        "verification": verification,
        "daily_props": report.daily_proposals(props, cut90, head),
        "disputes_table": report.publishable_disputes(disputes, settles, types),
        "recent_disputes": len(recent),
    }
    return ctx


def write_outputs(ctx):
    d = "data"
    report.write_csv(f"{d}/rates.csv", ctx["rates"])
    report.write_csv(f"{d}/requester_split_90d.csv", ctx["split"])
    report.write_csv(f"{d}/open_disputes.csv", [dict({k: v for k, v in r.items() if k != "key"}, disputed_at=report.utc(r["disputed_at"])) for r in ctx["open"]])
    report.write_csv(f"{d}/time_to_settle_by_month.csv", ctx["settle_months"])
    report.write_csv(f"{d}/overturn_by_month.csv", ctx["overturn_months"])
    report.write_csv(f"{d}/overturn_by_value_class.csv", ctx["value_classes"])
    report.write_csv(f"{d}/outcome_shares_by_month.csv", ctx["outcomes"])
    report.write_csv(f"{d}/overturn_by_cluster.csv", ctx["clusters"])
    report.write_csv(f"{d}/overturn_by_requester.csv", ctx["by_requester"])
    report.write_csv(f"{d}/overturn_by_requester_month.csv", ctx["req_month"])
    report.write_csv(f"{d}/overturn_first_vs_later_dispute.csv", ctx["order"])
    report.write_csv(f"{d}/concentration_by_month.csv", ctx["concentration"])
    report.write_csv(f"{d}/market_type_by_month.csv", ctx["mix"])
    report.write_csv(f"{d}/daily_disputes_90d.csv", ctx["daily"])
    report.write_csv(f"{d}/monthly_disputes.csv", ctx["monthly"])
    report.write_csv(f"{d}/daily_proposals_90d.csv", ctx["daily_props"])
    report.write_csv(f"{d}/disputes.csv", ctx["disputes_table"])
    json.dump({"checks": ctx["checks"], "key_integrity": ctx["key_integrity"], "rerequest": ctx["rerequest"]}, open(f"{d}/checks.json", "w"), indent=1)
    report.chart_svg(ctx["daily"], "docs/disputes_per_day.svg")
    report.write_readme(report.numbers_block(ctx))
    report.write_scorecard(ctx)
    report.write_as_of(ctx["head_block"], ctx["head_ts"])


def main():
    state = sync.sync_all()
    verification = [] if "--no-verify" in sys.argv else verify.verify(state)
    ctx = build(state, verification)
    write_outputs(ctx)
    bad = [v for v in verification if not v["match"]]
    print("rates:", json.dumps(ctx["rates"], indent=1))
    print("checks:", ctx["checks"])
    print("verification samples:", len(verification), "mismatches:", len(bad))


if __name__ == "__main__":
    main()
