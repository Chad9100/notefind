from notefind.parse import (
    Link,
    extract_links,
    extract_tags,
    front_matter_tags,
    split_front_matter,
    strip_code,
)


# --- code stripping -------------------------------------------------------

def test_strip_code_blanks_fenced_block_and_keeps_line_count():
    lines = ["before", "```python", "x = '#notatag'", "```", "after"]
    out = strip_code(lines)
    assert out == ["before", "", "", "", "after"]


def test_strip_code_blanks_inline_code_keeping_columns():
    out = strip_code(["use `#x` here"])
    assert out[0] == "use      here"
    assert len(out[0]) == len("use `#x` here")


def test_strip_code_tilde_fence_and_longer_backtick_fence():
    lines = ["~~~", "#a", "~~~", "````", "```", "#b", "````", "#c"]
    out = strip_code(lines)
    assert out == ["", "", "", "", "", "", "", "#c"]


def test_strip_code_unclosed_fence_runs_to_end():
    assert strip_code(["ok", "```", "#a", "#b"]) == ["ok", "", "", ""]


# --- front matter ---------------------------------------------------------

def test_split_front_matter_returns_body_start():
    fm, start = split_front_matter(["---", "title: x", "---", "body"])
    assert fm == ["title: x"]
    assert start == 3


def test_no_front_matter_when_first_line_is_not_dashes():
    assert split_front_matter(["title: x", "---"]) == ([], 0)


def test_front_matter_tags_bracket_list():
    assert front_matter_tags(["tags: [Alpha, 'beta', \"#gamma\"]"]) == ["alpha", "beta", "gamma"]


def test_front_matter_tags_comma_string():
    assert front_matter_tags(["tags: alpha, beta"]) == ["alpha", "beta"]


def test_front_matter_tags_block_list():
    fm = ["title: t", "tags:", "  - one", "  - two", "", "  - three", "status: done"]
    assert front_matter_tags(fm) == ["one", "two", "three"]


def test_front_matter_singular_tag_key():
    assert front_matter_tags(["tag: solo"]) == ["solo"]


# --- inline tags ----------------------------------------------------------

def test_inline_tags_and_front_matter_are_merged():
    text = "---\ntags: [meta]\n---\nSome #idea and #Project/Alpha.\n"
    assert extract_tags(text) == {"meta", "idea", "project/alpha"}


def test_headings_are_not_tags():
    text = "# Heading\n## Sub heading\n### Third #real\n"
    assert extract_tags(text) == {"real"}


def test_tags_in_code_are_ignored():
    text = "```\n#fenced\n```\nInline `#code` and #kept\n"
    assert extract_tags(text) == {"kept"}


def test_url_fragments_and_anchors_are_not_tags():
    text = (
        "See https://example.com/#section and example.com/#x and page#frag\n"
        "[jump](#local-anchor) [[Note#Heading]] [[#Self]] &#123;\n"
    )
    assert extract_tags(text) == set()


def test_pure_numbers_are_not_tags():
    text = "Fixed in #1 and #2024-05 but #v2 and #2nd-try count\n"
    assert extract_tags(text) == {"v2", "2nd-try"}


def test_tag_trailing_punctuation_dropped():
    assert extract_tags("Ends with #todo. And (#done), #wip!\n") == {"todo", "done", "wip"}


def test_front_matter_hash_lines_are_not_inline_tags():
    # Inside front matter, "#..." is a YAML comment, not an inline tag.
    text = "---\n# comment #nope\ntags: [yes]\n---\nbody\n"
    assert extract_tags(text) == {"yes"}


# --- links ----------------------------------------------------------------

def test_extract_wiki_links_with_alias_and_heading():
    text = "See [[Alpha]], [[Beta|the beta]] and [[Gamma#Intro]].\n"
    assert extract_links(text) == [
        Link(1, "Alpha", "wiki"),
        Link(1, "Beta", "wiki"),
        Link(1, "Gamma#Intro", "wiki"),
    ]


def test_extract_markdown_links_with_title_and_angle_brackets():
    text = 'a [x](sub/o.md#top "Title") b\n![img](<my pic.png>)\n'
    assert extract_links(text) == [
        Link(1, "sub/o.md#top", "markdown"),
        Link(2, "my pic.png", "markdown"),
    ]


def test_links_in_code_are_ignored():
    text = "```\n[[Fenced]]\n```\n`[[Inline]]` and `[x](y.md)`\n[[Real]]\n"
    assert extract_links(text) == [Link(5, "Real", "wiki")]


def test_escaped_alias_in_table():
    assert extract_links("| [[Note\\|alias]] |\n") == [Link(1, "Note", "wiki")]


# --- reference-style links ------------------------------------------------

def test_reference_links_full_collapsed_and_shortcut():
    text = (
        "See [the plan][plan], the [Compost][] note and [Seeds].\n"
        "\n"
        "[plan]: Garden%20Plan.md\n"
        "[compost]: <sub/Compost.md> \"Title\"\n"
        "  [SEEDS]:   seeds.md 'Seed order'\n"
    )
    assert extract_links(text) == [
        Link(1, "Garden%20Plan.md", "markdown"),
        Link(1, "sub/Compost.md", "markdown"),
        Link(1, "seeds.md", "markdown"),
    ]


def test_reference_labels_ignore_case_and_whitespace_first_definition_wins():
    text = "[a][My   Ref] and [b][my ref]\n[my ref]: first.md\n[MY REF]: second.md\n"
    assert extract_links(text) == [
        Link(1, "first.md", "markdown"),
        Link(1, "first.md", "markdown"),
    ]


def test_undefined_references_unused_definitions_and_footnotes_are_not_links():
    text = (
        "- [x] done task\n"
        "Text with [brackets] and [a][missing] and a note[^1].\n"
        "[unused]: nowhere.md\n"
        "[^1]: a footnote, not a link\n"
    )
    assert extract_links(text) == []


def test_reference_links_and_definitions_in_code_are_ignored():
    text = (
        "`[x][ref]` and\n"
        "```\n"
        "[y][ref]\n"
        "[code]: code.md\n"
        "```\n"
        "[z][code] [w][ref]\n"
        "[ref]: real.md\n"
    )
    assert extract_links(text) == [Link(6, "real.md", "markdown")]


def test_inline_link_is_not_mistaken_for_a_reference():
    text = "[ref](inline.md) [[ref]]\n[ref]: defined.md\n"
    assert extract_links(text) == [
        Link(1, "ref", "wiki"),
        Link(1, "inline.md", "markdown"),
    ]


def test_reference_definition_anchor_is_not_a_tag():
    assert extract_tags("[jump]: #section\nreal #tag\n") == {"tag"}
