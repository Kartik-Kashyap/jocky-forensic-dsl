# JOCKY — demo video shot list

Everything below is real; nothing needs staging. Full run is about **3 minutes**.

`[90s]` marks a shot you can **drop** to compress into 90 seconds — everything
except Shot 3 is droppable. Keep Shot 3 whatever you do; it's the one that
carries the idea.

---

## Pre-flight (do this before you hit record)

```powershell
cd C:\Users\karti\SIH-Forensic-PS2
python -m unittest discover -s tests -t . -q     # expect: OK, 50 tests
python -m jocky run scripts/beacon_hunt.jky      # expect: 6 findings, exit 0
python -m jocky serve --port 8787                # leave running in a second tab
```

Then set the terminal up so it reads well on camera:

- **Font size 16–18pt.** If the window is 1680 wide, the console screenshots in
  `deck/assets/` show the proportions that look right.
- Clear the screen (`cls`). Keep the console in a **second tab**, already loaded
  at `http://127.0.0.1:8787`, so you can cut to it without typing on camera.
- Close Slack / mail / anything that pops a notification.

---

## Shot 1 — the problem, in one line `[90s]`

**Do:** nothing on screen, or hold the console's `Compatibility` tab.
**Say:** *"When an intrusion is investigated, the examiner stitches together
Velociraptor, Chainsaw, KAPE, KQL and throwaway scripts. Six tools, six output
formats, and at the end of it a finding that cites nothing — so the conclusion
can't be reproduced or defended. JOCKY is one language for that whole job."*

**Don't** read the problem statement. One sentence, then show the tool. The
video is judged on the demo, not the intro.

---

## Shot 2 — one script, one command, a whole case `[90s]`

```powershell
python -m jocky run scripts/beacon_hunt.jky
```

**Point the camera at three things as they scroll past:**

1. The **findings list**, severity-tagged — `critical` for the log tampering and
   the intel-IP contact, `high` for the Office→scripting-child and the Temp-dir
   binary.
2. The **cited result sets** under each finding. *"Every finding names the query
   that produced it. That's enforced by the grammar, not by the examiner's
   discipline."*
3. The **timeline**, stitched from two different evidence files.

**Say:** *"93 lines of JOCKY. Three evidence sources — host events, netflow,
process table. Six findings, a timeline, and a report. One command."*

---

## Shot 3 — the money shot: it refuses to lie `[never cut]`

This is the UVP. Do not skip it. There are **two** refusals — show both, in this
order.

**3a — a typo is caught with a caret.** In the console (`Investigate` tab), open
`scripts/triage.jky` and paste this line at the bottom — it's valid except for
the triple `=`:

```
let broken = procs |> where (name === "x")
```

Hit **Run investigation**. You get (line number will be wherever you pasted it):

```
✗ syntax error triage.jky:13:37
  expected a value in this condition, found '='

  13 │ let broken = procs |> where (name === "x")
     │                                     ^
```

**Say:** *"Line, column, the offending line, and a caret under the exact token.
Forensic scripts get reviewed by people who didn't write them, so a parser that
points is worth more than one that just says 'invalid syntax'."*

Delete the line before moving on.

**3b — an uncitable finding will not compile.** Now append this line at the
bottom and Run again:

```
finding "Something I did not actually query" severity high from ghost_data
```

The run **fails**, exit code 1, with:

```
✗ finding cites unknown binding 'ghost_data'
```

**Say the line that matters:** *"The grammar will not let me write a finding that
doesn't name the query behind it. That's the whole thesis — you cannot produce an
uncitable finding in this language, because the language refuses to run one."*

Then delete the line and Run once more so the video ends on a success.

> In the terminal the error prints right after the execution trace and *above*
> the tables, so scroll up or you'll miss it. In the console it renders as a red
> error block, which films better.

---

## Shot 4 — the compiler, out loud `[90s]`

```powershell
python -m jocky compile scripts/beacon_hunt.jky --tokens
python -m jocky compile scripts/beacon_hunt.jky --ast
python -m jocky lint scripts/triage.jky
```

**Say:** *"Lexer, recursive-descent parser, plain nested-dict AST — 332 tokens,
101 nodes, parsed in 2.2 milliseconds. The AST is inspectable and JSON-safe, so
every stage of the pipeline is auditable."*

