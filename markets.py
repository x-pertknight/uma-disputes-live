"""Market type of a disputed request, from the question text only (never from outcomes).

Rules are applied in this order; the first match wins. Title = the question title,
context = the first 300 characters of the description.
  1 player_prop   sports context, title is "<name>: <stat> ..." with a player stat word or "N+"
  2 line          sports context or not: title has O/U, Over/Under, Spread, Handicap, Total(s), Odd/Even
  3 match_result  sports context (description says "game"/"match"), or "A vs B", or a title starting
                  "Game 2:" / "Map 1:" / "Set 1:", and none of the above: winner, exact score, draw, in-game markets
  4 sports_season sports words about seasons or events: championship, finals, Grand Prix, marathon, MVP, ...
  5 non_sports    politics, crypto and finance, weather, entertainment, statements, "event by <date>" news
  6 unclassified  nothing above matched
A line or prop is counted as its own type even when it is a sports line, because the study asks
about betting lines. Share of unclassified is reported next to every table.
"""
import collections
import re

import decode
from metrics import TOO_EARLY

TYPES = ["line", "player_prop", "match_result", "sports_season", "non_sports", "unclassified"]

STAT = (r"(hits|shots?|assists?|rebounds?|points?|yards|strikeouts?|goals?|saves|tackles|touchdowns?|receptions?|"
        r"rushing|passing|receiving|runs|rbis?|steals|blocks|threes|home runs?|bases|pts|reb|ast|\d\+)")
PROP = re.compile(r"^[^:]{3,45}:\s.*\b" + STAT + r"\b", re.I)
LINE = re.compile(r"(o/u|over/under|\bover\b.*\bunder\b|\bspread\b|handicap|\btotals?\b|odd/even|\(-?\+?\d+(\.\d)?\))", re.I)
SPORT_CTX = re.compile(r"(upcoming|refers to the|in the).{0,120}\b(game|match|fight|bout|race|series)\b", re.I | re.S)
MATCH = re.compile(r"(\bvs\.?\b|winner|exact score|draw|both teams|moneyline|\bbo[357]\b|map \d|set \d|game \d|"
                   r"first (half|blood|to)|\bto win\b|advance)", re.I)
SEASON = re.compile(r"(world series|super bowl|nba finals|stanley cup|grand prix|\bf1\b|marathon|indianapolis 500|"
                    r"world cup|champions league|premier league|\bepl\b|\bmvp\b|ballon|playoffs?|champion|"
                    r"top \d|finish in|standings|win the 20\d\d|rookie|draft|nfl|nba|mlb|nhl|ufc|olympic|"
                    r"tournament|league|ncaa|masters|open\b|tour de|wimbledon|play for|relegat|bundesliga|best record|starting 11|fifa|drafted|traded)", re.I)
# strong = a topic word; weak = a generic "will X do Y by <date>" shape. A sports season/event word beats a weak match.
NON = re.compile(r"(election|president|trump|biden|vance|senate|congress|governor|mayor|prime minister|minister|"
                 r"bitcoin|ethereum|solana|\bbtc\b|\beth\b|crypto|price|token|airdrop|fdv|market cap|etf|\bfed\b|rate cut|"
                 r"inflation|cpi|gdp|stock|ipo|tiktok|microstrategy|temperature|earthquake|hurricane|weather|\brain\b|\bsnow\b|"
                 r"box office|opening weekend|netflix|movie|film|oscar|grammy|emmy|spotify|album|song|youtube|"
                 r"tweet|tweets|say |says|said|mention|announce|ceasefire|\bwar\b|russia|ukraine|israel|iran|gaza|china|"
                 r"tariff|shutdown|launch|release|elon|musk|tsa passengers|domestic gross|"
                 r"up or down|house seat|revenue|\bviews\b|\bposts?\b|(?<!counter-)\bstrike\b|operation|settle at|go live)", re.I)
NON_WEAK = re.compile(r"(\btrad(e|ed)\b|\bby (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d|\bin 20\d\d\??$|\bout by|"
                      r"will .* (be|reach|hit|close|resign|leave|sign|sell|buy|ban|pass|die|pull))", re.I)
GAME_PART = re.compile(r"^(game|map|set|round|quarter|half)\s*\d+\s*:", re.I)   # esports and in-game markets


def classify(ancillary):
    title, desc = decode.parse_question(ancillary)
    title, ctx = title.strip(), desc[:300]
    sports = bool(SPORT_CTX.search(ctx))
    if sports and PROP.search(title):
        return "player_prop"
    if LINE.search(title) and not re.match(r"will the total (number|domestic|worldwide)", title, re.I):
        return "line"
    if GAME_PART.search(title) or (sports and (MATCH.search(title) or not NON.search(title))):
        return "match_result"
    if re.search(r"\bvs\.?\b", title, re.I) and not NON.search(title):
        return "match_result"
    if SEASON.search(title) and not NON.search(title):
        return "sports_season"
    if NON.search(title) or NON_WEAK.search(title):
        return "non_sports"
    return "unclassified"


def type_of(disputes):
    """{key: market type} for a dict of decoded disputes."""
    return {k: classify(d["ancillary"]) for k, d in disputes.items()}


# ---- per month and type, and the mix-adjusted rate ----------------------------

BASE_FIRST, BASE_LAST = "2025-11", "2026-06"     # months whose type mix is held fixed
THIN = 5                                          # fewer decided disputes than this = a thin cell


def _month(ts):
    import breakdown
    return breakdown.month_of(ts)


