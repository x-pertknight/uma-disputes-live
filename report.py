"""Write derived CSVs, the chart, and the numbers block of README.md.

Nothing written here contains a wallet address: requesters are public adapter
contracts, question text is scrubbed (decode.question_text), and proposer/disputer
fields are never copied out of data/raw_local/.
"""
import bisect
import collections
import csv
import datetime as dt
import json
import os
import re

import metrics
import times

START, END = "<!-- NUMBERS:START -->", "<!-- NUMBERS:END -->"


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def utc(ts, fmt="%Y-%m-%d %H:%M"):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime(fmt)


def daily_proposals(props, first_block, last_block):
    """Proposals per UTC day and contract. Block time is interpolated between
    checkpoints 25,000 blocks apart (error of a few seconds at day edges)."""
    grid = list(range(first_block, last_block, 25000)) + [last_block]  # never past the head
    ts = times.get(grid)
    xs = sorted(ts)
    c = collections.Counter()
    for (contract, _), r in props.items():
        i = max(1, bisect.bisect_left(xs, r["block"]))
        x0, x1 = xs[i - 1], xs[min(i, len(xs) - 1)]
        t = ts[x0] + (ts[x1] - ts[x0]) * ((r["block"] - x0) / (x1 - x0 or 1))
        c[(utc(t, "%Y-%m-%d"), contract)] += 1
    return [{"day": d, "oracle": o, "proposals": n} for (d, o), n in sorted(c.items())]


def publishable_disputes(disputes, settles, types):
    rows = []
    for (contract, key), d in sorted(disputes.items(), key=lambda kv: kv[1]["block"]):
        s = settles.get((contract, key))
        rows.append({"oracle": contract, "request_key": key, "requester": d["requester"],
                     "dispute_block": d["block"], "dispute_time": utc(d["time"], "%Y-%m-%d %H:%M:%S"),
                     "dispute_tx": d["tx"], "log_index": d["log_index"], "proposed_price": d["price"],
                     "settle_block": s["block"] if s else "", "settle_tx": s["tx"] if s else "",
                     "settled_price": s["price"] if s else "",
                     "settled_too_early": (s["price"] == metrics.TOO_EARLY) if s else "",
                     "market_type": types[(contract, key)],
                     "question": metrics.decode.question_text(d["ancillary"])})
    return rows


def chart_svg(daily, path):
    """Stacked bars: disputes per day, OOv2 vs ManagedOOv2."""
    days = sorted({r["day"] for r in daily})
    by = {(r["day"], r["oracle"]): r["disputes"] for r in daily}
    tops = [by.get((d, "OOv2"), 0) + by.get((d, "ManagedOOv2"), 0) for d in days]
    ymax = max(tops + [1])
    w, h, left, bottom = 900, 280, 40, 30
    bw = (w - left - 10) / max(len(days), 1)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="sans-serif" font-size="11">',
             '<rect width="100%" height="100%" fill="white"/>']
    for i, d in enumerate(days):
        x = left + i * bw
        a, b = by.get((d, "ManagedOOv2"), 0), by.get((d, "OOv2"), 0)
        ha, hb = (h - bottom - 20) * a / ymax, (h - bottom - 20) * b / ymax
        parts.append(f'<rect x="{x:.1f}" y="{h-bottom-ha:.1f}" width="{bw*0.8:.1f}" height="{ha:.1f}" fill="#2a6fb0"><title>{d} managed {a}</title></rect>')
        parts.append(f'<rect x="{x:.1f}" y="{h-bottom-ha-hb:.1f}" width="{bw*0.8:.1f}" height="{hb:.1f}" fill="#d9822b"><title>{d} OOv2 {b}</title></rect>')
    parts.append(f'<text x="{left}" y="14">Disputes per day (UTC), last 90 days. Max {ymax}.  blue: ManagedOOv2  orange: OOv2</text>')
    parts.append(f'<text x="{left}" y="{h-8}">{days[0] if days else ""}</text><text x="{w-90}" y="{h-8}">{days[-1] if days else ""}</text></svg>')
    open(path, "w").write("\n".join(parts))


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def numbers_block(ctx):
    """Markdown for everything between the NUMBERS markers. Every number and every sentence that
    contains a number is generated here from the tables, so prose cannot go stale after a refresh."""
    head_ts, head = ctx["head_ts"], ctx["head_block"]
    L = [f"Rebuilt: **{utc(ctx['run_ts'])} UTC** by `update.py` (a manual run, not a live feed). Last block: **{head}** "
         f"({utc(head_ts)} UTC). Proposals: last 90 days. Disputes and settlements: last 365 days. Source: Polygon logs via a "
         f"public RPC. All rates are per request, not per market. Monthly tables use disputes at least 7 days old.", "",
         "**What this measures.** Disputes are chosen by disputers, who post a bond to raise them. These tables measure how often "
         "disputers prevail and what the vote returns; they do not measure how often proposals are wrong. Wrong proposals that "
         "nobody disputed are not in the data, and the dispute rate is not an error rate.", ""]
    L += _outcome_section(ctx) + _order_section(ctx) + _mix_section(ctx) + _reconcile_section(ctx) + _monthly_section(ctx)
    L += _breakdown_sections(ctx) + _concentration_section(ctx) + _window_section(ctx) + _open_and_settle_sections(ctx)
    L += _integrity_section(ctx)
    return "\n".join(L)


