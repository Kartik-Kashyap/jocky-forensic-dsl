# Research paper brief — JOCKY

Everything a writing model needs to draft a paper on JOCKY. All figures live in
`research/paper-data.json`; use those numbers and no others. Do not invent
results, citations, or user studies.

---

## 1. What the paper is about

**Title candidates**

- *JOCKY: A Domain-Specific Language for Reproducible Computer and Network Forensic Analysis*
- *Provenance by Grammar: Enforcing Citable Findings in a Forensic Query Language*

**One-sentence thesis.** Digital-forensic examinations are assembled from
general-purpose tools and ad-hoc scripts, so a conclusion is only as defensible
as the undocumented pipeline that produced it; JOCKY makes the pipeline the
artifact — a small domain-specific language in which a finding that does not
name the query behind it cannot be expressed, let alone executed.

**The contribution is a design property, not a faster tool.** Lead with that.
The performance numbers exist to characterise the cost of the property, not to
claim an efficiency win. A paper that sells speed will be read as weak; a paper
that sells *auditability at a measured, stated cost* is honest and interesting.

---

## 2. Problem statement

Forensic examiners stitch together multiple tools — Volatility, plaso, KAPE,
Chainsaw, Hayabusa, Velociraptor, plus per-case Python — each with its own
output format. Three consequences:

1. **Every hop loses provenance.** A finding ends up in a report with no
   machine-checkable link to the query that produced it.
2. **Findings arrive without a citable query.** Ad-hoc pipelines produce results
   that cannot be reproduced or defended under cross-examination.
3. **The tooling is built for detection, not for the defensive workflow.**
   Sigma detects. VQL queries. Neither makes a finding citable.

The gap the paper identifies: existing forensic query languages optimise for
*expressing* a search. None of them treats *citation* as a language-level
obligation. Provenance in current practice is a matter of examiner discipline —
a convention documented in NIST SP 800-86 and ISO/IEC 27037, not something a
tool can enforce.

---

## 3. System description

JOCKY is an implemented language, not a proposal. Report it as such, with the
module table from `table_codebase` in the data file.

**Pipeline.** `lexer → recursive-descent parser → AST (plain nested dicts) →
tree-walking interpreter`. The AST being plain dicts is a deliberate choice: it
is inspectable and JSON-safe, so every compilation stage is externally auditable
and the front end can be exercised without executing anything.

**Language surface.** 13 statement forms, 8 pipeline stages (`where`, `select`,
`sort by`, `limit`, `count`, `group by`, `distinct`, `as`), 14 builtin functions
(hashing, entropy, IP classification, time arithmetic), 4 severity levels, and
the operators listed in `table_language_surface`. Four statement types carry the
forensic semantics: `source` (declare evidence), `timeline` (case narrative),
`report` (name the case file), `finding` (raise a severity-tagged result that
*cites a result set by name*).

**The central mechanism.** The `finding` statement has the form
`finding "text" severity <level> from <binding>`. The `<binding>` is mandatory
and is resolved against the set of declared and derived result sets. If it does
not resolve, the run fails with a non-zero exit code and the message
`finding cites unknown binding '...'`. There is no way to write an uncitable
finding, because there is no syntactic form for one. The `lint` subcommand
performs the same check statically, before evidence is read.

Cite `reproducibility_evidence.provenance_rejection_demo` in the data file as the
concrete demonstration.

**Interface.** A loopback-bound HTTP console with 7 tabs (Investigate, Compiler,
Timeline, Evidence, Fleet, Language, Compatibility), a single HTML file with no
build step. The Compiler tab exposes the token stream and AST, which is what
makes the front end inspectable to a reviewer rather than only to its authors.

**Reference investigations.** Four scripts shipped with the interpreter
(`reference_investigations` in the data file), all against one coherent synthetic
incident on host `FIN-WS-014`. `beacon_hunt.jky` is 93 lines, ingests three
evidence sources, and raises six findings — three `critical`, three `high`.

---

