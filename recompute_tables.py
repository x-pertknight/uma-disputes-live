"""Rebuild the published tables from data/disputes.csv and compare them with the committed CSVs.

Offline, standard library only. Reads data/disputes.csv, data/block_times.csv, data/state.json,
data/adapter_reset_logic.json and data/requester_labels.json, rebuilds each table below with the
same functions update.py uses, and compares the result byte for byte with data/<table>.csv.
Exits 1 on any difference.   python3 -I -B recompute_tables.py

Not rebuilt here, because they need inputs that are not in the repo (data/raw_local/ is
git-ignored, it holds wallet addresses): rates.csv, requester_split_90d.csv and
daily_proposals_90d.csv need the proposal logs; overturn_first_vs_later_dispute.csv needs the
question hash and request time of each dispute; concentration_by_month.csv needs the disputer
wallets.
"""
import csv
import datetime as dt
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

import breakdown  # noqa: E402
import markets  # noqa: E402
import metrics  # noqa: E402
import report  # noqa: E402


def load():
    """(disputes, settles, types) shaped like metrics.load_disputes / load_settles, from the CSV."""
    with open("data/block_times.csv") as f:
        ts = {int(r[0]): int(r[1]) for r in csv.reader(f) if r and r[0] != "block"}
    disputes, settles, types = {}, {}, {}
    with open("data/disputes.csv", newline="") as f:
        for r in csv.DictReader(f):
            k = (r["oracle"], r["request_key"])
            t = int(dt.datetime.strptime(r["dispute_time"], "%Y-%m-%d %H:%M:%S")
                    .replace(tzinfo=dt.timezone.utc).timestamp())
            title, _, desc = r["question"].partition(" | ")
            # The CSV keeps the scrubbed question text only. Re-wrap it in the JSON ancillary
            # format so decode.parse_question returns the same title for the cluster rule.
            anc = json.dumps({"title": title, "description": desc}).encode()
            disputes[k] = {"contract": r["oracle"], "key": r["request_key"], "requester": r["requester"],
                           "block": int(r["dispute_block"]), "time": t, "tx": r["dispute_tx"],
                           "log_index": int(r["log_index"]), "price": int(r["proposed_price"]), "ancillary": anc,
                           "question": r["question"]}
            types[k] = r["market_type"]
            if r["settle_block"]:
                b = int(r["settle_block"])
                settles[k] = {"block": b, "time": ts[b], "tx": r["settle_tx"], "price": int(r["settled_price"])}
    return disputes, settles, types


def tables(disputes, settles, types, head_ts):
    labels = {a: v["what_it_is"] for a, v in json.load(open("data/requester_labels.json")).items()}
    old = breakdown.matured(disputes, head_ts)
    mix, _ = markets.mix_table(markets.cells(old, settles, types))
    # The question column is copied from disputes.csv as written: rebuilding it from the
    # already truncated text would drop a trailing space that the 160 character cut can leave.
    opened = [dict(o, question=disputes[o["key"]]["question"], market_type=types[o["key"]],
                   venue=markets.venue(disputes[o["key"]]["ancillary"]))
              for o in metrics.open_disputes(disputes, settles, head_ts)]
    return {
        "time_to_settle_by_month": metrics.settle_hours_by_month(old, settles),
        "overturn_by_month": metrics.overturn_by_month(old, settles),
        "overturn_by_value_class": breakdown.value_classes(old, settles, head_ts),
        "outcome_shares_by_month": breakdown.outcome_shares(disputes, settles, head_ts),
        "overturn_by_cluster": breakdown.cluster_table(old, settles, head_ts),
        "overturn_by_requester": breakdown.by_requester(old, settles, head_ts, labels),
        "overturn_by_requester_month": breakdown.requester_by_month(old, settles, labels),
        "market_type_by_month": mix,
        "daily_disputes_90d": metrics.daily_disputes(disputes, head_ts),
        "monthly_disputes": metrics.monthly_counts(disputes),
        "open_disputes": [dict({k: v for k, v in r.items() if k != "key"}, disputed_at=report.utc(r["disputed_at"]))
                          for r in opened],
    }


def as_csv(rows):
    """The bytes report.write_csv would write for these rows."""
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def main():
    head_ts = json.load(open("data/state.json"))["head_ts"]
    bad = 0
    for name, rows in tables(*load(), head_ts).items():
        path = f"data/{name}.csv"
        with open(path, newline="") as f:
            committed = f.read()
        if rows and as_csv(rows) == committed:
            print(f"same {path}")
            continue
        bad += 1
        print(f"MISMATCH {path}")
        new = as_csv(rows).splitlines() if rows else []
        for i, (a, b) in enumerate(zip(committed.splitlines() + [""] * len(new), new + [""] * len(committed))):
            if a != b:
                print(f"  line {i + 1}\n    committed: {a}\n    rebuilt:   {b}")
                break
    print(f"FAIL: {bad} table(s) differ from data/disputes.csv" if bad else "all rebuilt tables match")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