def _outcome_section(ctx):
    rows = [[o["period"], o["settled_disputes"], f'{o["reset_pct"]}%', f'{o["overturned_pct"]}%', f'{o["upheld_pct"]}%',
             _pct(o["settled_at_midpoint_pct"]), _pct(o["decided_overturn_pct"]), o["younger_than_7d"]] for o in ctx["outcomes"]]
    return ["### Outcome of settled disputes: reset, overturned, upheld",
            "Shares of ALL settled disputes. *Reset* = the vote returned \"too early\", which tells the market to ask again. "
            "*Overturned* = decided on substance and the settled price differs from the proposed one. *Upheld* = decided on substance "
            "and the proposer was confirmed. *Midpoint* = settled at 0.5e18, shown on its own and inside the other columns. How to read a midpoint "
            "settlement is not tested here: it can follow a cancelled game, or a proposer who ignored the rules. *Overturned of decided* is the older "
            "ratio, overturned / (overturned + upheld); it moves partly because upheld cases turn into resets, so read it with the "
            "first three columns. Disputes with no `Settle` yet are not counted.", "",
            md_table(["Period", "Settled disputes", "Reset", "Overturned", "Upheld", "Midpoint", "Overturned of decided",
                      "Under 7 days old, left out"], rows), ""]


def _order_section(ctx):
    rows = [[o["period"], o["later_settled"], _pct(o["later_reset_pct"]), _pct(o["later_overturned_pct"]), _pct(o["later_upheld_pct"]),
             _pct(o["later_decided_overturn_pct"]), o["first_settled"], _pct(o["first_reset_pct"]), _pct(o["first_overturned_pct"]),
             _pct(o["first_upheld_pct"]), _pct(o["first_decided_overturn_pct"])] for o in ctx["order"]]
    return ["### Which disputes decide a market: later disputes first",
            f'In the verified `UmaCtfAdapter` source ({ctx["adapter_count"]} `UmaCtfAdapter` contracts confirmed, of which {ctx["adapter_listed"]} '
            f'{"is" if ctx["adapter_listed"] == 1 else "are"} in Polymarket\'s published contract list and the rest are verified on Sourcify under the same name but not listed; they raise '
            f'{ctx["disputes_by_adapter_pct"]}% of the disputes in this data), `priceDisputed()` resets the question on the first dispute: '
            "`_reset()` sends a NEW price request and moves the question to it. On a later dispute it sets `refund = true` and returns, and "
            "`resolve()` reads the price of the question's current request. So the vote on a first dispute is not the one that resolves the "
            "market; the vote on a later dispute is. `adapter_check.py` checks both the `priceDisputed()` path and the `resolve()` path (it reads the price of the current request, which `_reset()` moves) as text patterns in the source; it does not trace markets on chain. "
            + _excluded_text(ctx) + " "
            "\"First\" here means the first dispute inside the 12 months of logs. " + _first_share(ctx), "",
            md_table(["Period", "Later: settled", "Reset", "Overturned", "Upheld", "Overturned of decided",
                      "First: settled", "Reset", "Overturned", "Upheld", "Overturned of decided"], rows), ""]


