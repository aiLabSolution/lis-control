#!/usr/bin/env python3
"""Unit tests for scripts/plane_issue.py — the markdown→description_html renderer
and the create payload builder. Network-free (stdlib unittest), so CI needs no deps.

Run: python3 -m unittest discover -s scripts -p 'test_*.py'
"""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plane_issue as pi  # noqa: E402


class TestInline(unittest.TestCase):
    def test_escapes_text_metachars(self):
        self.assertEqual(pi._inline("a < b & c > d"), "a &lt; b &amp; c &gt; d")

    def test_bold(self):
        self.assertEqual(pi._inline("a **bold** b"), "a <strong>bold</strong> b")

    def test_inline_code_is_escaped_and_not_styled(self):
        # markup inside a code span must be escaped and left untouched by bold/link passes
        self.assertEqual(pi._inline("use `a < b && **x**`"),
                         "use <code>a &lt; b &amp;&amp; **x**</code>")

    def test_link_allowed_scheme(self):
        self.assertEqual(pi._inline("see [docs](https://x.test/a)"),
                         'see <a href="https://x.test/a">docs</a>')

    def test_link_rejects_javascript_scheme(self):
        # unsafe scheme → render the literal markdown, never an <a>
        out = pi._inline("[x](javascript:alert(1))")
        self.assertNotIn("<a", out)
        self.assertIn("[x](javascript:alert(1))", out)

    def test_link_relative_and_anchor_ok(self):
        self.assertIn('<a href="/docs">', pi._inline("[d](/docs)"))
        self.assertIn('<a href="#sec">', pi._inline("[s](#sec)"))

    def test_link_rejects_protocol_relative(self):
        # //host is an off-site/open-redirect href the allowlist must not wave through
        out = pi._inline("[x](//evil.example/login)")
        self.assertNotIn("<a", out)
        self.assertIn("[x](//evil.example/login)", out)

    def test_bold_does_not_corrupt_link_url(self):
        # ** inside a URL must not be rewritten into the href by the bold pass
        out = pi._inline("[x](https://a.test/**b**/c)")
        self.assertIn('href="https://a.test/**b**/c"', out)
        self.assertNotIn("<strong>", out)

    def test_quote_is_escaped(self):
        self.assertEqual(pi._inline('say "hi"'), "say &quot;hi&quot;")


class TestBlocks(unittest.TestCase):
    def test_headings(self):
        self.assertEqual(pi.md_to_html("## What to build"), "<h2>What to build</h2>")
        self.assertEqual(pi.md_to_html("###### deep"), "<h6>deep</h6>")

    def test_paragraph_preserves_linebreaks(self):
        self.assertEqual(pi.md_to_html("line one\nline two"),
                         "<p>line one<br>line two</p>")

    def test_blank_line_splits_paragraphs(self):
        self.assertEqual(pi.md_to_html("a\n\nb"), "<p>a</p>\n<p>b</p>")

    def test_unordered_list(self):
        self.assertEqual(pi.md_to_html("- one\n- two"),
                         "<ul><li>one</li><li>two</li></ul>")

    def test_ordered_list(self):
        self.assertEqual(pi.md_to_html("1. one\n2. two"),
                         "<ol><li>one</li><li>two</li></ol>")

    def test_task_items(self):
        html = pi.md_to_html("- [ ] todo\n- [x] done")
        self.assertEqual(html, "<ul><li>☐ todo</li><li>☑ done</li></ul>")

    def test_nested_unordered_list(self):
        html = pi.md_to_html("- top\n  - sub a\n  - sub b\n- next")
        self.assertEqual(html, "<ul><li>top<ul><li>sub a</li><li>sub b</li></ul></li>"
                               "<li>next</li></ul>")

    def test_nested_ordered_under_unordered(self):
        html = pi.md_to_html("- top\n  1. first\n  2. second")
        self.assertEqual(html, "<ul><li>top<ol><li>first</li><li>second</li></ol></li></ul>")

    def test_nested_task_items(self):
        html = pi.md_to_html("- AC\n  - [ ] sub-check")
        self.assertIn("<li>AC<ul><li>☐ sub-check</li></ul></li>", html)

    def test_list_kind_switch_starts_new_list(self):
        html = pi.md_to_html("- a\n1. b")
        self.assertEqual(html, "<ul><li>a</li></ul>\n<ol><li>b</li></ol>")

    def test_fenced_code_block_escaped_no_inline(self):
        html = pi.md_to_html("```\n<tag> **not bold** `not code`\n```")
        self.assertIn("<pre><code>", html)
        self.assertIn("&lt;tag&gt; **not bold** `not code`", html)
        self.assertNotIn("<strong>", html)

    def test_fenced_code_language_class(self):
        self.assertIn('<code class="language-python">', pi.md_to_html("```python\nx=1\n```"))

    def test_fenced_code_language_attr_breakout_is_escaped(self):
        # a crafted ```lang info-string must not break out of the class="..." attribute
        html = pi.md_to_html('```js" onmouseover="alert(1)\nx\n```')
        self.assertNotIn('onmouseover="alert(1)"', html)
        self.assertIn("&quot;", html)
        # the only literal double-quotes left are the attribute delimiters themselves
        self.assertEqual(html.count('"'), 2)

    def test_horizontal_rule(self):
        self.assertEqual(pi.md_to_html("---"), "<hr>")

    def test_blockquote(self):
        self.assertEqual(pi.md_to_html("> a\n> b"), "<blockquote>a<br>b</blockquote>")

    def test_heading_breaks_paragraph(self):
        self.assertEqual(pi.md_to_html("text\n## H"), "<p>text</p>\n<h2>H</h2>")

    def test_no_raw_html_injection(self):
        # a literal <script> in body text must be escaped, never emitted as a tag
        self.assertNotIn("<script>", pi.md_to_html("<script>alert(1)</script>"))


