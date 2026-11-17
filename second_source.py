"""Decoding check of 25 disputed requests, drawn with a fixed seed and stratified (not a random sample).

The log decoder in decode.py is ours. Here the same facts are read a different way:
  * getRequest() on the oracle contract itself returns the stored proposedPrice,
    resolvedPrice and settled flag (state, not logs), decoded by Foundry's `cast`;
  * `cast receipt` and `cast block` give the transaction's block and the block timestamp.
Draw: fixed seed, 10 overturned, 10 upheld, 5 resets. Same endpoint, contract and chain as the main pull,
so this tests the decoding, not the data's independence. Responses are cached in
data/raw_local/second_source/ (they contain wallet addresses); the published result,
data/second_source_sample.csv, does not.
"""
import hashlib
import json
import os
import random
import subprocess
import time

import metrics
import rpc

SEED = 20261116
DRAW = {"overturned": 10, "upheld": 10, "reset": 5}
CACHE = "data/raw_local/second_source"
GET_REQUEST = ("getRequest(address,bytes32,uint256,bytes)((address,address,address,bool,"
               "(bool,bool,bool,bool,bool,uint256,uint256),int256,int256,uint256,uint256,uint256))")


def cast(args):
    """Run cast with a disk cache keyed on the arguments. One request at a time."""
    os.makedirs(CACHE, exist_ok=True)
    path = f"{CACHE}/{hashlib.sha256(' '.join(args).encode()).hexdigest()[:24]}.json"
    if os.path.exists(path):
        return json.load(open(path))
    for attempt in range(4):
        out = subprocess.run(["cast", *args, "--rpc-url", rpc.ENDPOINT, "--json"], capture_output=True, text=True)
        if out.returncode == 0:
            time.sleep(0.4)
            json.dump(json.loads(out.stdout), open(path, "w"))
            return json.loads(out.stdout)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(out.stderr[:200])


def category(k, d, s):
    if s["price"] == metrics.TOO_EARLY:
        return "reset"
    return "upheld" if s["price"] == d["price"] else "overturned"


def draw(disputes, settles):
    rng = random.Random(SEED)
    pools = {c: [] for c in DRAW}
    for k in sorted(disputes):
        if k in settles:
            pools[category(k, disputes[k], settles[k])].append(k)
    return [(c, k) for c, n in DRAW.items() for k in rng.sample(pools[c], n)]


def tx_facts(tx, block, log_index, oracle, topic0):
    """Block number and block time per cast, and whether the log at our index is the right event."""
    rc = cast(["receipt", tx])
    blk = cast(["block", str(int(rc["blockNumber"], 16)) if isinstance(rc["blockNumber"], str) else str(rc["blockNumber"])])
    log = next((l for l in rc["logs"] if int(str(l["logIndex"]), 16 if str(l["logIndex"]).startswith("0x") else 10) == log_index), None)
    ts = blk["timestamp"]
    return {"block_ok": int(str(rc["blockNumber"]), 16 if str(rc["blockNumber"]).startswith("0x") else 10) == block,
            "log_ok": bool(log) and log["address"].lower() == oracle and log["topics"][0] == topic0,
            "block_time": int(str(ts), 16 if str(ts).startswith("0x") else 10)}


def check_one(cat, k, d, s):
    oracle = rpc.CONTRACTS[d["contract"]]
    req = cast(["call", oracle, GET_REQUEST, d["requester"], d["identifier"], str(d["req_ts"]), "0x" + d["ancillary"].hex()])
    st = req[0] if isinstance(req[0], list) else req
    proposed, resolved, settled = int(st[5]), int(st[6]), st[3] in (True, "true", "True")
    dt = tx_facts(d["tx"], d["block"], d["log_index"], oracle, rpc.TOPICS["DisputePrice"])
    stx = tx_facts(s["tx"], s["block"], s["log_index"], oracle, rpc.TOPICS["Settle"])
    row = {"category": cat, "oracle": d["contract"], "request_key": k, "dispute_tx": d["tx"], "settle_tx": s["tx"],
           "our_proposed": d["price"], "contract_proposed": proposed, "our_settled": s["price"], "contract_resolved": resolved,
           "contract_settled_flag": settled, "our_dispute_time": d["time"], "chain_dispute_time": dt["block_time"],
           "our_settle_time": s["time"], "chain_settle_time": stx["block_time"]}
    row["match"] = (proposed == d["price"] and resolved == s["price"] and settled and dt["block_ok"] and dt["log_ok"]
                    and stx["block_ok"] and stx["log_ok"] and dt["block_time"] == d["time"] and stx["block_time"] == s["time"])
    return row


def run():
    disputes, _ = metrics.load_disputes()
    settles = metrics.load_settles()
    rows = [check_one(c, k, disputes[k], settles[k]) for c, k in draw(disputes, settles)]
    import report
    report.write_csv("data/second_source_sample.csv", rows)
    bad = [r for r in rows if not r["match"]]
    print(f"second-source sample: {len(rows) - len(bad)} of {len(rows)} match")
    for r in bad:
        print("MISMATCH", {k: v for k, v in r.items() if k not in ("dispute_tx", "settle_tx")})
    return rows


if __name__ == "__main__":
    run()
