"""Test suite for the JOCKY language.

Run with:  python -m unittest discover -s tests -v
"""

import json
import os
import tempfile
import unittest

from jocky import builtins as jb
from jocky.lexer import tokenize, Lexer, JockySyntaxError
from jocky.parser import parse
from jocky.runtime import run_source, compile_source, count_nodes

FIXTURE_EVENTS = [
    {"timestamp": "2026-09-21T09:16:41Z", "host": "WS-1", "event_id": 1,
     "image": "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
     "parent_image": "C:\\Program Files\\Microsoft Office\\root\\Office16\\WINWORD.EXE",
     "command_line": "powershell.exe -nop -w hidden -enc SGVsbG8gV29ybGQhIFRoaXMgaXMgYSB0ZXN0IHBheWxvYWQgc3RyaW5n",
     "signed": True, "integrity": "medium", "dst_ip": "185.234.72.19",
     "hash": "47a648b1bbc9399b36e7189ea5ee0f855262c39c5dff523bc60eec2bc89fd963"},
    {"timestamp": "2026-09-21T09:22:17Z", "host": "WS-1", "event_id": 3,
     "image": "C:\\Program Files\\Microsoft Teams\\current\\Teams.exe",
     "parent_image": "C:\\Windows\\explorer.exe", "signed": True,
     "integrity": "medium", "dst_ip": "52.113.194.132", "dst_port": 443},
    {"timestamp": "2026-09-21T10:01:47Z", "host": "WS-1", "event_id": 1,
     "image": "C:\\Windows\\System32\\wevtutil.exe",
     "parent_image": "C:\\Users\\a\\AppData\\Local\\Temp\\svchost_update.exe",
     "command_line": "wevtutil.exe cl Security", "signed": True,
     "integrity": "medium"},
]


