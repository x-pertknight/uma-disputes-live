"""Four charts for the article, built from the saved tables in data/. Each is written as an SVG and
rendered to PNG with headless Chrome (path in CHROME; set UMA_CHROME to override). Titles are generated
from the data so they cannot drift from it.   python3 charts.py
"""
import csv
import os
import subprocess

CHROME = os.environ.get("UMA_CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
W, H = 1200, 720
INK, SOFT, GRID = "#1c1c1c", "#555555", "#e3e3e3"
C_RESET_TEXT = "#4a535c"      # darker grey for text that sits on white
C_RESET, C_OVER, C_UP, C_LINE = "#9aa3ad", "#d9822b", "#2a6fb0", "#7a4fa3"
FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def rows(name):
    return list(csv.DictReader(open(f"data/{name}.csv")))


def label(month):                     # "2026-07" -> "Jul 26"
    return f"{MON[int(month[5:]) - 1]} {month[2:4]}"


def text(x, y, s, size=22, fill=INK, anchor="start", weight="normal"):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{s}</text>'


def frame(title, body, sub=""):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="Helvetica, Arial, sans-serif">',
             f'<rect width="{W}" height="{H}" fill="white"/>', text(30, 46, title, 30, INK, weight="bold")]
    if sub:
        parts.append(text(30, 80, sub, 21, SOFT))
    return "\n".join(parts + body + ["</svg>"])


def axes(ymax, unit, left=95, top=120, bottom=H - 90, step=None):
    step = step or ymax / 4
    out, v = [], 0.0
    while v <= ymax + 1e-9:
        y = bottom - (bottom - top) * v / ymax
        out += [f'<line x1="{left}" x2="{W - 30}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>',
                text(left - 12, y + 7, f"{v:g}", 21, SOFT, "end")]
        v += step
    out.append(text(30, top - 14, unit, 21, SOFT))
    return out


def month_axis(months, left=95, right=W - 30, y=H - 55):
    bw = (right - left) / len(months)
    return [text(left + bw * (i + .5), y, label(m), 19, SOFT, "middle") for i, m in enumerate(months)]


def stacked(path, title, sub, months, series):
    """series: [(name, color, [pct per month])] drawn bottom to top; each month sums to 100."""
    left, top, bottom = 95, 120, H - 90
    bw = (W - 30 - left) / len(months)
    body = axes(100, "Share of settled disputes (%)", step=25)
    for i in range(len(months)):
        base = 0
        for _, color, vals in series:
            h = (bottom - top) * vals[i] / 100
            body.append(f'<rect x="{left + bw * i + 5:.1f}" y="{bottom - (bottom - top) * base / 100 - h:.1f}" width="{bw - 10:.1f}" height="{h:.1f}" fill="{color}"/>')
            base += vals[i]
    body += month_axis(months)
    lx = left
    for name, color, _ in series[::-1]:
        body += [f'<rect x="{lx}" y="{H - 28}" width="18" height="18" fill="{color}"/>', text(lx + 26, H - 12, name, 21)]
        lx += 60 + 12 * len(name)
    open(path, "w").write(frame(title, body, sub))


def lines(path, title, sub, months, series, unit, ymax, direct=True):
    """series: [(name, color, [value per month])]; direct labels at the right end."""
    left, top, bottom, right = 95, 120, H - 90, W - 200
    bw = (right - left) / len(months)
    body = axes(ymax, unit)
    for name, color, vals in series:
        pts = [(left + bw * (i + .5), bottom - (bottom - top) * v / ymax) for i, v in enumerate(vals)]
        body.append(f'<polyline fill="none" stroke="{color}" stroke-width="5" points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}"/>')
        body += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}"/>' for x, y in pts]
        body.append(text(pts[-1][0] + 16, pts[-1][1] + 7, name, 21, color, weight="bold"))
    body += month_axis(months, left, right)
    open(path, "w").write(frame(title, body, sub))


def chart_outcomes():
    d = [r for r in rows("outcome_shares_by_month") if r["period"][:2] == "20"]
    ms = [r["period"] for r in d]
    big = sum(1 for r in d if float(r["reset_pct"]) >= max(float(r["overturned_pct"]), float(r["upheld_pct"])))
    stacked("charts/01_outcomes.svg", f"A reset was the most common outcome of a dispute in {big} of {len(ms)} months",
            "Settled disputes on UMA's oracles on Polygon, by month of dispute; November 2026 is a partial month", ms,
            [("Reset", C_RESET, [float(r["reset_pct"]) for r in d]), ("Overturned", C_OVER, [float(r["overturned_pct"]) for r in d]),
             ("Upheld", C_UP, [float(r["upheld_pct"]) for r in d])])


