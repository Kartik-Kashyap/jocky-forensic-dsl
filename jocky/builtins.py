"""Built-in functions available inside JOCKY expressions.

These are the analysis primitives a script can call on a field value:
hashing, entropy measurement, address classification, string and numeric
helpers. All pure functions, all safe on malformed input.
"""

import hashlib
import ipaddress
import math
from collections import Counter
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# numeric / string helpers
# ---------------------------------------------------------------------------

def _s(v):
    return "" if v is None else str(v)


def fn_lower(v):
    return _s(v).lower()


def fn_upper(v):
    return _s(v).upper()


def fn_len(v):
    if v is None:
        return 0
    if isinstance(v, (list, tuple, dict, str)):
        return len(v)
    return len(_s(v))


def fn_int(v):
    try:
        return int(float(_s(v)))
    except (TypeError, ValueError):
        return 0


def fn_abs(v):
    try:
        return abs(float(v))
    except (TypeError, ValueError):
        return 0


def fn_round(v, places=0):
    try:
        n = round(float(v), int(places))
    except (TypeError, ValueError):
        return 0
    return int(n) if n == int(n) else n


# ---------------------------------------------------------------------------
# hashing — hash any field value to compare against threat-intel lists
# ---------------------------------------------------------------------------

def fn_sha256(v):
    return hashlib.sha256(_s(v).encode("utf-8", "replace")).hexdigest()


def fn_md5(v):
    return hashlib.md5(_s(v).encode("utf-8", "replace")).hexdigest()


# ---------------------------------------------------------------------------
# entropy — the workhorse for spotting packed, encrypted or encoded content
# ---------------------------------------------------------------------------

def fn_entropy(v):
    """Shannon entropy (bits per byte) of the value's bytes.

    ~0 for constant data, ~3-4 for English text, >4.5 usually means the
    content is encoded, compressed or encrypted.
    """
    data = _s(v).encode("utf-8", "replace")
    if not data:
        return 0.0
    counts = Counter(data)
    n = len(data)
    return round(-sum((c / n) * math.log2(c / n) for c in counts.values()), 4)


# ---------------------------------------------------------------------------
# address classification — is this destination on the public internet?
# ---------------------------------------------------------------------------

def _addr(v):
    try:
        return ipaddress.ip_address(_s(v).strip())
    except ValueError:
        return None


def fn_is_private_ip(v):
    a = _addr(v)
    return bool(a and (a.is_private or a.is_loopback or a.is_link_local
                       or a.is_reserved or a.is_multicast))


def fn_is_public_ip(v):
    a = _addr(v)
    return bool(a and not (a.is_private or a.is_loopback or a.is_link_local
                           or a.is_reserved or a.is_multicast))


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------

def fn_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fn_epoch(v):
    """ISO-8601 timestamp string -> epoch seconds. 0 if unparseable."""
    text = _s(v).strip().replace("Z", "+00:00")
    for parser in (datetime.fromisoformat,):
        try:
            dt = parser(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return 0


def fn_age_minutes(v):
    """Minutes between the given timestamp and now (negative if in future)."""
    e = fn_epoch(v)
    if not e:
        return 0
    return int((datetime.now(timezone.utc).timestamp() - e) / 60)


REGISTRY = {
    "lower": (fn_lower, 1, 1),
    "upper": (fn_upper, 1, 1),
    "len": (fn_len, 1, 1),
    "int": (fn_int, 1, 1),
    "abs": (fn_abs, 1, 1),
    "round": (fn_round, 1, 2),
    "sha256": (fn_sha256, 1, 1),
    "md5": (fn_md5, 1, 1),
    "entropy": (fn_entropy, 1, 1),
    "is_private_ip": (fn_is_private_ip, 1, 1),
    "is_public_ip": (fn_is_public_ip, 1, 1),
    "now": (fn_now, 0, 0),
    "epoch": (fn_epoch, 1, 1),
    "age_minutes": (fn_age_minutes, 1, 1),
}


def describe():
    """Introspection for the console's Built-ins panel."""
    docs = {
        "lower": "Lowercase a string.",
        "upper": "Uppercase a string.",
        "len": "Length of a string or list.",
        "int": "Coerce to integer (0 on failure).",
        "abs": "Absolute value.",
        "round": "Round to N decimal places.",
        "sha256": "SHA-256 of a field value — compare against intel hashes.",
        "md5": "MD5 of a field value.",
        "entropy": "Shannon entropy in bits/byte; >4.5 suggests encoded or packed data.",
        "is_private_ip": "True for RFC1918 / loopback / link-local / reserved addresses.",
        "is_public_ip": "True for routable internet addresses.",
        "now": "Current UTC time as an ISO-8601 string.",
        "epoch": "ISO-8601 timestamp to epoch seconds.",
        "age_minutes": "Minutes elapsed since a timestamp.",
    }
    return [
        {"name": name, "arity": arity, "doc": docs.get(name, "")}
        for name, (_, lo, hi) in sorted(REGISTRY.items())
        for arity in [f"{lo}" if lo == hi else f"{lo}–{hi}"]
    ]
