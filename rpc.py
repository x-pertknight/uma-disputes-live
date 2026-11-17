"""Minimal JSON-RPC helper for public Polygon endpoints (standard library only)."""
import json
import os
import time
import urllib.request

# Tenderly's public gateway accepted 50,000-block ranges in testing on 16 Nov 2026;
# publicnode's cap dropped from 1,000 to 10 blocks under load, so it is only a fallback.
ENDPOINT = os.environ.get("UMA_RPC", "https://polygon.gateway.tenderly.co")
FALLBACK_ENDPOINT = "https://polygon-bor-rpc.publicnode.com"

# Contracts: UMA networks/137.json (OOv2) and UMA docs / UMIP-189 (managed proxy).
CONTRACTS = {
    "OOv2": "0xee3afe347d5c74317041e2618c49534daf887c24",
    "ManagedOOv2": "0x2c0367a9db231ddebd88a94b4f6461a6e47c58b1",
}

# topic0 = keccak256(event signature), computed with `cast keccak` (see DOCS_FIRST.md 1.2)
TOPICS = {
    "ProposePrice": "0x6e51dd00371aabffa82cd401592f76ed51e98a9ea4b58751c70463a2c78b5ca1",
    "DisputePrice": "0x5165909c3d1c01c5d1e121ac6f6d01dda1ba24bc9e1f975b5a375339c15be7f3",
    "Settle": "0x3f384afb4bd9f0aef0298c80399950011420eb33b0e1a750b20966270247b9a0",
}


def call(method, params, endpoint=ENDPOINT, retries=4):
    """One JSON-RPC call. Retries transient failures; raises RpcError on RPC errors.

    HTTP 429 (rate limit) is retried up to 10 times with a growing wait. It must not
    surface as an error, because get_logs splits ranges on errors and that would add calls.
    """
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    failures = limited = 0
    while True:
        try:
            req = urllib.request.Request(
                endpoint, body, {"content-type": "application/json", "user-agent": "uma-monitor/0.1"})
            with urllib.request.urlopen(req, timeout=60) as r:
                out = json.load(r)
        except Exception as exc:  # network error or bad JSON: back off and retry
            if getattr(exc, "code", None) == 429 and limited < 10:
                limited += 1
                time.sleep(5 * limited)
                continue
            failures += 1
            if failures >= retries:
                raise RpcError(str(exc))
            time.sleep(2 ** failures)
            continue
        if "error" in out:
            raise RpcError(json.dumps(out["error"]))
        return out["result"]


class RpcError(Exception):
    pass


def get_logs(address, topic0, start, end, stats, endpoint=ENDPOINT):
    """All logs in [start, end]. On any RPC error the range is split in half.

    stats collects the number of calls, splits and the smallest range used, so the
    README can state how the endpoint behaved.
    """
    # topic0 may be one hash, or a full topics list (e.g. to filter on the disputer topic)
    topics = topic0 if isinstance(topic0, list) else [topic0]
    params = [{"address": address, "topics": topics, "fromBlock": hex(start), "toBlock": hex(end)}]
    stats["calls"] = stats.get("calls", 0) + 1
    try:
        return call("eth_getLogs", params, endpoint)
    except RpcError as exc:
        if start >= end:
            raise
        stats["splits"] = stats.get("splits", 0) + 1
        stats.setdefault("last_error", str(exc)[:200])
        mid = (start + end) // 2
        return (get_logs(address, topic0, start, mid, stats, endpoint)
                + get_logs(address, topic0, mid + 1, end, stats, endpoint))


def batch(method, params_list, endpoint=ENDPOINT, retries=8):
    """Send many calls of one method in a single HTTP request. Results keep input order."""
    body = json.dumps([{"jsonrpc": "2.0", "id": i, "method": method, "params": p}
                       for i, p in enumerate(params_list)]).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                endpoint, body, {"content-type": "application/json", "user-agent": "uma-monitor/0.1"})
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.load(r)
            by_id = {o["id"]: o for o in out}
            if len(by_id) != len(params_list) or any("error" in o for o in by_id.values()):
                raise RpcError("batch had errors or missing answers")
            return [by_id[i]["result"] for i in range(len(params_list))]
        except Exception as exc:
            if attempt == retries - 1:
                raise RpcError(str(exc)[:200])
            time.sleep(min(30, 3 * (attempt + 1)))  # also covers HTTP 429
