import pytest

from notefind.scan import Note
from notefind.search import (
    HIGHLIGHT_OFF,
    HIGHLIGHT_ON,
    FuzzyTerm,
    QueryError,
    compile_pattern,
    edit_distance,
    highlight,
    make_snippet,
    parse_query,
    search,
    typo_budget,
    words_pattern,
)


def note(rel, text):
    return Note(rel=rel, path=None, text=text)


# --- query parsing --------------------------------------------------------

def test_plain_terms_are_anded():
    q = parse_query(["pasta", "Tomato"])
    assert q.terms == ["pasta", "Tomato"]
    assert q.phrases == [] and q.excludes == []


def test_quoted_phrase_inside_one_string():
    q = parse_query('soup "olive oil" salt')
    assert q.terms == ["soup", "salt"]
    assert q.phrases == ["olive oil"]


def test_shell_split_argument_with_space_is_phrase():
    q = parse_query(["olive oil", "salt"])
    assert q.phrases == ["olive oil"]
    assert q.terms == ["salt"]


def test_exclusions_terms_and_phrases():
    q = parse_query(['pasta -tomato -"cream sauce"'])
    assert q.terms == ["pasta"]
    assert q.excludes == ["tomato", "cream sauce"]


def test_tag_filters():
    q = parse_query(["tag:Recipe", "-tag:#draft", "bread"])
    assert q.tags == ["recipe"]
    assert q.exclude_tags == ["draft"]
    assert q.terms == ["bread"]


def test_hyphenated_word_is_a_term_and_empty_query_detected():
    assert parse_query(["follow-up"]).terms == ["follow-up"]
    assert parse_query(["-only", "-excludes"]).is_empty()


def test_quoted_tag_text_is_a_phrase_not_a_filter():
    q = parse_query('"tag:x"')
    assert q.tags == [] and q.phrases == ["tag:x"]


# --- matching and ranking -------------------------------------------------

def test_search_is_case_insensitive_and_requires_all_terms():
    notes = [note("a.md", "Pasta with TOMATO"), note("b.md", "pasta only")]
    hits = search(notes, parse_query(["pasta", "tomato"]))
    assert [h.path for h in hits] == ["a.md"]


def test_ranked_by_match_count_then_path():
    notes = [
        note("c.md", "kiwi"),
        note("a.md", "kiwi"),
        note("b.md", "kiwi kiwi kiwi"),
    ]
    hits = search(notes, parse_query(["kiwi"]))
    assert [(h.path, h.matches) for h in hits] == [("b.md", 3), ("a.md", 1), ("c.md", 1)]


def test_phrase_matches_across_whitespace_but_not_reordered():
    notes = [note("a.md", "olive\n  oil"), note("b.md", "oil and olive")]
    hits = search(notes, parse_query(['"olive oil"']))
    assert [h.path for h in hits] == ["a.md"]


def test_exclusion_drops_notes():
    notes = [note("a.md", "bread rye"), note("b.md", "bread wheat")]
    hits = search(notes, parse_query(["bread", "-rye"]))
    assert [h.path for h in hits] == ["b.md"]


def test_tag_filter_restricts_and_matches_nested_tags():
    notes = [
        note("a.md", "---\ntags: [recipe]\n---\nbread\n"),
        note("b.md", "bread #recipe/baking\n"),
        note("c.md", "bread without tag\n"),
    ]
    hits = search(notes, parse_query(["tag:recipe", "bread"]))
    assert sorted(h.path for h in hits) == ["a.md", "b.md"]


def test_tag_only_query_lists_tagged_notes_at_first_body_line():
    notes = [note("a.md", "---\ntags: [x]\n---\n\nFirst line\n"), note("b.md", "nothing")]
    hits = search(notes, parse_query(["tag:x"]))
    assert len(hits) == 1
    assert hits[0].line == 5 and hits[0].snippet == "First line"


def test_hit_reports_first_matching_line():
    hits = search([note("a.md", "one\ntwo\nthree apple\napple")], parse_query(["apple"]))
    assert hits[0].line == 3
    assert hits[0].snippet == "three apple"


# --- snippets and highlighting -------------------------------------------

def test_long_line_snippet_is_cut_around_match():
    line = "x" * 200 + " needle " + "y" * 200
    snip = make_snippet(line, [compile_pattern("needle")], width=60)
    assert "needle" in snip
    assert snip.startswith("...") and snip.endswith("...")
    assert len(snip) == 66