class TestPrdTemplate(unittest.TestCase):
    BODY = (
        "## Parent\n\nLIS-22\n\n"
        "## What to build\n\n"
        "An end-to-end ERBA EC90 channel that ingests `ASTM E1381` frames.\n"
        "See [the spec](https://example.test/astm).\n\n"
        "## Acceptance criteria\n\n"
        "- [ ] Frames parse\n  - [ ] checksums verified\n- [ ] Results normalize\n"
        "- [x] Already done\n\n"
        "## Blocked by\n\n- None - can start immediately\n"
    )

    def test_renders_expected_structure(self):
        html = pi.md_to_html(self.BODY)
        for frag in ("<h2>Parent</h2>", "<h2>What to build</h2>",
                     "<code>ASTM E1381</code>", '<a href="https://example.test/astm">',
                     "<li>☐ Frames parse<ul><li>☐ checksums verified</li></ul></li>",
                     "<li>☑ Already done</li>", "<h2>Blocked by</h2>"):
            self.assertIn(frag, html)

    def test_round_trips_without_raising(self):
        self.assertTrue(pi.md_to_html(self.BODY))


class TestPayload(unittest.TestCase):
    def test_minimal(self):
        p = pi.build_payload("Title", "body text")
        self.assertEqual(p["name"], "Title")
        self.assertIn("<p>body text</p>", p["description_html"])

    def test_empty_body_omits_description(self):
        self.assertNotIn("description_html", pi.build_payload("Title", "   "))

    def test_priority_is_string_enum(self):
        # The Plane API takes priority as a string enum — the old int mapping 400s
        # ('"2" is not a valid choice', confirmed live 2026-07-02).
        self.assertEqual(pi.build_payload("T", "b", priority="high")["priority"], "high")
        self.assertEqual(pi.build_payload("T", "b", priority="NONE")["priority"], "none")

    def test_priority_rejects_unknown(self):
        with self.assertRaises(SystemExit):
            pi.build_payload("T", "b", priority="critical")

    def test_parent_and_label(self):
        p = pi.build_payload("T", "b", parent="uuid-1", label="uuid-2")
        self.assertEqual(p["parent"], "uuid-1")
        self.assertEqual(p["labels"], ["uuid-2"])

    def test_state_passthrough(self):
        # build_payload is pure: it takes an already-resolved state UUID verbatim
        self.assertEqual(pi.build_payload("T", "b", state="uuid-s")["state"], "uuid-s")


class TestReadBody(unittest.TestCase):
    def test_missing_file_exits_cleanly(self):
        # a bad --body-file path should sys.exit, not dump a raw traceback
        with self.assertRaises(SystemExit):
            pi._read_body("/no/such/file-plane-issue-xyz.md")


if __name__ == "__main__":
    unittest.main()
