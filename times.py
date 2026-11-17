"""Block timestamps, cached in data/block_times.csv (block number, unix seconds)."""
import csv
import os
import time

import rpc

PATH = "data/block_times.csv"
BATCH = 20  # small batches plus a pause keep the public endpoint from rate limiting


def load():
    if not os.path.exists(PATH):
        return {}
    with open(PATH) as f:
        return {int(r[0]): int(r[1]) for r in csv.reader(f) if r and r[0] != "block"}


def get(blocks):
    """Timestamps for the given block numbers; fetches only what the cache lacks."""
    cache = load()
    missing = sorted(set(blocks) - set(cache))
    new = []
    for i in range(0, len(missing), BATCH):
        chunk = missing[i:i + BATCH]
        res = rpc.batch("eth_getBlockByNumber", [[hex(b), False] for b in chunk])
        new += [(b, int(r["timestamp"], 16)) for b, r in zip(chunk, res)]
        time.sleep(0.25)
    if new:
        write_new(new, not os.path.exists(PATH))
        cache.update(new)
    return cache


def write_new(rows, header):
    with open(PATH, "a", newline="") as f:
        w = csv.writer(f)
        if header:
            w.writerow(["block", "timestamp"])
        w.writerows(rows)