def _excluded_text(ctx):
    ex = ctx["order_excluded"]
    parts = "; ".join(f'{_short(rq)} ({ctx["labels"].get(rq, "unlabelled")}): {n}' for rq, n in ex["by_requester"])
    return ("The table covers only the confirmed adapter contracts. Left out: "
            f'{ex["total"]} settled disputes (matured) on other requester contracts, whose source does not show this logic, could not be '
            f'read, or is not an adapter. By contract: {parts}.')


def _first_share(ctx):
    months = [o for o in ctx["order"] if o["period"] != "last 90d"]
    f, l = sum(o["first_settled"] for o in months), sum(o["later_settled"] for o in months)
    return (f"Over the 12 months, {round(100 * f / (f + l), 1)}% of the settled disputes in this table ({f} of {f + l}) are first disputes, "
            "so the all-disputes series above is mostly made of votes that, per the source, do not resolve the market.")


def _mix_section(ctx):
    mix, base = ctx["mix"], ctx["mix_base"]
    short = {"line": "Lines", "player_prop": "Player props", "match_result": "Match/game result",
             "sports_season": "Sports season", "non_sports": "Non-sports", "unclassified": "Unclassified"}
    ts = list(short)
    share = [[m["month"], m["decided"]] + [_pct(m[f"{t}_share_pct"]) for t in ts] for m in mix]
    rate = [[m["month"]] + [f'{_pct(m[f"{t}_overturn_pct"])} ({m[f"{t}_n"]})' for t in ts] + [_pct(m["actual_pct"])] for m in mix]
    adj = [[m["month"], _pct(m["actual_pct"]), _pct(m["mix_adjusted_pct"]), m["mix_effect_pts"], _pct(m["mix_only_pct"]),
            m["thin_cells"] or "-"] for m in mix]
    L = ["### Market type: mix and overturn rate by type",
         "Each disputed request is typed from its question text only, by the ordered rules at the top of `markets.py` (lines = over/under, "
         "spread, handicap, totals, odd/even; player props; match or game result; sports season or event; non-sports; unclassified). "
         f'Unclassified: {ctx["unclassified_pct"]}% of all {ctx["all_disputes"]} disputes in the 12 months (base: every dispute, whatever its state). '
         "Rules were tuned by reading titles, not outcomes, and revised once after review. The tables below use decided disputes only "
         "(resets and unsettled left out).", "",
         "**Share of decided disputes by type (%)**", md_table(["Month", "Decided"] + list(short.values()), share), "",
         "**Overturn rate by type, % (decided disputes)**", md_table(["Month"] + list(short.values()) + ["All"], rate), ""]
    L += ["**Mix-adjusted overturn rate.** Base = pooled Nov 2025 to Jun 2026: "
          f'{base["base_overturned"]} of {base["base_decided"]} = {base["base_pct"]}%; type mix '
          + ", ".join(f'{short[t].lower()} {base["base_share_pct"][t]}%' for t in ts) + "; rates "
          + ", ".join(f'{short[t].lower()} {base["base_rate_pct"][t]}%' for t in ts) + ". "
          "*Held mix* = the month's own rate in each type, weighted by the base mix. *Mix only* = the month's own mix, each type at its "
          "base rate. *Thin cells* = types with at least 5% of the base mix that have fewer than 5 decided disputes that month.", "",
          md_table(["Month", "Actual", "Held mix", "Actual minus held mix (points)", "Mix only", "Thin cells"], adj), ""]
    return L + _decomposition(ctx) + _cause_paragraph(ctx) + _burst_paragraph(ctx)


