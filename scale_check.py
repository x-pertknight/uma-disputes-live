"""Scale check: one recent day of ProposePrice logs per contract, then extrapolate.

Also checks both addresses hold contract code and that each log's topic0 matches.
Output stays local (data/raw_local/scale/), because raw logs carry wallet addresses.
"""
import json
import os
import time

import rpc

BLOCKS_PER_DAY = 43200  # about 2.0 s per Polygon block; measured below from timestamps


def block_time(n):
    return int(rpc.call("eth_getBlockByNumber", [hex(n), False])["timestamp"], 16)


def main():
    head = int(rpc.call("eth_blockNumber", []), 16)
    print("chainId", int(rpc.call("eth_chainId", []), 16), "head", head)
    # use a day that ends 1000 blocks behind head, so the range is final
    end = head - 1000
    start = end - BLOCKS_PER_DAY + 1
    span = block_time(end) - block_time(start)
    print("seconds covered by", BLOCKS_PER_DAY, "blocks:", span, "(86400 = exactly one day)")
    os.makedirs("data/raw_local/scale", exist_ok=True)
    for name, addr in rpc.CONTRACTS.items():
        code = rpc.call("eth_getCode", [addr, "latest"])
        stats = {}
        t0 = time.time()
        # fetch in 20,000-block pieces so one failing piece does not discard the day
        logs = []
        for s in range(start, end + 1, 20000):
            logs += rpc.get_logs(addr, rpc.TOPICS["ProposePrice"], s, min(s + 19999, end), stats)
        secs = time.time() - t0
        bad = [l for l in logs if l["topics"][0] != rpc.TOPICS["ProposePrice"]]
        wrong_addr = [l for l in logs if l["address"].lower() != addr]
        print(json.dumps({"contract": name, "code_bytes": (len(code) - 2) // 2, "logs": len(logs),
                          "fetch_seconds": round(secs, 1), "stats": stats,
                          "bad_topic": len(bad), "wrong_address": len(wrong_addr),
                          "first_block": start, "last_block": end}))
        with open(f"data/raw_local/scale/{name}_propose_1day.json", "w") as f:
            json.dump(logs, f)


if __name__ == "__main__":
    main()
