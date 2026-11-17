"""Fetch every stream up to the head (minus a finality margin). Safe to re-run.

Streams per contract:
  ProposePrice  last 90 days   (compact rows)
  DisputePrice  last 365 days  (full logs, local only)
  Settle        from the first dispute, filtered on the disputer topic so that only
                settlements of disputed requests are returned. Settle is emitted for
                every settled request (millions a year), disputed or not.
"""
import time

import decode
import fetch
import rpc

PROPOSAL_DAYS = 90
DISPUTE_DAYS = 365


def pad_topic(addr):
    return "0x" + "0" * 24 + addr[2:]


def disputers():
    """Distinct disputer wallets seen so far. Used only to build the query filter."""
    rows = fetch.read_jsonl("disputes_raw")
    return sorted({decode.decode_log("DisputePrice", r["log"])["disputer"] for r in rows})


def set_head(state):
    head = int(rpc.call("eth_blockNumber", []), 16) - fetch.FINALITY_BLOCKS
    state["head_block"] = head
    state["head_ts"] = fetch.block_ts(head)
    return head


def sync_stream(state, name, addr, event, window_days, head, sink, topics=None):
    key = f"{name}:{event}"
    if f"{key}:window_start" not in state:
        state[f"{key}:window_start"] = fetch.block_at(state["head_ts"] - window_days * 86400, head)
    start = fetch.start_block(state, key, state[f"{key}:window_start"])
    if start > head:
        return
    stats = {}
    fetch.fetch_range(addr, topics or rpc.TOPICS[event], start, head, stats, sink, key, state)
    print(key, "done", stats, flush=True)


def sync_settles(state, name, addr, head):
    """Settle logs whose disputer topic is one of the known disputers."""
    ds = [pad_topic(a) for a in disputers()]
    topics = [rpc.TOPICS["Settle"], None, None, ds]
    key = f"{name}:Settle"
    first = state.get(f"{name}:DisputePrice:window_start", head)
    state.setdefault(f"{key}:window_start", first)
    sync_stream(state, name, addr, "Settle", 0, head, fetch.jsonl_sink("settles_raw", name), topics)


def sync_all():
    state = fetch.load_state()
    head = set_head(state)
    for name, addr in rpc.CONTRACTS.items():
        sync_stream(state, name, addr, "ProposePrice", PROPOSAL_DAYS, head,
                    fetch.proposals_sink(name))
        sync_stream(state, name, addr, "DisputePrice", DISPUTE_DAYS, head,
                    fetch.jsonl_sink("disputes_raw", name))
        sync_settles(state, name, addr, head)
    fetch.save_state(state)
    return state


if __name__ == "__main__":
    t0 = time.time()
    sync_all()
    print("sync finished in", round(time.time() - t0), "s", flush=True)