def _decomposition(ctx):
    """Rise over the base rate split two ways. Held mix: mix part = actual - held, rate part = held - base.
    Mix only: mix part = mix-only - base, rate part = actual - mix-only. Months from July 2026."""
    base = ctx["mix_base"]["base_pct"]
    rows = []
    for m in ctx["mix"]:
        if m["month"] >= "2026-07" and m["mix_adjusted_pct"] is not None:
            rows.append(_split_row(m["month"], m["decided"], m["actual_pct"], m["mix_adjusted_pct"], m["mix_only_pct"], base))
    p = ctx["pooled_adjusted"]
    rows.append(_split_row("**Jul 2026 onward, pooled**", p["decided"], p["actual_pct"], p["held_pct"], p["mix_only_pct"], base))
    return ["**Where the rise over the base rate sits** (points above the pooled base rate, two methods)", "",
            md_table(["Month", "Decided", "Actual", "Rise over base", "Mix part, held mix", "Rates part, held mix",
                      "Mix part, mix only", "Rates part, mix only"], rows), ""]


def _split_row(label, n, actual, held, only, base):
    return [label, n, _pct(actual), round(actual - base, 1), round(actual - held, 1), round(held - base, 1),
            round(only - base, 1), round(actual - only, 1)]


def _cause_paragraph(ctx):
    """What the type split shows, every number taken from the tables. No cause is named."""
    p, base = ctx["pooled_adjusted"], ctx["mix_base"]["base_pct"]
    rise = round(p["actual_pct"] - base, 1)
    mix = sorted([round(p["actual_pct"] - p["held_pct"], 1), round(p["mix_only_pct"] - base, 1)])
    rate = sorted([round(p["held_pct"] - base, 1), round(p["actual_pct"] - p["mix_only_pct"], 1)])
    names = {"line": "lines", "player_prop": "player props", "match_result": "match/game results",
             "sports_season": "sports season", "non_sports": "non-sports", "unclassified": "unclassified"}
    tb, ta = ctx["type_base"], ctx["type_after"]
    rows = [[names[t], f"{tb[t][1]}% ({tb[t][2]})", f"{ta[t][1]}% ({ta[t][2]})", tb[t][0], ta[t][0]] for t in names]
    moved = {t: (ta[t][1] or 0) - (tb[t][1] or 0) for t in names if tb[t][1] is not None and ta[t][1] is not None}
    rose = [names[t] for t, v in moved.items() if v > 5 and ta[t][2] >= 20]
    fell = [names[t] for t, v in moved.items() if v < -5 and ta[t][2] >= 20]
    flat = [names[t] for t, v in moved.items() if abs(v) <= 5 and ta[t][2] >= 20]
    return ["**What the type split shows.** " + f'Pooled from July 2026 the overturn rate of decided disputes is {p["actual_pct"]}%, {rise} points '
            f'above the {base}% base rate. Across the two standardisation methods, {mix[0]} to {mix[1]} points of that rise come from the change '
            f'in type mix and {rate[0]} to {rate[1]} points from different rates inside the types. The methods give different splits pooled '
            "and by month (table above), so the split is a range, not a point. Rate inside each type, base period to July onward "
            "(decided disputes in brackets), and share of decided disputes:", "",
            md_table(["Type", "Rate, Nov 2025 to Jun 2026", "Rate, Jul 2026 onward", "Share, base (%)", "Share, from July (%)"], rows), "",
            f'With at least 20 decided disputes from July: rate rose by more than 5 points in {", ".join(rose) or "no type"}; '
            f'fell by more than 5 points in {", ".join(fell) or "no type"}; within 5 points in {", ".join(flat) or "no type"}. '
            "The tables do not show why those rates changed, and this repo does not claim a cause.", ""]