def chart_mix():
    d = rows("market_type_by_month")
    ms = [r["month"] for r in d]
    def share(sel):                      # pooled share of decided disputes that are betting lines
        rs = [r for r in d if sel(r["month"])]
        return 100 * sum(int(r["line_n"]) for r in rs) / sum(int(r["decided"]) for r in rs)
    lo, hi = share(lambda m: m < "2026-07"), share(lambda m: m >= "2026-07")
    lines("charts/02_mix.png".replace(".png", ".svg"), f"Betting lines rose from {lo:.0f}% to {hi:.0f}% of decided disputes from July",
          "By month of dispute; title compares Nov 2025 to Jun 2026 with July onward", ms,
          [("Overturned", C_OVER, [float(r["actual_pct"]) for r in d]), ("Betting lines", C_LINE, [float(r["line_share_pct"]) for r in d])],
          "Share of decided disputes (%)", 100)


def chart_time():
    d = rows("time_to_settle_by_month")
    ms = [r["month"] for r in d]
    med = [float(r["median_hours"]) for r in d]
    lines("charts/03_time.svg", f"The median dispute settled in {min(med):.0f} to {max(med):.0f} hours in every month",
          "Hours from dispute to settlement, disputes at least 7 days old; only disputes that have settled are included", ms,
          [("90th percentile", C_OVER, [float(r["p90_hours"]) for r in d]), ("Median", C_UP, med)], "Hours", 200)


def chart_first_later():
    r = next(x for x in rows("overturn_first_vs_later_dispute") if x["period"] == "last 90d")
    sets = [("Later disputes", "later"), ("First disputes", "first")]
    body, left, bw = [], 260, W - 260 - 40
    for j, (name, key) in enumerate(sets):
        y, x = 190 + j * 200, left
        body.append(text(left - 15, y + 52, name, 24, INK, "end"))
        body.append(text(left - 15, y + 82, f"{r[key + '_settled']} settled", 19, SOFT, "end"))
        for lab, color, f in [("Reset", C_RESET, "reset"), ("Overturned", C_OVER, "overturned"), ("Upheld", C_UP, "upheld")]:
            v = float(r[f"{key}_{f}_pct"])
            w = bw * v / 100
            body.append(f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="80" fill="{color}"/>')
            if v >= 8:
                body.append(text(x + w / 2, y + 50, f"{v:.0f}%", 24, "white", "middle", "bold"))
            x += w
    lx = left
    for lab, color in [("Reset", C_RESET), ("Overturned", C_OVER), ("Upheld", C_UP)]:
        body += [f'<rect x="{lx}" y="{H - 90}" width="18" height="18" fill="{color}"/>', text(lx + 26, H - 74, lab, 21)]
        lx += 60 + 12 * len(lab)
    big_f = max(("reset", "overturned", "upheld"), key=lambda f: float(r[f"first_{f}_pct"]))
    big_l = max(("reset", "overturned", "upheld"), key=lambda f: float(r[f"later_{f}_pct"]))
    open("charts/04_first_later.svg", "w").write(frame(
        f"Most first disputes end in a {big_f}; most later disputes are {big_l}",
        body, "Outcome of settled disputes over the last 90 days, adapters whose source was read, disputes at least 7 days old"))


def render(name):
    png = name.replace(".svg", ".png")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={W},{H}",
                    f"--screenshot={os.path.abspath(png)}", "file://" + os.path.abspath(name)], check=True, capture_output=True)
    print("wrote", png)




# ---- one summary image for the post (1080 x 1350, phone feed) -----------------

