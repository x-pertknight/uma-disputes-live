"""Which requester contracts use the "reset on the first dispute" logic?

For every requester labelled UmaCtfAdapter in data/requester_labels.json, download the
verified source from Sourcify (keyless) and look at priceDisputed(): the logic we rely on is
  first dispute  -> _reset(): a NEW price request is sent, the disputed one is left behind
  later dispute  -> sets refund = true and returns, so the market waits for the new request
and resolve() / _resolve(): the price it reads is the one for questionData.requestTimestamp, and _reset() is
where that timestamp is moved to the new request. Both are checked as text patterns in the source.
Writes data/adapter_reset_logic.json: {address: {"dispute_reset_once": bool, "resolve_reads_current_request": bool,
"confirmed": bool} or "source not read"}.
"""
import json
import urllib.request

LABELS, OUT = "data/requester_labels.json", "data/adapter_reset_logic.json"


def body_of(src, name, size):
    return src[src.index(name):][:size]


def check_source(checksum_addr):
    url = f"https://sourcify.dev/server/v2/contract/137/{checksum_addr}?fields=sources"
    src = json.load(urllib.request.urlopen(url))["sources"]["src/UmaCtfAdapter.sol"]["content"]
    dispute = body_of(src, "function priceDisputed", 1400)
    resolve = body_of(src, "function _resolve", 900)
    reset = body_of(src, "function _reset", 700)
    once = "if (questionData.reset)" in dispute and "refund = true" in dispute and "_reset(" in dispute
    # resolve reads the price of questionData.requestTimestamp, and _reset assigns that field
    reads = "settleAndGetPrice" in resolve and "questionData.requestTimestamp" in resolve \
        and "questionData.requestTimestamp = requestTimestamp" in reset
    return {"dispute_reset_once": once, "resolve_reads_current_request": reads, "confirmed": once and reads}


def run():
    out = {}
    for addr, v in json.load(open(LABELS)).items():
        if v.get("contract_name") != "UmaCtfAdapter":
            continue
        try:
            out[addr] = check_source(v["checksum"])
        except Exception:                  # source layout differs or Sourcify has no file
            out[addr] = "source not read"
    json.dump(out, open(OUT, "w"), indent=1)
    print(out)


if __name__ == "__main__":
    run()