def _burst_paragraph(ctx):
    b, lp = ctx["bursts"], ctx["later_pooled"]
    ap = ctx["outcome_pools"]
    return ["**Betting lines come in bursts.** " + f'From July 2026 the {b["decided_lines"]} decided line disputes ({b["overturned_pct"]}% overturned, per request) fall into '
            f'{b["bursts"]} bursts (same requester, within 10 minutes). The largest has {b["largest_burst"]} requests on {b["largest_burst_day"]} and '
            f'{b["largest_burst_overturned"]} of them were overturned. Without bursts of 10 or more requests the rate is {b["rate_without_bursts_10plus_pct"]}% '
            f'({b["decided_without_bursts_10plus"]} decided). The rate is per request, not per game.',
            f'**Against all settled disputes.** Pooled Nov 2025 to Jun 2026 ({ap["before"]["n"]} settled): overturned {ap["before"]["overturned_pct"]}%, '
            f'upheld {ap["before"]["upheld_pct"]}%, reset {ap["before"]["reset_pct"]}%. From July ({ap["after"]["n"]} settled): overturned {ap["after"]["overturned_pct"]}%, '
            f'upheld {ap["after"]["upheld_pct"]}%, reset {ap["after"]["reset_pct"]}%.',
            f'**Later disputes** (the ones that can decide a market), overturned of decided: {lp["before"]["pct"]}% ({lp["before"]["overturned"]} of '
            f'{lp["before"]["decided"]}) before July, {lp["after"]["pct"]}% ({lp["after"]["overturned"]} of {lp["after"]["decided"]}) from July.', ""]


def _reconcile_section(ctx):
    p = ctx["pooled"]
    f = lambda x: f'{x["overturned"]} of {x["decided"]} = {x["pct"]}%'
    return ["### How this relates to earlier published figures",
            "The earlier Dune dashboard reported about 31% overturned among disputes decided on substance over its full history to mid-2026 "
            "(its definitions text; its saved results have expired, so I did not reproduce it). That history includes months before "
            "November 2025, which are not measured here. Pooled figures from this repo, same definition, matured cohort:", "",
            f'- Nov 2025 to Jun 2026 pooled: {f(p["base"])}',
            f'- 12 months pooled: {f(p["all"])}',
            f'- Jul 2026 onward pooled: {f(p["after"])}', "",
            "A pooled figure depends on the window, so there is no single number to compare with 31%. The monthly path is in the tables above.", ""]


def _monthly_section(ctx):
    cl = {c["period"]: c for c in ctx["clusters"]}
    rows = []
    for m in ctx["overturn_months"]:
        c = cl.get(m["month"], {})
        rows.append([m["month"], m["disputes"], m["resets"], m["decided"], m["overturned"], _pct(m["overturn_pct"]),
                     c.get("clusters", ""), _pct(c.get("per_cluster_pct")), _pct(c.get("per_cluster_pct_ties_overturned")),
                     _pct(c.get("per_cluster_pct_time_only_linking"))])
    c90 = cl["last 90d"]
    rows.append(["**last 90 days**", "", "", c90["decided_requests"], c90["overturned_requests"], _pct(c90["per_request_pct"]),
                 c90["clusters"], _pct(c90["per_cluster_pct"]), _pct(c90["per_cluster_pct_ties_overturned"]),
                 _pct(c90["per_cluster_pct_time_only_linking"])])
    dev = max((c for c in ctx["clusters"] if c["period"] != "last 90d" and c["per_cluster_pct"] is not None),
              key=lambda c: abs(c["per_cluster_pct"] - c["per_request_pct"]))
    sens = (f'Largest gap between the two bases: {dev["period"]}, per request {dev["per_request_pct"]}%, per cluster '
            f'{dev["per_cluster_pct"]}%, per cluster with ties as overturned {dev["per_cluster_pct_ties_overturned"]}%. '
            f'The tie rule moves it {round(dev["per_cluster_pct_ties_overturned"] - dev["per_cluster_pct"], 1)} points; the rest of the '
            "gap comes from counting majorities of clusters instead of requests.")
    return ["### Overturn of decided disputes by month: per request and per event cluster",
            "Same ratio as *Overturned of decided* above, with resets and unsettled disputes left out. A *cluster* groups disputes on one "
            "requester within 10 minutes that share a team or player name in the title. **Cluster rule:** a cluster counts as overturned "
            "when MORE than half of its decided requests were overturned, and an exact tie counts as upheld; the next column counts ties "
            "as overturned, to show how much the rule matters. The last column links by requester and time only. Matured cohort. " + sens, "",
            md_table(["Month", "Disputes", "Resets", "Decided", "Overturned", "Per request", "Clusters", "Per cluster",
                      "Per cluster, ties overturned", "Per cluster, time-only linking"], rows), ""]