def test_highlight_wraps_every_match_preserving_case():
    out = highlight("Pasta and pasta", [compile_pattern("pasta")], color=True)
    assert out == f"{HIGHLIGHT_ON}Pasta{HIGHLIGHT_OFF} and {HIGHLIGHT_ON}pasta{HIGHLIGHT_OFF}"


def test_highlight_merges_overlapping_matches():
    out = highlight("olive oil", [compile_pattern("olive oil"), compile_pattern("oil")], color=True)
    assert out == f"{HIGHLIGHT_ON}olive oil{HIGHLIGHT_OFF}"


def test_highlight_off_returns_plain_text():
    assert highlight("pasta", [compile_pattern("pasta")], color=False) == "pasta"


# --- fuzzy matching -------------------------------------------------------

@pytest.mark.parametrize("a, b, expected", [
    ("tomato", "tomato", 0),
    ("tomatos", "tomatoes", 1),   # insertion
    ("compst", "compost", 1),     # deletion
    ("basel", "basil", 1),        # substitution
    ("tomaot", "tomato", 1),      # swap of neighbours counts once
    ("wtaer", "water", 1),
    ("kitten", "sitting", 3),
])
def test_edit_distance(a, b, expected):
    assert edit_distance(a, b, limit=5) == expected
    assert edit_distance(b, a, limit=5) == expected


def test_edit_distance_stops_early_past_the_limit():
    assert edit_distance("kitten", "sitting", limit=1) == 2
    assert edit_distance("a", "abcdef", limit=2) == 3


@pytest.mark.parametrize("term, budget", [
    ("fig", 0), ("kale", 1), ("tomatos", 1), ("compostin", 2),
    ("c++", 0), ("2026-05-02", 0), ("follow-up", 0),
])
def test_typo_budget_grows_with_length_and_skips_non_words(term, budget):
    assert typo_budget(term) == budget


def test_fuzzy_off_by_default():
    notes = [note("a.md", "Tomatoes need sun")]
    assert search(notes, parse_query(["tomatos"])) == []


def test_fuzzy_matches_typos_and_reports_the_words():
    notes = [
        note("a.md", "Tomatoes need sun.\nMore tomatoes here."),
        note("b.md", "A cherry tomato."),
        note("c.md", "Potatoes only."),  # two substitutions away
    ]
    hits = search(notes, parse_query(["tomatos"]), fuzzy=True)
    assert [(h.path, h.matches, h.fuzzy_words) for h in hits] == [
        ("a.md", 2, ["tomatoes"]),
        ("b.md", 1, ["tomato"]),
    ]
    assert hits[0].line == 1


def test_fuzzy_still_matches_substrings_exactly():
    hits = search([note("a.md", "Composting the pile")], parse_query(["compost"]), fuzzy=True)
    assert len(hits) == 1 and hits[0].fuzzy_words == []


def test_fuzzy_short_terms_stay_exact():
    notes = [note("a.md", "a fog in the morning")]
    assert search(notes, parse_query(["fig"]), fuzzy=True) == []


def test_fuzzy_needs_whole_words_and_all_terms():
    notes = [
        note("a.md", "the compost pile"),
        note("b.md", "the compost heap"),
    ]
    hits = search(notes, parse_query(["compst", "piles"]), fuzzy=True)
    assert [(h.path, h.fuzzy_words) for h in hits] == [("a.md", ["compost", "pile"])]


def test_fuzzy_does_not_loosen_phrases_or_exclusions():
    notes = [note("a.md", "full sun for tomatoes"), note("b.md", "tomatoes and blight")]
    assert search(notes, parse_query(['"ful sun"']), fuzzy=True) == []
    hits = search(notes, parse_query(["tomatos", "-blite"]), fuzzy=True)
    assert [h.path for h in hits] == ["a.md", "b.md"]


def test_fuzzy_term_caches_word_decisions():
    term = FuzzyTerm("basel")
    assert term.is_close("basil") and not term.is_close("bagels")
    assert term._close == {"basil": True, "bagels": False}


def test_words_pattern_highlights_whole_words_only():
    pattern = words_pattern(["tomato", "tomatoes"])
    out = highlight("Tomatoes, tomatoey", [pattern], color=True)
    assert out == f"{HIGHLIGHT_ON}Tomatoes{HIGHLIGHT_OFF}, tomatoey"
    assert words_pattern([]) is None


# --- whole words and regex -------------------------------------------------

