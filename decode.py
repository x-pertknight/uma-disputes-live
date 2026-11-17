"""Decode ProposePrice / DisputePrice / Settle logs from the UMA optimistic oracles.

ABI layout of the non-indexed data (see DOCS_FIRST.md 1.2). Every event starts with
identifier (word 0), timestamp (word 1) and the offset of ancillaryData (word 2).
Word 3 is the price (proposedPrice or settled price). ancillaryData is a dynamic
`bytes`: at its offset sits a length word, then the bytes.
"""
import hashlib
import json
import re

# 40 hex characters, with or without 0x: removes wallet addresses from question text
ADDR_RE = re.compile(r"(?:0x)?[0-9a-fA-F]{40}")
ZERO_TOPIC = "0x" + "0" * 64


def _int(b, signed=False):
    return int.from_bytes(b, "big", signed=signed)


def _ancillary(data):
    """Return (identifier, timestamp, ancillary bytes) from the event data."""
    offset = _int(data[64:96])
    length = _int(data[offset:offset + 32])
    if offset + 32 + length > len(data):
        raise ValueError("ancillaryData runs past the end of the log data")
    return data[0:32], _int(data[32:64]), data[offset + 32:offset + 32 + length]


def _topic_addr(topic):
    return "0x" + topic[-40:]


def decode_log(event, log):
    """One log to a flat dict. `ancillary` is raw bytes; callers decide what to keep."""
    data = bytes.fromhex(log["data"][2:])
    topics = log["topics"]
    ident, ts, anc = _ancillary(data)
    requester = _topic_addr(topics[1])
    req_bytes = bytes.fromhex(requester[2:])
    out = {
        "block": int(log["blockNumber"], 16),
        "tx": log["transactionHash"],
        "log_index": int(log["logIndex"], 16),
        "requester": requester,
        "req_ts": ts,
        "price": _int(data[96:128], signed=True),
        "ancillary": anc,
        # request key = (requester, identifier, timestamp, ancillaryData); the question
        # hash drops the timestamp so a re-request of the same question can be found
        "key": hashlib.sha256(req_bytes + ident + data[32:64] + anc).hexdigest()[:32],
        "qhash": hashlib.sha256(req_bytes + ident + anc).hexdigest()[:32],
        "identifier": "0x" + ident.hex(),
        "proposer": _topic_addr(topics[2]),
    }
    if event in ("DisputePrice", "Settle"):
        out["disputer"] = _topic_addr(topics[3])
    return out


def _unescape(raw):
    try:
        return json.loads('"' + raw + '"')
    except ValueError:
        return raw


def parse_question(anc):
    """(title, description) from either ancillary format used by Polymarket requests:
    'q: title: T, description: D ...'  or  '{"type":1,"title":"T","description":"D" ...}'.
    Falls back to the raw text as the title when neither pattern fits."""
    text = anc.decode("utf-8", errors="replace")
    t = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if t:
        d = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)', text)
        return _unescape(t.group(1)), _unescape(d.group(1)) if d else ""
    t = re.search(r"title:\s*(.*?),\s*description:\s*(.*)", text, re.S)
    if t:
        return t.group(1), t.group(2)
    return text, ""


def question_text(anc, limit=160):
    """One row style for every request: 'title | description', addresses scrubbed."""
    title, desc = parse_question(anc)
    text = ADDR_RE.sub("[address]", f"{title} | {desc}" if desc else title)
    return " ".join(text.split())[:limit]