## 4. Evaluation method

**This section must be described accurately — do not overstate it.**

- One representative investigation, executed against synthetic evidence at four
  scales: 1k / 5k / 25k / 100k host events, each paired with n/2 network flows,
  giving 1.5k / 7.5k / 37.5k / 150k total records (`table_scaling`).
- Measured with `time.perf_counter` for time and `tracemalloc` for peak memory.
- A **hand-written Python implementation of the same investigation** serves as
  the baseline (`table_overhead_vs_python`), plus isolated evidence-load timing.
- Result stability checked by re-running and diffing the JSON artifacts.
- 50 unit tests across lexer, parser, runtime, builtins and CLI.

**Stated limitations — include all of these in the paper, they are not optional.**
Single machine, single operating system. Synthetic rather than real evidence.
No comparison against Velociraptor VQL or Sigma on the same task. No user study
with practising examiners. The implementation is alpha-quality. Trees-walking
interpretation is the known ceiling, with a bytecode VM as the named next step.

The absence of a user study is the paper's most obvious weakness. Name it in the
limitations rather than hoping a reviewer misses it. The claim the paper can
actually support is *"the property is enforceable and its cost is measurable"*,
not *"examiners work better with it."*

---

## 5. Results to report

Use `paper-data.json` verbatim. The shape of the story:

- **Lex and parse cost is independent of data volume** — 2.2–3.1 ms for a
  332-token script at every scale (Table 5, Figure 5). This is the mechanism that
  makes a script reviewable *before* it touches evidence, and it is the result
  most worth foregrounding.
- **Execution is linear** in record count, ~0.14–0.20 ms per record (Table 1,
  Figure 1).
- **Memory is linear** at a strikingly constant ~1.25 KB per record (Figure 3).
- **Throughput is flat** at 5,079–7,363 records/sec across three orders of
  magnitude — no superlinear behaviour at these scales (Figure 2).
- **Overhead against hand-written Python is 19.5–26.3×, mean 22.7×** (Table 2,
  Figure 4). Report this plainly and early. It is the price of the auditability
  property, it is consistent across scales, and the mitigation is scoping —
  scripts are built to triage sets of 10³–10⁵ records where first-response calls
  are made, not to process full-disk images.
- **Results are stable**: identical findings, record counts and digests across
  runs; only `duration_ms` varies between two consecutive runs.

Do not present the overhead as a rounding error or bury it in an appendix.
A paper that volunteers its worst number and then explains the design trade is
more credible than one whose every measurement flatters it.

---

## 6. Scope and ethics — the paper must state this

The problem statement JOCKY was written against also asks for tooling that
conceals itself from endpoint security products. **The implementation deliberately
does not do this, and the paper must say so explicitly**, because the omission is
a design position rather than an unfinished feature.

State the reasoning directly: a forensic tool that evades the endpoint's own
telemetry is indistinguishable, in the evidence it leaves, from the intrusion it
is meant to investigate. The stated answer to "security tooling blocks our
collector" is instead signed reproducible builds with published hashes for vendor
allowlisting, and documented telemetry sources — ETW, WMI, the USN journal,
auditd/eBPF, netflow.

Supporting properties already enforced in the implementation, all of which belong
in the paper: evidence files are opened read-only and SHA-256 digested at ingest;
the console binds to loopback only; script paths are resolved with a traversal
guard; every run is attributable to a source hash.

**Do not** add, imply or gesture at polymorphism, bring-your-own-vulnerable-driver
techniques, process injection, API unhooking, direct syscalls, kernel patching,
or domain-fronted command and control — not even as future work. A paper that
describes an evasion capability as "out of scope but planned" has described it.

---

## 7. Related work to position against

Twelve references, as cited in the submission deck:

