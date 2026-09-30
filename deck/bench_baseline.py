"""Same investigation, hand-written in Python, to quantify interpreter overhead.

The honest comparison for a DSL is not "is it fast" but "what does the
abstraction cost over the code you would otherwise write by hand".
"""
import csv, json, math, os, random, sys, tempfile, time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench import make_events, make_flows, SCALES, run_scale          # noqa: E402
from jocky.runtime import run_source                                   # noqa: E402


def entropy(s):
    if not s:
        return 0.0
    c = Counter(s)
    n = len(s)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def baseline(events, flows, intel):
    """The equivalent of the JOCKY bench script, written directly."""
    suspect = [e for e in events
               if entropy(e["command_line"]) > 4.0 and "powershell" in e["image"]]
    ext = [f for f in flows
           if f["direction"] == "outbound" and f["dst_ip"] in intel
           or (f["direction"] == "outbound" and not f["dst_ip"].startswith(("10.", "172.", "192.")))]
    small = [f for f in flows
             if f["direction"] == "outbound"
             and not f["dst_ip"].startswith(("10.", "172.", "192."))
             and int(f["bytes"]) < 2000]
    groups = Counter((f["dst_ip"], f["dst_port"]) for f in small)
    beacon = sorted(groups.items(), key=lambda kv: -kv[1])
    intel_flows = [f for f in flows if f["dst_ip"] in intel]
    tl = sorted(events, key=lambda e: e["timestamp"])
    return len(suspect), len(beacon), len(intel_flows), len(tl)


if __name__ == "__main__":
    rng = random.Random(20260921)
    rows = []
    for n in SCALES:
        events = make_events(n, rng)
        flows = make_flows(n // 2, rng)
        intel = set(["185.234.72.19", "45.133.1.87", "91.219.236.14", "103.75.190.22"])

        t0 = time.perf_counter(); baseline(events, flows, intel)
        py_ms = (time.perf_counter() - t0) * 1000

        # load cost, isolated
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "events.json"), "w", encoding="utf-8") as fh:
                json.dump(events, fh)
            d0 = os.getcwd(); os.chdir(d)
            t0 = time.perf_counter()
            json.load(open("events.json", encoding="utf-8"))
            load_ms = (time.perf_counter() - t0) * 1000
            os.chdir(d0)

        jk = run_scale(n, rng)
        rows.append({
            "events": n,
            "python_ms": round(py_ms, 1),
            "jocky_ms": jk["exec_ms"],
            "overhead_x": round(jk["exec_ms"] / py_ms, 1),
            "evidence_load_ms": round(load_ms, 1),
        })
        print(f"{n:>7,}  python {py_ms:>8.1f} ms   jocky {jk['exec_ms']:>9.1f} ms   "
              f"overhead {rows[-1]['overhead_x']:>5.1f}x   json-load {load_ms:>6.1f} ms")

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "bench_baseline.json"), "w", encoding="utf-8") as fh:
        json.dump({"baseline": rows}, fh, indent=2)
