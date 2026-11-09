from notefind.linkcheck import find_broken_links
from notefind.scan import load_notes, walk_files


def broken(root):
    files = walk_files(root)
    result, checked = find_broken_links(root, load_notes(root, files), files)
    return [(b.path, b.line, b.target) for b in result], checked


# --- scanning -------------------------------------------------------------

def test_hidden_dirs_and_node_modules_are_skipped(make_vault):
    root = make_vault({
        "a.md": "x",
        "sub/b.markdown": "x",
        ".obsidian/c.md": "x",
        ".git/d.md": "x",
        "node_modules/pkg/e.md": "x",
        ".hidden.md": "x",
        "image.png": b"\x89PNG",
    })
    assert [n.rel for n in load_notes(root)] == ["a.md", "sub/b.markdown"]
    assert walk_files(root) == ["a.md", "image.png", "sub/b.markdown"]


def test_bom_and_crlf_are_normalised(make_vault):
    root = make_vault({"a.md": b"\xef\xbb\xbf---\r\ntags: [x]\r\n---\r\nline\r\n"})
    (n,) = load_notes(root)
    assert n.text == "---\ntags: [x]\n---\nline\n"


def test_invalid_utf8_is_replaced_not_fatal(make_vault):
    root = make_vault({"a.md": b"caf\xe9 ok"})
    (n,) = load_notes(root)
    assert n.text == "caf� ok"


# --- link resolution ------------------------------------------------------

def test_wiki_links_resolve_by_stem_anywhere_case_insensitive(make_vault):
    root = make_vault({
        "index.md": "[[deep note]] [[Deep Note|alias]] [[DEEP NOTE#Heading]] [[Missing]]\n",
        "a/b/Deep Note.md": "x",
    })
    assert broken(root) == ([("index.md", 1, "Missing")], 4)


def test_wiki_link_with_folder_path_and_attachment(make_vault):
    root = make_vault({
        "index.md": "[[a/b/Note]]\n![[diagram.png]]\n[[x/Note]]\n[[Note.md]]\n",
        "a/b/Note.md": "x",
        "assets/diagram.png": b"png",
    })
    assert broken(root)[0] == [("index.md", 3, "x/Note")]


def test_self_heading_links_are_not_checked(make_vault):
    root = make_vault({"a.md": "[[#Intro]] [jump](#intro)\n"})
    assert broken(root) == ([], 0)


def test_markdown_links_relative_to_linking_file(make_vault):
    root = make_vault({
        "sub/a.md": "[ok](other.md) [up](../top.md#x) [bad](top.md) [enc](my%20note.md)\n",
        "sub/other.md": "x",
        "sub/my note.md": "x",
        "top.md": "x",
    })
    assert broken(root) == ([("sub/a.md", 1, "top.md")], 4)


def test_external_links_are_ignored(make_vault):
    root = make_vault({
        "a.md": "[w](https://example.com/x.md) [m](mailto:a@example.com) [h](http://x)\n",
    })
    assert broken(root) == ([], 0)


def test_links_in_code_are_not_reported(make_vault):
    root = make_vault({"a.md": "```\n[[Nope]]\n```\n`[x](nope.md)`\n"})
    assert broken(root) == ([], 0)


def test_links_to_notes_in_hidden_dirs_do_not_resolve(make_vault):
    root = make_vault({"a.md": "[[Secret]]\n", ".trash/Secret.md": "x"})
    assert broken(root)[0] == [("a.md", 1, "Secret")]


def test_crlf_note_reports_correct_line(make_vault):
    root = make_vault({"a.md": b"one\r\ntwo\r\n[[Gone]]\r\n"})
    assert broken(root)[0] == [("a.md", 3, "Gone")]


def test_reference_style_links_are_checked_where_used(make_vault):
    root = make_vault({
        "sub/a.md": (
            "Read [the other note][other] and [top][].\n"
            "\n"
            "Also [gone][missing-file] and [ext][web].\n"
            "\n"
            "[other]: other.md\n"
            "[top]: ../top.md#intro\n"
            "[missing-file]: nope.md\n"
            "[web]: https://example.com/\n"
        ),
        "sub/other.md": "x",
        "top.md": "x",
    })
    assert broken(root) == ([("sub/a.md", 3, "nope.md")], 3)