def _breakdown_sections(ctx):
    vc = [[v["period"], v["decided"], v["overturned"], v["flipped_to_opposite"], v["flip_0_to_1e18"], v["flip_1e18_to_0"],
           v["to_midpoint"], v["from_midpoint"], v["other"]] for v in ctx["value_classes"]]
    L = ["### What the overturned requests changed to",
         "Prices are raw int256 values at a scale of 1e18: 0 = first outcome, 1e18 = second outcome, 0.5e18 = midpoint. "
         "*Flipped* = settled at the opposite of the proposed 0 or 1e18. *To midpoint* = settled at 0.5e18. "
         "*From midpoint* = proposed 0.5e18, settled at 0 or 1e18. What a midpoint settlement means is not tested here.", "",
         md_table(["Period", "Decided", "Overturned", "Flipped", "0 to 1e18", "1e18 to 0", "To midpoint", "From midpoint", "Other"], vc), ""]
    br = [[b["period"], _short(b["requester"]), b["what_it_is"], b["disputes"], b["resets"], b["decided"], b["overturned"],
           _pct(b["overturn_pct"])] for b in ctx["by_requester"] if b["disputes"] >= 5]
    L += ["### By requester contract (contracts with 5 or more disputes in the period)",
          "A requester contract is not a market type: one adapter carries sports, politics and crypto. Descriptive only. Labels come from "
          "Sourcify's verified source names and Polymarket's published contract list.", "",
          md_table(["Period", "Requester", "What it is", "Disputes", "Resets", "Decided", "Overturned", "Overturn rate"], br), ""]
    return L


def _concentration_section(ctx):
    rows = [[c["period"], c["disputes"], c["distinct_disputers"], _pct(c["top3_disputers_share_of_disputes_pct"]), c["overturned"],
             c["distinct_proposers_overturned"], _pct(c["top3_proposers_share_of_overturns_pct"])] for c in ctx["concentration"]]
    return ["### Concentration of disputers and proposers (aggregate counts only)",
            "How concentrated the actors are, by dispute month. No addresses are published.", "",
            md_table(["Period", "Disputes", "Distinct disputers", "Top 3 disputers' share of disputes", "Overturned",
                      "Distinct proposers", "Top 3 proposers' share of overturns"], rows), ""]


def _window_section(ctx):
    rows = [[r["window"], f'{r["proposals"]:,}', r["disputes"], f'{r["dispute_rate_pct"]}%', r["matured_decided"],
             r["matured_overturned"], _pct(r["matured_overturn_pct"]), r["immature_excluded"], r["matured_no_settle"],
             r["matured_resets"]] for r in ctx["rates"]]
    L = ["### Rolling 30 and 90 day rates",
         md_table(["Window", "Proposals", "Disputes", "Dispute rate", "Decided (disputes at least 7 days old)", "Overturned",
                   "Overturn rate", "Immature, left out", "Matured, no Settle", "Resets"], rows), "",
         "Matured = dispute at least 7 days old at the last block, because a vote takes days. The overturn rate here is a window "
         "average of a series that moves from month to month (tables above). Time to Settle is for one request; the time until a "
         "market resolves (re-request, later dispute, vote) is not measured.", "",
         "### Requester split, proposals and disputes (last 90 days)",
         md_table(["Requester contract", "Proposals", "Share of proposals", "Disputes", "Share of disputes", "Dispute rate"],
                  [[_short(r["requester"]), f'{r["proposals"]:,}', f'{r["proposal_share_pct"]}%', r["disputes"],
                    f'{r["dispute_share_pct"]}%', f'{r["dispute_rate_pct"]}%'] for r in ctx["split"]]), ""]
    rr = ctx["rerequest"]
    L.append(f'Re-requests: of {rr["disputed_requests"]} disputed requests in the 90-day window, '
             f'{rr["followed_by_new_request"]} were followed by a later request for the same question.')
    L.append("")
    return L