def _write_fixture(tmpdir):
    path = os.path.join(tmpdir, "events.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(FIXTURE_EVENTS, fh)
    intel = os.path.join(tmpdir, "intel.txt")
    with open(intel, "w", encoding="utf-8") as fh:
        fh.write("# comment line\n185.234.72.19\n")
    return path, intel


# ---------------------------------------------------------------------------
# lexer
# ---------------------------------------------------------------------------

class TestLexer(unittest.TestCase):

    def test_keywords_and_idents(self):
        toks = tokenize("let x = where")
        self.assertEqual([t.kind for t in toks],
                         ["kw", "ident", "op", "kw", "eof"])
        self.assertEqual(toks[0].value, "let")
        self.assertEqual(toks[1].value, "x")

    def test_pipe_operator_is_single_token(self):
        toks = tokenize("a |> b")
        self.assertEqual(toks[1].kind, "op")
        self.assertEqual(toks[1].value, "|>")

    def test_comments_are_skipped(self):
        toks = tokenize("# a comment\nlet x = 1  # trailing")
        self.assertEqual(toks[0].value, "let")

    def test_string_escapes_are_minimal_by_design(self):
        # Only \" \' and \\ are escapes. Everything else is literal, because
        # JOCKY strings carry Windows paths and regex patterns.
        toks = tokenize(r'"a\nb\tc\"d"')
        self.assertEqual(toks[0].value, 'a\\nb\\tc"d')
        toks = tokenize(r'"back\\slash"')
        self.assertEqual(toks[0].value, "back\\slash")

    def test_windows_paths_survive_untouched(self):
        # \T, \U and \a are not escapes, and neither is a lowercase \t here.
        for raw in (r"C:\Users\a\Temp", r"C:\temp", r"C:\reports\nov",
                    r"C:\Users\npatel\Desktop"):
            self.assertEqual(tokenize(f'"{raw}"')[0].value, raw, raw)

    def test_regex_patterns_survive_untouched(self):
        for raw in (r"(?i)appdata\.local", r"\d{1,3}(\.\d{1,3}){3}",
                    r"\.xlsx$", r"\bwevtutil\b"):
            self.assertEqual(tokenize(f'"{raw}"')[0].value, raw, raw)

    def test_unknown_escapes_are_preserved(self):
        toks = tokenize(r'"(?i)appdata\.local"')
        self.assertEqual(toks[0].value, r"(?i)appdata\.local")

    def test_numbers_and_hex(self):
        toks = tokenize("42 3.5 0x1410 1_000")
        self.assertEqual(toks[0].value, 42)
        self.assertEqual(toks[1].value, 3.5)
        self.assertEqual(toks[2].value, 0x1410)
        self.assertEqual(toks[3].value, 1000)

    def test_positions_are_tracked(self):
        toks = tokenize("let x\n  above")
        above = [t for t in toks if t.value == "above"][0]
        self.assertEqual((above.line, above.col), (2, 3))

    def test_unterminated_string_reports_position(self):
        with self.assertRaises(JockySyntaxError) as ctx:
            tokenize('let x = "unterminated')
        self.assertIn("unterminated string", ctx.exception.message)
        self.assertEqual(ctx.exception.line, 1)

    def test_unexpected_character(self):
        with self.assertRaises(JockySyntaxError):
            tokenize("let x = @bad")


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

class TestParser(unittest.TestCase):

    def test_minimal_program(self):
        ast = parse('case "C-1"')
        self.assertEqual(ast["node"], "Program")
        self.assertEqual(ast["body"][0], {"node": "Case", "name": "C-1", "line": 1})

    def test_pipeline_sugar(self):
        ast = parse("let r = src |> where (a == 1) |> limit (5)")
        let = ast["body"][0]
        self.assertEqual(let["node"], "Let")
        pipe = let["value"]
        self.assertEqual(pipe["node"], "Pipe")
        self.assertEqual(pipe["source"]["name"], "src")
        self.assertEqual([s["node"] for s in pipe["stages"]], ["Where", "Limit"])
        self.assertEqual(pipe["stages"][1]["n"], 5)

    def test_keyword_field_names_are_allowed(self):
        # `count` is produced by `group by` and must stay addressable.
        ast = parse("let r = src |> group by (a) |> sort by (count desc)")
        sort = ast["body"][0]["value"]["stages"][1]
        self.assertEqual(sort["field"], "count")
        self.assertEqual(sort["direction"], "desc")

    def test_all_comparison_operators(self):
        src = ('let r = s |> where (a == 1 or b != 2 or c < 3 or d <= 4 '
               'or e > 5 or f >= 6 or g contains "x" or h in ["y"])')
        stages = ast_stages(src)
        conds = collect_ops(stages[0]["cond"])
        self.assertEqual(conds, {"or", "==", "!=", "<", "<=", ">", ">=",
                                 "contains", "in"})

    def test_boolean_precedence_is_left_associative(self):
        ast = parse('let r = s |> where (a == 1 or b == 2 and c == 3)')
        cond = ast["body"][0]["value"]["stages"][0]["cond"]
        self.assertEqual(cond["op"], "or")     # `or` binds loosest
        self.assertEqual(cond["right"]["op"], "and")

    def test_not_and_parentheses(self):
        ast = parse('let r = s |> where (not (a == 1))')
        cond = ast["body"][0]["value"]["stages"][0]["cond"]
        self.assertEqual(cond["node"], "Not")

    def test_match_statement_default_and_named(self):
        ast = parse('match ev.dst_ip against "i.txt"')
        self.assertEqual(ast["body"][0]["name"], "ev_dst_ip_matches")
        ast = parse('match ev.dst_ip against "i.txt" as hits')
        self.assertEqual(ast["body"][0]["name"], "hits")

    def test_finding_severity_is_validated(self):
        with self.assertRaises(JockySyntaxError) as ctx:
            parse('finding "x" severity urgent from r')
        self.assertIn("unknown severity", ctx.exception.message)

    def test_in_requires_list(self):
        with self.assertRaises(JockySyntaxError) as ctx:
            parse('let r = s |> where (a in "notalist")')
        self.assertIn("must be a [ ... ] list", ctx.exception.message)

    def test_error_carries_source_line(self):
        with self.assertRaises(JockySyntaxError) as ctx:
            parse('case "C"\nlet b = a |> where (t == )\n')
        self.assertEqual(ctx.exception.line, 2)
        self.assertEqual(ctx.exception.source_line, 'let b = a |> where (t == )')

    def test_unknown_stage_is_rejected(self):
        with self.assertRaises(JockySyntaxError):
            parse("let r = s |> filter (a == 1)")

    def test_node_counting(self):
        ast = parse('case "C"')
        self.assertGreater(count_nodes(ast), 1)


def ast_stages(src):
    return parse(src)["body"][0]["value"]["stages"]


def collect_ops(node, acc=None):
    acc = set() if acc is None else acc
    if isinstance(node, dict):
        if node.get("node") == "Logic":
            acc.add(node["op"])
        if node.get("node") == "Compare":
            acc.add(node["op"])
        for v in node.values():
            collect_ops(v, acc)
    elif isinstance(node, list):
        for v in node:
            collect_ops(v, acc)
    return acc


# ---------------------------------------------------------------------------
# builtins
# ---------------------------------------------------------------------------

class TestBuiltins(unittest.TestCase):

    def test_sha256_matches_hashlib(self):
        import hashlib
        self.assertEqual(jb.fn_sha256("abc"),
                         hashlib.sha256(b"abc").hexdigest())

    def test_entropy_orders_content_types(self):
        flat = jb.fn_entropy("aaaaaaaaaaaaaaaa")
        text = jb.fn_entropy("the quick brown fox jumps over")
        b64 = jb.fn_entropy("SGVsbG8gV29ybGQhIFRoaXMgaXMgYSB0ZXN0IHBheWxvYWQ")
        self.assertLess(flat, text)
        self.assertLess(text, b64)
        self.assertEqual(jb.fn_entropy(""), 0.0)

    def test_ip_classification(self):
        for private in ("10.0.0.1", "192.168.1.1", "172.16.0.1", "127.0.0.1"):
            self.assertTrue(jb.fn_is_private_ip(private), private)
            self.assertFalse(jb.fn_is_public_ip(private), private)
        for public in ("185.234.72.19", "8.8.8.8"):
            self.assertTrue(jb.fn_is_public_ip(public), public)

    def test_ip_classification_handles_garbage(self):
        self.assertFalse(jb.fn_is_public_ip("not-an-ip"))
        self.assertFalse(jb.fn_is_private_ip(None))

    def test_epoch_parsing(self):
        self.assertEqual(jb.fn_epoch("1970-01-01T00:00:00Z"), 0)
        self.assertEqual(jb.fn_epoch("nonsense"), 0)

    def test_coercion_helpers_are_safe(self):
        self.assertEqual(jb.fn_int("abc"), 0)
        self.assertEqual(jb.fn_len(None), 0)
        self.assertEqual(jb.fn_round("2.567", 2), 2.57)


# ---------------------------------------------------------------------------
# runtime, end to end
# ---------------------------------------------------------------------------

class TestRuntime(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.events, self.intel = _write_fixture(self.tmp.name)
        self.events_rel = os.path.relpath(self.events, os.getcwd())
        self.intel_rel = os.path.relpath(self.intel, os.getcwd())

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, body):
        src = f'case "T-1"\nsource ev = ingest "{self.events_rel}"\n{body}\n'
        return run_source(src, filename="<test>")

    def test_where_and_select(self):
        art = self.run_script(
            'let r = ev |> where (signed == true and event_id == 3)\n'
            'emit r')
        self.assertEqual(art["tables"][0]["total"], 1)
        self.assertEqual(art["tables"][0]["rows"][0]["image"][-9:], "Teams.exe")

    def test_regex_operator(self):
        art = self.run_script(
            'let r = ev |> where (image ~ "(?i)teams\\\\.exe$")\n'
            'emit r')
        self.assertEqual(art["tables"][0]["total"], 1)

    def test_entropy_filter_finds_encoded_command(self):
        art = self.run_script(
            'let r = ev |> where (command_line contains "-enc") '
            '|> where (entropy(command_line) > 4.0)\n'
            'emit r')
        self.assertEqual(art["tables"][0]["total"], 1)

    def test_group_by_counts_and_orders(self):
        art = self.run_script('let r = ev |> group by (host)\nemit r')
        row = art["tables"][0]["rows"][0]
        self.assertEqual(row["count"], 3)
        self.assertEqual(row["host"], "WS-1")

    def test_distinct(self):
        art = self.run_script('let r = ev |> distinct (event_id)\nemit r')
        counts = sorted(r["count"] for r in art["tables"][0]["rows"])
        self.assertEqual(counts, [1, 2])

    def test_sort_descending_and_limit(self):
        art = self.run_script(
            'let r = ev |> sort by (timestamp desc) |> limit (1)\nemit r')
        self.assertEqual(art["tables"][0]["total"], 1)
        self.assertEqual(art["tables"][0]["rows"][0]["timestamp"],
                         "2026-09-21T10:01:47Z")

    def test_count_stage(self):
        art = self.run_script('let r = ev |> count\nemit r')
        self.assertEqual(art["tables"][0]["rows"][0]["count"], 3)

    def test_match_against_intel(self):
        art = self.run_script(
            f'match ev.dst_ip against "{self.intel_rel}" as hits\nemit hits')
        self.assertEqual(art["tables"][0]["total"], 1)
        self.assertEqual(art["tables"][0]["rows"][0]["dst_ip"], "185.234.72.19")

    def test_match_ignores_comment_lines(self):
        art = self.run_script(
            f'match ev.dst_ip against "{self.intel_rel}" as hits\nemit hits')
        self.assertTrue(all(r["dst_ip"] != "# comment line"
                            for r in art["tables"][0]["rows"]))

    def test_timeline_is_chronological(self):
        art = self.run_script('timeline ev on timestamp as "t"')
        stamps = [e["timestamp"] for e in art["timeline"]["events"]]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(art["timeline"]["count"], 3)

    def test_findings_are_sorted_by_severity_and_cite_sources(self):
        art = self.run_script(
            'let low = ev |> where (signed == true)\n'
            'let bad = ev |> where (signed == false)\n'
            'report "R"\n'
            'finding "minor" severity low from low\n'
            'finding "serious" severity critical from bad\n'
            'emit bad')
        self.assertEqual([f["severity"] for f in art["findings"]],
                         ["critical", "low"])
        self.assertEqual(art["findings"][1]["rows"], 3)

    def test_evidence_metadata_is_recorded(self):
        art = self.run_script('emit ev')
        self.assertEqual(art["sources"]["ev"]["records"], 3)
        self.assertIn("timestamp", art["sources"]["ev"]["columns"])

    def test_missing_field_compares_false_not_crash(self):
        art = self.run_script(
            'let r = ev |> where (no_such_field > 5)\nemit r')
        self.assertEqual(art["tables"][0]["total"], 0)

    def test_missing_evidence_is_a_runtime_error(self):
        art = run_source('case "X"\nsource a = ingest "nope/none.json"\nemit a',
                         filename="<test>")
        self.assertTrue(art["errors"])
        self.assertIn("not found", art["errors"][0])

    def test_unknown_source_is_reported(self):
        art = self.run_script('let r = ghost |> limit (1)\nemit r')
        self.assertTrue(any("unknown data source" in e for e in art["errors"]))

    def test_unknown_function_is_reported(self):
        art = self.run_script('let r = ev |> where (nope(x) > 1)\nemit r')
        self.assertTrue(any("unknown function" in e for e in art["errors"]))

    def test_wrong_arity_is_reported(self):
        art = self.run_script('let r = ev |> where (entropy(a, b) > 1)\nemit r')
        self.assertTrue(any("takes 1 argument" in e for e in art["errors"]))

    def test_case_override_beats_the_script(self):
        # --case on the command line is an operator override; it wins over
        # whatever the script declares, and the log records both.
        art = run_source(f'case "A"\nsource ev = ingest "{self.events_rel}"\nemit ev',
                         filename="<test>", case="OVERRIDE")
        self.assertEqual(art["case"], "OVERRIDE")
        self.assertTrue(any("overridden to OVERRIDE" in line
                            for line in art["log"]))

    def test_case_falls_back_to_the_script(self):
        art = run_source(f'case "A"\nsource ev = ingest "{self.events_rel}"\nemit ev',
                         filename="<test>")
        self.assertEqual(art["case"], "A")

    def test_stats_are_populated(self):
        art = self.run_script('emit ev')
        self.assertEqual(art["stats"]["records_read"], 3)
        self.assertGreater(art["stats"]["nodes"], 3)
        self.assertGreaterEqual(art["stats"]["duration_ms"], 0.0)

    def test_compile_reports_token_and_node_counts(self):
        ast, toks = compile_source('case "C"', "t.jky")
        self.assertGreater(len(toks), 1)
        self.assertEqual(ast["_tokens"], len(toks) - 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