def summary_values():
    """Every figure on the image, from the saved tables, rounded to whole percents."""
    out = {r["period"]: r for r in rows("outcome_shares_by_month")}
    tot = out["12 months"]
    months = [r for r in out.values() if r["period"][:2] == "20"]

    def pooled(sel, key):
        rs = [r for r in months if sel(r["period"])]
        return sum(int(r[key]) for r in rs)
    pct = lambda a, b: round(100 * a / b)
    before, after = (lambda p: p < "2026-07"), (lambda p: p >= "2026-07")
    fl = [r for r in rows("overturn_first_vs_later_dispute") if r["period"][:2] == "20"]
    first = sum(int(r["first_settled"]) for r in fl)
    later = sum(int(r["later_settled"]) for r in fl)
    up = sum(float(r["later_upheld_pct"] or 0) * int(r["later_settled"]) / 100 for r in fl)
    mt = rows("market_type_by_month")
    dec = lambda sel, k: sum(int(r[k]) for r in mt if sel(r["month"]))
    return {"n": int(tot["settled_disputes"]), "reset": round(float(tot["reset_pct"])), "over": round(float(tot["overturned_pct"])),
            "up": round(float(tot["upheld_pct"])), "first_in_ten": round(10 * first / (first + later)), "later_up_in_three": round(3 * up / later),
            "verdict_before": pct(dec(before, "overturned"), dec(before, "decided")), "verdict_after": pct(dec(after, "overturned"), dec(after, "decided")),
            "all_before": pct(pooled(before, "overturned"), pooled(before, "settled_disputes")),
            "all_after": pct(pooled(after, "overturned"), pooled(after, "settled_disputes")),
            "lines_before": pct(dec(before, "line_n"), dec(before, "decided")), "lines_after": pct(dec(after, "line_n"), dec(after, "decided"))}


def chart_summary():
    v = summary_values()
    w, h, m = 1080, 1350, 60
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="Helvetica, Arial, sans-serif">',
         f'<rect width="{w}" height="{h}" fill="white"/>',
         text(m, 110, "What happens when a", 62, INK, weight="bold"), text(m, 182, "Polymarket result is challenged", 62, INK, weight="bold"),
         text(m, 236, f"{v['n']:,} challenges settled on Polygon, 12 months to November 2026", 28, SOFT)]
    p.append(text(m, 330, "Most end with “ask again”", 44, INK, weight="bold"))
    x, bw = m, w - 2 * m
    for name, color, key in [("too early,<br>ask again", C_RESET, "reset"), ("changed<br>the answer", C_OVER, "over"), ("confirmed<br>it", C_UP, "up")]:
        wd = bw * v[key] / 100
        p.append(f'<rect x="{x:.1f}" y="355" width="{wd:.1f}" height="110" fill="{color}"/>')
        p.append(text(x + wd / 2, 425, f"{v[key]}%", 50, "white", "middle", "bold"))
        a, b = name.split("<br>")
        tc = C_RESET_TEXT if key == "reset" else color
        p += [text(x + 8, 505, a, 27, tc, weight="bold"), text(x + 8, 537, b, 27, tc, weight="bold")]
        x += wd
    p.append(text(m, 650, "The first challenge doesn’t decide", 44, INK, weight="bold"))
    for cx, big, color, l1, l2 in [(m, f"{v['first_in_ten']} in 10", C_RESET, "challenges are first ones,", "sent back to be asked again"),
                                   (m + 500, f"{v['later_up_in_three']} in 3", C_UP, "later challenges", "confirmed the answer")]:
        p += [text(cx, 760, big, 96, C_RESET_TEXT if color == C_RESET else color, weight="bold"), text(cx, 808, l1, 27, INK), text(cx, 842, l2, 27, INK)]
    p.append(text(m, 960, "The rise after June", 44, INK, weight="bold"))
    for cx, a, b, l1, l2 in [(m, v["verdict_before"], v["verdict_after"], "of challenges that got", "a verdict were overturned"),
                             (m + 500, v["all_before"], v["all_after"], "of all settled", "challenges were overturned")]:
        p += [text(cx, 1070, f"{a}% → {b}%", 76, C_OVER, weight="bold"), text(cx, 1118, l1, 27, INK), text(cx, 1152, l2, 27, INK)]
    p.append(text(m, 1215, f"Betting lines went from {v['lines_before']}% to {v['lines_after']}% of the cases", 32, INK))
    p.append(f'<line x1="{m}" x2="{w - m}" y1="1262" y2="1262" stroke="{GRID}" stroke-width="2"/>')
    p.append(text(m, 1310, "Marco Amendola · data and code: github.com/x-pertknight/uma-disputes-live", 26, SOFT))
    p.append("</svg>")
    open("charts/summary.svg", "w").write("\n".join(p))
    return v


def render_size(name, w, h):
    png = name.replace(".svg", ".png")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}",
                    f"--screenshot={os.path.abspath(png)}", "file://" + os.path.abspath(name)], check=True, capture_output=True)
    print("wrote", png)


if __name__ == "__main__":
    os.makedirs("charts", exist_ok=True)
    chart_outcomes(), chart_mix(), chart_time(), chart_first_later()
    for f in sorted(os.listdir("charts")):
        if f.endswith(".svg") and f != "summary.svg":
            render("charts/" + f)
    print(chart_summary())
    render_size("charts/summary.svg", 1080, 1350)