def _open_and_settle_sections(ctx):
    op = sorted(ctx["open"], key=lambda o: o["disputed_at"])[:10]
    L = [f'### Open disputes: no Settle event yet ({len(ctx["open"])} disputes from the last 30 days; the 10 oldest shown)',
         "This means no `Settle` log exists yet. It does not say the vote is undecided. Market types and leagues are shown instead of titles; the full list with titles is `data/open_disputes.csv`.", "",
         md_table(["Oracle", "Disputed at (UTC)", "Hours since dispute", "Market type", "League or sport"],
                  [[o["oracle"], utc(o["disputed_at"]), o["hours_open"], o["market_type"], _cell(o["venue"]) or "-"] for o in op]), "",
         "### Time from dispute to Settle, by dispute month (matured disputes)",
         "Disputes at least 7 days old. *Slowest settled* is the slowest dispute that HAS a `Settle`; it is not a worst case, because "
         "disputes still without a `Settle` are not in it (next table).", "",
         md_table(["Month", "Settled disputes", "Resets", "Median hours", "p90 hours", "Fastest, hours", "Slowest settled, hours",
                   "Matured, no Settle yet"],
                  [[r["month"], r["settled_disputes"], r["resets"], r["median_hours"], r["p90_hours"], r["min_hours"],
                    r["max_settled_hours"], r["no_settle_yet"]] for r in ctx["settle_months"]]), "",
         f'**Matured disputes with no `Settle`: {ctx["stuck"][1]}.** The longest open, with the requester contract and market type '
         "(a missing `Settle` log does not say the vote is undecided):", "",
         md_table(["Oracle", "Requester", "Disputed at (UTC)", "Hours open", "Market type"],
                  [[s["oracle"], _short(s["requester"]), utc(s["disputed_at"]), s["hours_open"], s["market_type"]] for s in ctx["stuck"][0][:5]]), "",
         "![Disputes per day](docs/disputes_per_day.svg)", ""]
    return L


def _integrity_section(ctx):
    k, v = ctx["key_integrity"], ctx["verification"]
    bad = sum(1 for x in v if not x["match"])
    ss = list(csv.DictReader(open("data/second_source_sample.csv"))) if os.path.exists("data/second_source_sample.csv") else []
    ok = sum(1 for x in ss if x["match"] == "True")
    return ["### Data checks (recomputed on every run)",
            f'- Second-source decoding check (stratified sample, same endpoint): {ok} of {len(ss)} match.',
            f'- Request keys with more than one Settle log: {k["keys_with_2plus_settle_logs"]}; with more than one dispute log: '
            f'{k["keys_with_2plus_dispute_logs"]}. Proposed price differs between the proposal and the dispute event: '
            f'{k["proposed_price_differs_between_proposal_and_dispute_event"]} of {k["disputes_with_a_proposal_row_in_window"]} matched disputes.',
            f'- Log completeness: {len(v) - bad} of {len(v)} re-queried windows identical to the stored logs.']


def _pct(v):
    return "n/a" if v is None else f"{v}%"


def _short(addr):
    return addr if addr == "other" else addr[:8] + "…" + addr[-4:]


def _cell(text):
    return re.sub(r"\s+", " ", text).replace("|", "/")


def write_readme(block, path="README.md"):
    src = open(path).read()
    i, j = src.index(START) + len(START), src.index(END)
    open(path, "w").write(src[:i] + "\n" + block + "\n" + src[j:])


# ---- SCORECARD figures, regenerated from the same ctx as the README ----------------

RANGES = {"P3": (0.05, 0.40), "P1": (10000, 60000), "P2": (30000, 180000), "P4": (0.05, 0.40), "P5": (8, 150), "P6": (20, 70), "P7": (30, 65),
          "P8": (55, 85), "P9": (90, 220), "P10": (0.3, 3), "P11": (1, 12), "P12": (0, 15), "P13": (40, 95)}


