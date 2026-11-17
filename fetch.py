"""Incremental log fetching with cursors. Re-running never duplicates rows.

Layout (data/raw_local/ is git-ignored because raw logs carry proposer/disputer wallets):
  proposals.csv        compact proposal rows, no wallet other than the requester contract
  disputes_raw.jsonl   full DisputePrice logs
  settles_raw.jsonl    full Settle logs (only for disputers seen in DisputePrice)
  state.json           last block fetched per stream
"""
import csv
import json
import os
import time

import decode
import rpc

RAW = "data/raw_local"
STATE = "data/state.json"
STEP = int(os.environ.get("UMA_STEP", 25000))            # blocks per request; 50k can exceed the endpoint's 20,000-log cap on busy days
FINALITY_BLOCKS = 256   # about 6 minutes: stay behind the head to avoid reorg rows
PROPOSAL_COLS = ["contract", "block", "tx", "log_index", "requester", "key", "qhash", "req_ts", "price"]


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {}


def save_state(state):
    tmp = STATE + ".tmp"
    json.dump(state, open(tmp, "w"), indent=1, sort_keys=True)
    os.replace(tmp, STATE)  # atomic: a crash never leaves a half-written state


# ---- block / time helpers -------------------------------------------------

def block_ts(n, cache={}):
    if n not in cache:
        cache[n] = int(rpc.call("eth_getBlockByNumber", [hex(n), False])["timestamp"], 16)
    return cache[n]


def block_at(target_ts, head):
    """First block whose timestamp is >= target_ts (binary search)."""
    lo, hi = max(1, head - int(time.time() - target_ts) - 1000), head
    while lo < hi:
        mid = (lo + hi) // 2
        if block_ts(mid) < target_ts:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ---- generic chunked fetch ------------------------------------------------

def fetch_range(addr, topics, start, end, stats, on_logs, cursor_key, state):
    """Walk [start, end] in STEP pieces. After each piece: write rows, then move cursor."""
    for s in range(start, end + 1, STEP):
        e = min(s + STEP - 1, end)
        logs = rpc.get_logs(addr, topics, s, e, stats)
        logs = [l for l in logs if not l.get("removed")]
        on_logs(logs)
        state[cursor_key] = e
        save_state(state)
        print(f"  {cursor_key} to block {e}: +{len(logs)} logs", flush=True)
        time.sleep(0.2)  # be polite to a free public endpoint


def start_block(state, key, default_start):
    return max(default_start, state.get(key, 0) + 1)


# ---- sinks ----------------------------------------------------------------

def proposals_sink(contract):
    def write(logs):
        os.makedirs(RAW, exist_ok=True)
        path = f"{RAW}/proposals.csv"
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(PROPOSAL_COLS)
            for l in logs:
                d = decode.decode_log("ProposePrice", l)
                w.writerow([contract] + [d[c] for c in PROPOSAL_COLS[1:]])
    return write


def jsonl_sink(name, contract):
    def write(logs):
        os.makedirs(RAW, exist_ok=True)
        with open(f"{RAW}/{name}.jsonl", "a") as f:
            for l in logs:
                f.write(json.dumps({"contract": contract, "log": l}) + "\n")
    return write


def read_jsonl(name):
    """Raw log rows, de-duplicated on (contract, tx, log index)."""
    path = f"{RAW}/{name}.jsonl"
    seen, out = set(), []
    if os.path.exists(path):
        for line in open(path):
            r = json.loads(line)
            k = (r["contract"], r["log"]["transactionHash"], r["log"]["logIndex"])
            if k not in seen:
                seen.add(k)
                out.append(r)
    return out