Then switch to the console's **Compiler** tab and scroll the token stream — it
looks better on camera than terminal text. Finish on `lint` reporting
`✓ no issues found`.


---

## Shot 5 — the console `[90s]`

Open `http://127.0.0.1:8787` (already running from pre-flight). Click through the
tabs, ~4 seconds each, no talking over the first two:

| Tab | What to point at |
|---|---|
| **Investigate** | Script list, editor, findings, tables |
| **Timeline** | The case narrative as a single ordered stream |
| **Evidence** | Per-file SHA-256, record count, column preview — *"every artefact is digested before it's parsed"* |
| **Fleet** | The collector inventory — agents, versions, last-seen. Run `telemetry_audit.jky` in Investigate to turn it into stale-agent findings. |
| **Language** | The full grammar on one page |
| **Compatibility** | The design constraints — see the boundary note below |

**Say (over Evidence):** *"Nothing is written back. Evidence is opened read-only
and hashed at ingest, so you can show a court exactly what you looked at."*

---

## Shot 6 — portability and determinism `[90s]`

```powershell
python -m jocky run scripts/beacon_hunt.jky --case "SIH-2026-DEMO"
```

**Say:** *"The case identifier is a parameter, not a hardcoded string — the same
script runs against any case."*

Now the determinism check. Two runs, compared:

```powershell
python -m jocky run scripts/beacon_hunt.jky --json > run1.json
python -m jocky run scripts/beacon_hunt.jky --json > run2.json
python -c "import json;a=json.load(open('run1.json'));b=json.load(open('run2.json'));[d.get('stats',{}).pop('duration_ms',None) for d in (a,b)];print('IDENTICAL' if a==b else 'DIFFERS')"
```

It prints `IDENTICAL`. **Say:** *"Same digests, same findings, same timeline, byte
for byte — twice. The only thing I excluded is the wall-clock duration, because
that's a measurement of this laptop, not part of the case. A script is a
reviewable artefact you can hand to another examiner or another agency and they
get the same result."*

> Don't use `fc` on the raw files — `duration_ms` differs by a few tenths and the
> diff makes it look non-deterministic when the *results* are identical. Drawing
> that distinction yourself is a stronger point than hiding it.

Clean up afterwards: `del run1.json run2.json`


---

## Shot 7 — close on the boundary `[90s]`

Hold the **Compatibility** tab.

**Say:** *"The problem statement asks for tooling that hides from security
products. We didn't build that, and we want to be explicit about why: a forensic
tool that hides from the endpoint's own evidence is indistinguishable from the
intrusion it's meant to investigate. So JOCKY's answer to 'AV blocks our tooling'
is signed reproducible builds with published hashes for vendor allowlisting, and
documented telemetry sources — ETW, WMI, the USN journal, auditd, netflow. That's
the reading of this problem statement that survives an audit."*

This lands well with judges. Say it plainly and without apology.

---

## What not to film

Do not show, mock up, or describe polymorphic engines, BYOVD, process hollowing,
reflective DLL injection, API unhooking, direct syscalls, kernel patching, or
domain-fronted C2 — not even as a "future work" slide or a greyed-out menu item.
The deck and the repository both state the opposite explicitly, and a video
claiming otherwise contradicts the artefact you're submitting.

---

## Honest numbers if a judge asks

Have `deck/bench_results.json` open in a background tab.

- Interpreter throughput **5,079–7,363 records/sec**, held flat from 10³ to 10⁵ records.
- **20–26× slower** than the equivalent hand-written Python. Stated, not hidden —
  the accepted trade for an auditable interpretable language. Bytecode VM is the
  named next milestone.
- Peak memory **1.9 MB @ 1k → 188 MB @ 100k**, linear.
- **Zero** third-party dependencies. Python 3.11+ stdlib only.
- **50** unit tests, all passing.

Say the slow number before anyone finds it. Volunteering it is what makes the
rest believable.

---

## Retake notes

- If the console errors, it's almost always a **stale server** — restart
  `python -m jocky serve --port 8787` and reload the page.
- Keep `scripts/triage.jky` **clean on disk**. Do the Shot 3 edits live and undo
  them with Ctrl+Z rather than saving the broken version — the console and the
  submission both point at the good copy.
- Record the shots out of order if it's easier — the console tab (Shot 5) has no
  dependency on the terminal shots.