def test_whole_word_pattern_rejects_parts_of_longer_words():
    p = compile_pattern("tomato", whole_word=True)
    assert p.findall("Tomato, tomatoes, cherry-tomato, tomato_2, (tomato)") == [
        "Tomato", "tomato", "tomato",
    ]


def test_whole_word_works_for_terms_with_symbols_at_the_edges():
    assert compile_pattern("c++", whole_word=True).findall("c++ and c++11") == ["c++"]
    assert compile_pattern("#todo", whole_word=True).findall("a #todo, #todos") == ["#todo"]


def test_whole_word_phrase_still_matches_across_whitespace():
    p = compile_pattern("full sun", whole_word=True)
    assert p.search("needs full\n  sun.")
    assert not p.search("full sunlight")


def test_search_whole_word_terms_and_exclusions():
    notes = [
        note("a.md", "One tomato plant."),
        note("b.md", "Lots of tomatoes."),
        note("c.md", "A tomato next to the cart."),
    ]
    hits = search(notes, parse_query(["tomato"]), whole_word=True)
    assert [h.path for h in hits] == ["a.md", "c.md"]
    # -car only drops whole-word "car", so "cart" doesn't count.
    hits = search(notes, parse_query(["tomato", "-car"]), whole_word=True)
    assert [h.path for h in hits] == ["a.md", "c.md"]
    hits = search(notes, parse_query(["tomato", "-cart"]), whole_word=True)
    assert [h.path for h in hits] == ["a.md"]


def test_whole_word_fuzzy_still_tolerates_typos_but_not_substrings():
    notes = [note("a.md", "Tomatoes here."), note("b.md", "A tomatoey sauce.")]
    hits = search(notes, parse_query(["tomatos"]), fuzzy=True, whole_word=True)
    assert [(h.path, h.fuzzy_words) for h in hits] == [("a.md", ["tomatoes"])]
    # Without typos, -w with --fuzzy matches the word itself, not "tomatoey".
    hits = search(notes, parse_query(["tomato"]), fuzzy=True, whole_word=True)
    assert [h.path for h in hits] == []
    term = FuzzyTerm("tomato", whole_word=True)
    assert term.is_close("tomatos") and not term.is_close("tomato")


def test_regex_terms_are_case_insensitive_and_counted():
    notes = [note("a.md", "Order 12 seeds, then 30 more.\nOrder soil."), note("b.md", "No digits")]
    hits = search(notes, parse_query([r"\d+", "order"]), regex=True)
    assert [(h.path, h.matches, h.line) for h in hits] == [("a.md", 4, 1)]


def test_regex_anchors_match_at_line_boundaries():
    notes = [note("a.md", "# Title\n- [ ] buy seeds\n- [x] plant"), note("b.md", "text - [ ] inline")]
    hits = search(notes, parse_query([r"^- \[ \]"]), regex=True)
    assert [(h.path, h.line, h.snippet) for h in hits] == [("a.md", 2, "- [ ] buy seeds")]


def test_regex_exclusion_and_whole_word_together():
    notes = [note("a.md", "basil 2026-05-02"), note("b.md", "basil 2026-5-2"), note("c.md", "basils")]
    hits = search(notes, parse_query(["basil", r"-\d{4}-\d\d-\d\d"]), regex=True, whole_word=True)
    assert [h.path for h in hits] == ["b.md"]


def test_regex_is_off_by_default():
    notes = [note("a.md", "costs 1+1 dollars"), note("b.md", "costs 11 dollars")]
    assert [h.path for h in search(notes, parse_query(["1+1"]))] == ["a.md"]
    assert [h.path for h in search(notes, parse_query(["1+1"]), regex=True)] == ["b.md"]


@pytest.mark.parametrize("bad, message", [
    ("tomato(", "invalid regex"),
    ("x*", "matches empty text"),
    ("^", "matches empty text"),
])
def test_bad_regexes_raise_query_error(bad, message):
    with pytest.raises(QueryError, match=message):
        compile_pattern(bad, regex=True)


def test_regex_lookaround_zero_width_matches_are_not_counted():
    notes = [note("a.md", "plain text")]
    assert search(notes, parse_query(["(?=text)"]), regex=True) == []


def test_fuzzy_and_regex_cannot_be_combined():
    with pytest.raises(QueryError, match="can't be combined"):
        search([note("a.md", "x")], parse_query(["x"]), fuzzy=True, regex=True)