**Standards.** NIST SP 800-86 (integrating forensic techniques into incident
response — the collect/analyse/report workflow JOCKY's case model follows);
RFC 3227 (evidence collection and archiving — the ordering of volatility that
governs what JOCKY ingests first); ISO/IEC 27037:2012 (identification,
collection, acquisition and preservation of digital evidence); NIST SP 800-61r2
(incident handling); FIPS 180-4 (SHA-256 for evidence digests).

**Prior art in portable detection languages.** Sigma — the closest analogue for
*detection rules*, and the paper's main comparison point: Sigma made detection
logic portable and shareable, but a Sigma rule detects; it does not cite. JOCKY's
claim is that the same move applied to the *analysis* stage yields citable
findings.

**Existing forensic query and timeline tooling.** Velociraptor VQL (a query
language over endpoint state — closest existing art, but a query tool rather than
a language with provenance obligations); plaso, Chainsaw, Hayabusa (timeline and
EVTX tooling — JOCKY's timing stage is measured against this class of work);
E. Zimmerman's tools (de-facto reference implementations for EVTX, USN journal
and MFT parsing — the adapter roadmap); MITRE ATT&CK (the technique vocabulary
findings map to).

**Foundational.** Shannon (1948), *A Mathematical Theory of Communication* — the
basis of the entropy builtin that separates base64 from prose.

Position JOCKY as complementary to these rather than replacing them: it is the
layer where their outputs become a citable, reviewable, transferable case.

---

## 8. Suggested structure

1. **Introduction** — the stitching problem, the provenance gap, the thesis.
2. **Background and related work** — standards, Sigma, VQL, timeline tooling.
3. **Design** — pipeline, AST as plain dicts, the language surface, and the
   `finding ... from <binding>` mechanism as the central contribution.
4. **Implementation** — module table, the four reference investigations, zero
   dependencies as a deployment property.
5. **Evaluation** — method, then Tables 1–8 and Figures 1–5, overhead reported
   plainly.
6. **Discussion** — what the parse-cost-independence result implies for
   review-before-execution workflows; the overhead as the price of the property;
   where the design would break down.
7. **Limitations** — all of section 4's list, plus the absence of a user study.
8. **Scope and ethics** — section 6, stated as a design position.
9. **Conclusion and future work** — bytecode VM to close the overhead gap, then
   a Σ/ATT&CK mapping layer, then a user study with practising examiners.

---

## 9. Writing constraints

- **Tense and voice.** The system exists and was measured: past tense for what
  was built and run, present tense for what the language does.
- **No fabricated citations.** The twelve above are the citation set. If the
  draft needs a reference that is not in that list, mark it
  `[CITATION NEEDED]` rather than inventing one.
- **No invented numbers.** Every figure in the paper must appear in
  `paper-data.json`. If a number is wanted and absent, mark it
  `[DATA NEEDED]`.
- **Claim discipline.** Say "at the scales tested" and "on a single host", not
  "in general". The paper's strongest sentence is the honest one about overhead.
- **Target length** 6–8 pages, two-column. Conference or workshop style; the
  paper is describing a working system and a measurement, so an
  experience-and-evaluation track fits better than a theory track.
- **Availability.** The implementation is public at
  `https://github.com/Kartik-Kashyap/jocky-forensic-dsl` — the paper can point
  reviewers at it, and every number regenerates from `deck/bench.py`,
  `deck/bench_baseline.py` and the test suite. Say so; reproducibility that a
  reviewer can check is the paper's whole argument applied to itself.

---

## 10. Files

| File | Contents |
|---|---|
| `research/paper-data.json` | Every number: 8 tables, 5 figures, derived statistics, the three reproducibility demonstrations |
| `README.md` | Project overview and the "Scope and constraints" section |
| `jocky/` | Lexer, parser, runtime, builtins, CLI, console server |
| `scripts/*.jky` | The four reference investigations |
| `evidence/` | The synthetic corpus (Table 4) |
| `tests/test_jocky.py` | The 50-test suite |
| `deck/build_deck.py` | The submission deck generator, useful for wording of the contribution |
| `DEMO-GUIDE.md` | A shot list of the system's behaviour, useful for writing the walkthrough |