def scorecard_values(ctx):
    r30, r90 = ctx["rates"]
    managed = sum(d["disputes"] for d in ctx["daily"] if d["oracle"] == "ManagedOOv2")
    total = sum(d["disputes"] for d in ctx["daily"])
    young = sum(1 for o in ctx["open"] if o["hours_open"] < 72)
    return {"P3": (r30["dispute_rate_pct"], f'{r30["dispute_rate_pct"]:.3f}%'), "P1": (r30["proposals"], f'{r30["proposals"]:,}'), "P2": (r90["proposals"], f'{r90["proposals"]:,}'),
            "P4": (r90["dispute_rate_pct"], f'{r90["dispute_rate_pct"]:.3f}%'), "P5": (r30["disputes"], f'{r30["disputes"]:,}'),
            "P6": (r30["matured_overturn_pct"], f'{r30["matured_overturn_pct"]}% (n={r30["matured_decided"]})'),
            "P7": (r90["matured_overturn_pct"], f'{r90["matured_overturn_pct"]}% (n={r90["matured_decided"]})'),
            "P8": (ctx["settle_pool"]["median"], f'{ctx["settle_pool"]["median"]} (12-month pool, n={ctx["settle_pool"]["n"]:,})'),
            "P9": (ctx["settle_pool"]["p90"], f'{ctx["settle_pool"]["p90"]}'),
            "P10": (round(ctx["recent_disputes"] / 90, 1), f'{ctx["recent_disputes"] / 90:.1f}'),
            "P11": (len(ctx["open"]), f'{len(ctx["open"])} ({young} are under 72 h old)'),
            "P12": (ctx["outcomes"][-1]["reset_pct"], f'{ctx["outcomes"][-1]["reset_pct"]}% (12 months)'),
            "P13": (round(100 * managed / total, 1), f'{100 * managed / total:.1f}%')}


def write_scorecard(ctx, path="SCORECARD.md"):
    """Rewrite the Measured and Result cells of the numeric rows and the header from ctx. Predicted ranges are untouched."""
    vals, text = scorecard_values(ctx), open(path).read()

    def row(m):
        key = m.group(1)
        if key not in vals:
            return m.group(0)
        lo, hi = RANGES[key]
        x, shown = vals[key]
        res = "Hit" if lo <= x <= hi else f"**Miss** ({'above' if x > hi else 'below'} the range)"
        return f"| {key} | {m.group(2)} | {m.group(3)} | {shown} | {res} |"

    text = re.sub(r"^\| (P\d+) \| (.*?) \| (.*?) \| (.*?) \| (.*?) \|$", row, text, flags=re.M)
    text = re.sub(r"\A# SCORECARD.*\n", f"# SCORECARD: predictions vs measured (regenerated by update.py; data to block {ctx['head_block']:,}, {utc(ctx['head_ts'])} UTC)\n", text)
    text = re.sub(r"The README refreshes.*?No scoring changes\.", "The Measured and Result cells of P1 to P13 are rewritten by `update.py` from the same tables as the README; the Predicted column and the notes below are not.", text, flags=re.S)
    r30 = ctx["rates"][0]
    text = re.sub(r"^\| S5 \| (.*?) \| (.*?) \| .*? \| .*? \|$", lambda m: f"| S5 | {m.group(1)} | {m.group(2)} | {r30['immature_excluded']} immature left out; 30d decided "
                  f"{r30['all_decided']} raw vs {r30['matured_decided']} matured | Pass |", text, flags=re.M)
    rows = re.findall(r"^\| P\d+ \|.*\| (Hit.*|\*\*Miss.*) \|$", text, flags=re.M)
    hit = sum(1 for x in rows if x.startswith("Hit"))
    text = re.sub(r"Score: \d+ of \d+ numeric predictions hit, \d+ missed\.", f"Score: {hit} of {len(rows)} numeric predictions hit, {len(rows) - hit} missed.", text)
    open(path, "w").write(text)