def cells(disputes, settles, types):
    """{(month, type): Counter(settled, decided, overturned)} and {month: Counter} totals."""
    c = collections.defaultdict(collections.Counter)
    for k, d in disputes.items():
        s = settles.get(k)
        if not s:
            continue
        g = c[(_month(d["time"]), types[k])]
        g["settled"] += 1
        if s["price"] != TOO_EARLY:
            g["decided"] += 1
            g["overturned"] += s["price"] != d["price"]
    return c


def _pct(a, b):
    return round(100 * a / b, 1) if b else None


def mix_table(cell):
    """One row per month: each type's share of decided disputes, each type's overturn rate and the
    decided count, the actual rate, and the rate if the Nov 2025 to Jun 2026 type mix were held."""
    months = sorted({m for m, _ in cell})
    base, base_over = collections.Counter(), collections.Counter()
    for (m, t), g in cell.items():
        if BASE_FIRST <= m <= BASE_LAST:
            base[t] += g["decided"]
            base_over[t] += g["overturned"]
    nb = sum(base.values())
    rows = []
    for m in months:
        tot = sum(cell[(m, t)]["decided"] for t in TYPES)
        over = sum(cell[(m, t)]["overturned"] for t in TYPES)
        row = {"month": m, "decided": tot, "overturned": over, "actual_pct": _pct(over, tot)}
        for t in TYPES:
            g = cell[(m, t)]
            row[f"{t}_share_pct"] = _pct(g["decided"], tot)
            row[f"{t}_n"] = g["decided"]
            row[f"{t}_overturn_pct"] = _pct(g["overturned"], g["decided"])
        row["mix_adjusted_pct"] = _adjusted(cell, m, base)
        # the other direction: this month's mix, but every type at its Nov-Jun overturn rate
        row["mix_only_pct"] = round(100 * sum(cell[(m, t)]["decided"] * base_over[t] / base[t]
                                              for t in TYPES if base[t]) / tot, 1) if tot else None
        row["thin_cells"] = ",".join(t for t in TYPES if base[t] / nb >= 0.05 and cell[(m, t)]["decided"] < THIN)
        row["mix_effect_pts"] = _diff(row["actual_pct"], row["mix_adjusted_pct"])
        rows.append(row)
    b_over = sum(g["overturned"] for (m, _), g in cell.items() if BASE_FIRST <= m <= BASE_LAST)
    return rows, {"base_decided": nb, "base_overturned": b_over, "base_pct": _pct(b_over, nb),
                  "base_share_pct": {t: _pct(base[t], nb) for t in TYPES},
                  "base_rate_pct": {t: _pct(base_over[t], base[t]) for t in TYPES}}


def _adjusted(cell, m, base):
    """Weights = base mix; types with no decided dispute that month are dropped and the weights renormalised."""
    num = den = 0
    for t in TYPES:
        g = cell[(m, t)]
        if g["decided"]:
            num += base[t] * g["overturned"] / g["decided"]
            den += base[t]
    return round(100 * num / den, 1) if den else None


def _diff(a, b):
    return None if a is None or b is None else round(a - b, 1)


def pooled(cell, first, last):
    """(overturned, decided, pct) pooled over months first..last (inclusive, 'YYYY-MM')."""
    o = sum(g["overturned"] for (m, _), g in cell.items() if first <= m <= last)
    n = sum(g["decided"] for (m, _), g in cell.items() if first <= m <= last)
    return {"overturned": o, "decided": n, "pct": _pct(o, n)}


def unclassified_share(types):
    return _pct(sum(1 for t in types.values() if t == "unclassified"), len(types))


VENUE = re.compile(r"(?:upcoming|refers to the)\s+(.{2,40}?)\s+(?:game|match)\b", re.I)


def venue(ancillary):
    """League or sport named in the description ("NHL", "Dota 2"), or "" when none is found.
    Used instead of the full title so the README names no players or teams."""
    m = VENUE.search(decode.parse_question(ancillary)[1][:300])
    return m.group(1) if m else ""


def pooled_adjusted(cell, first, last, base_first=BASE_FIRST, base_last=BASE_LAST):
    """Actual, held-mix and mix-only rates pooled over months first..last (decided-weighted)."""
    merged = collections.defaultdict(collections.Counter)
    base, base_over = collections.Counter(), collections.Counter()
    for (mo, t), g in cell.items():
        if first <= mo <= last:
            merged[("pool", t)].update(g)
        if base_first <= mo <= base_last:
            base[t] += g["decided"]
            base_over[t] += g["overturned"]
    n = sum(merged[("pool", t)]["decided"] for t in TYPES)
    o = sum(merged[("pool", t)]["overturned"] for t in TYPES)
    only = sum(merged[("pool", t)]["decided"] * base_over[t] / base[t] for t in TYPES if base[t]) / n
    return {"decided": n, "actual_pct": _pct(o, n), "held_pct": _adjusted(merged, "pool", base),
            "mix_only_pct": round(100 * only, 1)}


def type_summary(cell, first, last):
    """{type: (share of decided %, overturn rate %, decided)} pooled over months first..last."""
    n = {t: sum(g["decided"] for (mo, tt), g in cell.items() if tt == t and first <= mo <= last) for t in TYPES}
    o = {t: sum(g["overturned"] for (mo, tt), g in cell.items() if tt == t and first <= mo <= last) for t in TYPES}
    tot = sum(n.values())
    return {t: (_pct(n[t], tot), _pct(o[t], n[t]), n[t]) for t in TYPES}
