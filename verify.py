"""Truncation check: re-fetch windows with different chunk boundaries, compare log sets.

If the RPC silently dropped logs from a large range, a re-query over smaller, shifted
pieces would return more logs than we stored. Result goes to data/verification.json.
"""
import csv
import json

import fetch
import rpc

PIECE = 7777          # deliberately unlike the 50,000-block pull steps
WINDOW = 40000        # blocks re-checked per sample
SAMPLES = (0.15, 0.5, 0.85, 0.999)   # positions inside the fetched range


def stored_ids(stream, contract, lo, hi):
    """(tx, log_index) pairs we stored for blocks in [lo, hi]."""
    ids = set()
    if stream == "ProposePrice":
        with open(f"{fetch.RAW}/proposals.csv") as f:
            for r in csv.DictReader(f):
                if r["contract"] == contract and lo <= int(r["block"]) <= hi:
                    ids.add((r["tx"], int(r["log_index"])))
    else:
        for r in fetch.read_jsonl("disputes_raw"):
            l = r["log"]
            if r["contract"] == contract and lo <= int(l["blockNumber"], 16) <= hi:
                ids.add((l["transactionHash"], int(l["logIndex"], 16)))
    return ids


def refetch_ids(addr, event, lo, hi):
    ids, stats = set(), {}
    for s in range(lo, hi + 1, PIECE):
        for l in rpc.get_logs(addr, rpc.TOPICS[event], s, min(s + PIECE - 1, hi), stats):
            ids.add((l["transactionHash"], int(l["logIndex"], 16)))
    return ids


def verify(state):
    results = []
    for name, addr in rpc.CONTRACTS.items():
        for event in ("ProposePrice", "DisputePrice"):
            first = state[f"{name}:{event}:window_start"]
            last = state[f"{name}:{event}"]
            for frac in SAMPLES:
                lo = int(first + (last - first - WINDOW) * frac)
                hi = lo + WINDOW - 1
                a, b = stored_ids(event, name, lo, hi), refetch_ids(addr, event, lo, hi)
                results.append({"contract": name, "event": event, "from_block": lo, "to_block": hi,
                                "stored": len(a), "refetched": len(b), "only_stored": len(a - b),
                                "only_refetched": len(b - a), "match": a == b})
    json.dump(results, open("data/verification.json", "w"), indent=1)
    return results
