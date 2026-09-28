"""The transform extension: a key word the answer must use ('keyword'), the
new sentence printed with one gap ('frame', key word transformation) and a
word limit for the gap ('max_words'), with the checks, answer key and
layout that go with them."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from langwich.answers import answer_key, transform_answer, transform_sentence
from langwich.model import ContractError, TransformTask, worksheet_from_dict
from langwich.plan import plan
from langwich.render import RenderOptions, build_html, render_worksheet
from langwich.render.css import GUTTER_W
from langwich.render.html import Builder, esc
from langwich.render.tasks import frame_blank_width
from langwich.validate import Issue, validate
from tests.test_render import need_pdf

ROOT = Path(__file__).resolve().parent.parent
LENA = ROOT / "examples" / "lena_01_en_de.json"

#: The validator codes this file exercises (collected by tests/test_validate.py).
COVERED_CODES = {"frame-gaps", "keyword-not-used", "answer-too-long", "frame-and-answer"}

#: A key word transformation about Wednesday in the roastery (a new form task
#: on scene s3 of the Lena example).
KWT: dict[str, Any] = {
    "id": "t15", "kind": "transform", "stage": "form", "scene": "s3",
    "title": "Say it another way",
    "max_words": 5,
    "items": [
        {"prompt": "„Pass auf die Bohnen auf!“, ruft Frau Berger.", "keyword": "soll",
         "frame": "Frau Berger ruft, dass Lena {{auf die Bohnen aufpassen soll}}."},
        {"prompt": "Der Kaffee ist so bitter, dass Lena ihn nur mit viel Zucker trinken kann.",
         "keyword": "zu",
         "frame": "Der Kaffee ist {{zu bitter, um ihn}} ohne viel Zucker zu trinken."},
        {"prompt": "Eine dunkle Röstung schmeckt kräftiger als eine helle.", "keyword": "SO",
         "frame": "Eine helle Röstung schmeckt {{nicht so kräftig wie|nicht so stark wie}} "
                  "eine dunkle."},
        {"prompt": "Frau Berger hat die Bohnen am Mittwoch in der Rösterei geröstet.",
         "keyword": "wurden",
         "frame": "Die Bohnen {{wurden von Frau Berger}} am Mittwoch in der Rösterei geröstet."},
    ],
}

#: Reported speech with frames but no key words, and one plain item (a new
#: practice task on scene s4).
TOLD: dict[str, Any] = {
    "id": "t16", "kind": "transform", "stage": "practice", "scene": "s4",
    "title": "What Lena tells Onkel Marco",
    "items": [
        {"prompt": "Herr Novak: „Morgen wieder. Um sieben.“", "cue": "dass",
         "frame": "Herr Novak hat gesagt, dass er {{morgen um sieben wiederkommt}}."},
        {"prompt": "Frau Berger: „Rösten braucht Geduld!“", "cue": "dass",
         "answer": "Frau Berger hat gesagt, dass Rösten Geduld braucht."},
    ],
}


def _lena(task: dict[str, Any] = KWT, **changes: Any) -> dict[str, Any]:
    """The Lena example with ``task`` (plus ``changes``) added as its last task."""
    data = json.loads(LENA.read_text(encoding="utf-8"))
    data["tasks"].append({**copy.deepcopy(task), **changes})
    return data


def _items(changes: dict[int, dict[str, Any]], task: dict[str, Any] = KWT,
           **task_changes: Any) -> dict[str, Any]:
    """``task`` with the fields of some items changed, ``{1: {"keyword": "…"}}``
    (``None`` removes a field)."""
    items = copy.deepcopy(task["items"])
    for j, fields in changes.items():
        for name, value in fields.items():
            if value is None:
                items[j].pop(name, None)
            else:
                items[j][name] = value
    return _lena(task, items=items, **task_changes)


#: Where the added task is in the file (the example has 14 tasks).
AT = "/tasks/14"


def _issues(data: dict[str, Any], code: str | None = None) -> list[Issue]:
    issues = validate(worksheet_from_dict(data)).issues
    return [i for i in issues if code is None or i.code == code]


def _key(data: dict[str, Any], task_id: str = "t15") -> list[str]:
    ws = worksheet_from_dict(data)
    pt = next(pt for pt in plan(ws).tasks if pt.task.id == task_id)
    return answer_key(pt, ws)


def _section(html: str, title: str = KWT["title"]) -> str:
    """The worksheet section of the transform task called ``title``."""
    sections = re.findall(r'<section class="task unit k-transform[^"]*".*?</section>', html,
                          flags=re.S)
    return next(s for s in sections if f"<h3>{esc(title)}</h3>" in s)


def _instruction(data: dict[str, Any], title: str = KWT["title"], **options: Any) -> str:
    section = _section(build_html(worksheet_from_dict(data), RenderOptions(**options)), title)
    match = re.search(r'<p class="ins">(.*?)</p>', section)
    assert match
    return match.group(1)


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_the_new_fields_are_read() -> None:
    task = next(t for t in worksheet_from_dict(_lena()).tasks if t.id == "t15")
    assert isinstance(task, TransformTask)
    assert task.max_words == 5
    first = task.items[0]
    assert first.keyword == "soll" and first.answer is None
    assert first.frame == "Frau Berger ruft, dass Lena {{auf die Bohnen aufpassen soll}}."


def test_a_frame_needs_no_answer_but_a_plain_item_does() -> None:
    worksheet_from_dict(_items({0: {"answer": None}}, TOLD))
    with pytest.raises(ContractError) as exc:
        worksheet_from_dict(_items({1: {"answer": None}}, TOLD))
    ((where, message),) = exc.value.problems
    assert where == f"{AT}/items/1"
    assert "needs an 'answer' (the rewritten sentence), or a 'frame'" in message
    with pytest.raises(ContractError):
        worksheet_from_dict(_items({1: {"answer": "  "}}, TOLD))


@pytest.mark.parametrize(("changes", "where"), [
    ({"max_words": 0}, f"{AT}/max_words"),
    ({"max_words": 11}, f"{AT}/max_words"),
    ({"max_words": "five"}, f"{AT}/max_words"),
])
def test_the_contract_rejects(changes: dict[str, Any], where: str) -> None:
    with pytest.raises(ContractError) as exc:
        worksheet_from_dict(_lena(**changes))
    assert where in [loc for loc, _ in exc.value.problems]


def test_the_new_fields_default_to_a_plain_transform_task() -> None:
    task = next(t for t in worksheet_from_dict(_lena(TOLD)).tasks if t.id == "t16")
    assert isinstance(task, TransformTask)
    assert task.max_words is None
    assert [item.keyword for item in task.items] == [None, None]


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------


def test_key_words_and_frames_are_clean() -> None:
    assert _issues(_lena()) == []
    assert _issues(_lena(TOLD)) == []


@pytest.mark.parametrize("frame", [
    "Frau Berger ruft, dass Lena auf die Bohnen aufpassen soll.",
    "Frau Berger ruft, dass Lena {auf die Bohnen aufpassen soll}.",
])
def test_a_frame_without_a_gap(frame: str) -> None:
    (hit,) = _issues(_items({0: {"frame": frame}}), "frame-gaps")
    assert (hit.level, hit.where) == ("error", f"{AT}/items/0/frame")
    assert "has no {{gap}}" in hit.message and "into one gap" in hit.message
    assert not validate(worksheet_from_dict(_items({0: {"frame": frame}}))).ok


def test_a_frame_with_two_gaps() -> None:
    frame = "Frau Berger ruft, dass Lena {{auf die Bohnen}} {{aufpassen soll}}."
    (hit,) = _issues(_items({0: {"frame": frame}}), "frame-gaps")
    assert (hit.level, hit.where) == ("error", f"{AT}/items/0/frame")
    assert "has 2 gaps ({{auf die Bohnen}}, {{aufpassen soll}})" in hit.message
    assert "Join them into one gap" in hit.message


@pytest.mark.parametrize(("frame", "code"), [
    ("Frau Berger ruft, dass Lena {{ }}.", "empty-gap"),
    ("Frau Berger ruft, dass Lena {{auf die Bohnen aufpassen soll.", "unbalanced-braces"),
    ("Frau Berger ruft, dass Lena {{{auf die Bohnen aufpassen soll}}}.", "unbalanced-braces"),
])
def test_broken_frame_markup_is_reported_once(frame: str, code: str) -> None:
    # (the markup problem, not also a missing gap)
    hits = [(i.code, i.where) for i in _issues(_items({0: {"frame": frame}}))
            if i.where.startswith(f"{AT}/items/0")]
    assert hits == [(code, f"{AT}/items/0/frame")]


def test_a_key_word_the_gap_does_not_use() -> None:
    (hit,) = _issues(_items({1: {"keyword": "damit"}}), "keyword-not-used")
    assert (hit.level, hit.where) == ("warning", f"{AT}/items/1/keyword")
    assert ("the key word 'damit' is not in the words in the gap 'zu bitter, um ihn'"
            in hit.message)
    assert "Rewrite the gap so that it contains 'damit' exactly" in hit.message


def test_a_key_word_is_used_unchanged() -> None:
    # an inflected key word is not the key word, nor is a word that contains it
    (hit,) = _issues(_items({3: {"keyword": "werden"}}), "keyword-not-used")
    assert "unchanged (not inflected, not replaced)" in hit.message
    assert _issues(_items({1: {"keyword": "bitte"}}), "keyword-not-used")  # (not 'bitter')


def test_a_key_word_printed_outside_the_gap() -> None:
    frame = "Der Kaffee ist zu {{bitter, um ihn}} ohne viel Zucker zu trinken."
    (hit,) = _issues(_items({1: {"frame": frame}}), "keyword-not-used")
    assert "printed in the frame, outside the gap '{{bitter, um ihn}}'" in hit.message
    assert "Move it into the gap" in hit.message


def test_every_accepted_answer_uses_the_key_word() -> None:
    frame = "Eine helle Röstung schmeckt {{nicht so kräftig wie|weniger kräftig als}} eine dunkle."
    (hit,) = _issues(_items({2: {"frame": frame}}), "keyword-not-used")
    assert hit.where == f"{AT}/items/2/keyword"
    assert "is in the accepted answer 'nicht so kräftig wie', but not in 'weniger kräftig als'" in (
        hit.message)


def test_a_key_word_in_a_plain_answer() -> None:
    item = {"prompt": "Lena hatte keine Geduld. Trotzdem wollte sie perfekt rösten.",
            "keyword": "obwohl",
            "answer": "Obwohl Lena keine Geduld hatte, wollte sie perfekt rösten."}
    assert _issues(_lena(TOLD, items=[item])) == []
    (hit,) = _issues(_lena(TOLD, items=[{**item, "keyword": "weil"}]), "keyword-not-used")
    assert "is not in the answer 'Obwohl Lena keine Geduld hatte" in hit.message
    assert "Rewrite the answer so that it contains 'weil'" in hit.message


@pytest.mark.parametrize("keyword", ["ZU", " zu ", "Zu"])
def test_key_words_are_compared_without_case_or_spaces(keyword: str) -> None:
    assert _issues(_items({1: {"keyword": keyword}}), "keyword-not-used") == []


def test_a_gap_longer_than_max_words() -> None:
    (hit,) = _issues(_lena(max_words=4), "answer-too-long")
    assert (hit.level, hit.where) == ("warning", f"{AT}/items/0/frame")
    assert "the answer 'auf die Bohnen aufpassen soll' has 5 words" in hit.message
    assert "allows at most 4" in hit.message and "raise max_words to 5" in hit.message
    assert "outside the gap" in hit.message
    # the other gaps have four words ('zu bitter, um ihn' too)
    assert [i.where for i in _issues(_lena(max_words=3), "answer-too-long")] == [
        f"{AT}/items/{j}/frame" for j in range(4)]


def test_an_alternative_longer_than_max_words() -> None:
    frame = "Die Bohnen {{wurden von Frau Berger|wurden am Mittwoch von Frau Berger}} geröstet."
    (hit,) = _issues(_items({3: {"frame": frame}}), "answer-too-long")
    assert hit.where == f"{AT}/items/3/frame"
    assert "the answer 'wurden am Mittwoch von Frau Berger' has 6 words" in hit.message


def test_max_words_and_a_plain_answer() -> None:
    (hit,) = _issues(_lena(TOLD, max_words=5), "answer-too-long")
    assert hit.where == f"{AT}/items/1/answer"
    assert "Without a 'frame', the learner writes the whole new sentence" in hit.message
    assert "or remove max_words from the task" in hit.message


def test_without_max_words_any_length_is_fine() -> None:
    frame = "Die Bohnen {{wurden am Mittwoch von Frau Berger in der Rösterei}} geröstet."
    assert _issues(_items({3: {"frame": frame}}, max_words=None), "answer-too-long") == []


def test_a_frame_and_an_answer() -> None:
    sentence = "Frau Berger ruft, dass Lena auf die Bohnen aufpassen soll."
    (hit,) = _issues(_items({0: {"answer": sentence}}), "frame-and-answer")
    assert (hit.level, hit.where) == ("warning", f"{AT}/items/0/answer")
    assert "'answer' is never used" in hit.message and "Remove 'answer'" in hit.message
    assert "differs" not in hit.message
    # an answer unlike the filled frame: the gap may not hold what was meant
    (hit,) = _issues(_items({0: {"answer": "Lena soll auf die Bohnen aufpassen."}}),
                     "frame-and-answer")
    assert f"differs from the frame with its gap filled, '{sentence}'" in hit.message
    # the answer is not checked against the key word or the limit
    assert [i.code for i in _issues(_items({0: {"answer": "Lena muss " + "sehr " * 9}}))] == [
        "frame-and-answer"]


def test_words_are_not_counted_in_a_language_without_spaces() -> None:
    data = _items({0: {"keyword": "好き", "frame": "レナは{{コーヒーが、とても好きです}}。"}},
                  max_words=1)
    data["target_lang"] = "ja"
    codes = {i.code for i in _issues(data) if i.where.startswith(f"{AT}/items/0")}
    assert not codes & {"keyword-not-used", "answer-too-long"}


# ---------------------------------------------------------------------------
# The answer key
# ---------------------------------------------------------------------------


def test_the_key_shows_what_the_learner_writes() -> None:
    assert _key(_lena()) == [
        "auf die Bohnen aufpassen soll", "zu bitter, um ihn",
        "nicht so kräftig wie / nicht so stark wie", "wurden von Frau Berger",
    ]
    assert _key(_lena(TOLD), "t16") == [
        "morgen um sieben wiederkommt", "Frau Berger hat gesagt, dass Rösten Geduld braucht.",
    ]


def test_answer_and_sentence_of_a_frame() -> None:
    task = next(t for t in worksheet_from_dict(_lena()).tasks if isinstance(t, TransformTask))
    item = task.items[2]
    assert transform_answer(item) == "nicht so kräftig wie / nicht so stark wie"
    assert transform_sentence(item) == "Eine helle Röstung schmeckt nicht so kräftig wie eine dunkle."


# ---------------------------------------------------------------------------
# The worksheet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_key_words_beside_the_prompts_and_frames_with_blanks(page: str) -> None:
    section = _section(build_html(worksheet_from_dict(_lena()), RenderOptions(page=page)))
    items = re.findall(r'<div class="it">.*?</div></div></div>', section, flags=re.S)
    assert len(items) == 4
    assert ('<div class="kwr"><p class="tl q" lang="de">„Pass auf die Bohnen auf!“, ruft Frau '
            'Berger.</p><span class="kw" lang="de">soll</span></div>') in items[0]
    # (capitals by CSS: the words stay as written for the lang attribute)
    assert '<span class="kw" lang="de">SO</span>' in items[2]
    for item in items:
        assert '<div class="frm"><span class="cue">→</span><span class="tl" lang="de">' in item
        assert item.count('class="blank"') == 1
        assert 'class="wl"' not in item and "{{" not in item
    assert "Frau Berger ruft, dass Lena <span class=\"gap pu\">" in items[0]
    assert "</span></span> ohne viel Zucker zu trinken.</span>" in items[1]
    # the answers are not printed
    assert "aufpassen soll" not in section and "zu bitter, um" not in section


def test_plain_items_keep_their_line() -> None:
    section = _section(build_html(worksheet_from_dict(_lena(TOLD))), TOLD["title"])
    items = re.findall(r'<div class="it">.*?</div></div></div>', section, flags=re.S)
    assert '<div class="frm"><span class="cue">→ dass</span>' in items[0]
    assert ('<p class="tl q" lang="de">Frau Berger: „Rösten braucht Geduld!“</p><div class="wl">'
            '<span class="cue">→ dass</span><span class="line"></span></div>') in items[1]
    assert 'class="kw' not in section


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_the_blanks_share_one_width_that_fits_the_line(page: str) -> None:
    data = _lena(grammar="g1")
    del data["tasks"][4]["grammar"]  # (A4: the grammar box beside these items, not t5's)
    section = _section(build_html(worksheet_from_dict(data), RenderOptions(page=page)))
    assert ("<aside" in section) == (page == "a4")
    widths = {float(w) for w in re.findall(r'class="blank" style="width:([\d.]+)mm"', section)}
    assert len(widths) == 1
    width = widths.pop()
    main = 141.8 if page == "epaper" else 120.0
    # wider than print: the longest answer, 'auf die Bohnen aufpassen soll'
    assert 60.0 < width <= main - GUTTER_W - 8.0
    b = Builder(worksheet_from_dict(data), RenderOptions(page=page))
    assert frame_blank_width(b, ["ohne"], False) == 30.0
    line = b.main_width(False) - GUTTER_W - 8.0
    assert frame_blank_width(b, ["sehr " * 40], False) == pytest.approx(line)


def test_the_default_instruction_asks_for_the_key_word() -> None:
    assert _instruction(_lena()) == (
        "Complete the second sentence so that it means the same as the first. Use the word in "
        'capitals. <span class="len">At most 5 words</span>')
    # frames without key words: no word in capitals to use
    assert _instruction(_lena(TOLD), TOLD["title"]) == "Rewrite each sentence as shown."
    one = _items({0: {"keyword": "dass"}}, TOLD)
    assert _instruction(one, TOLD["title"]).startswith("Complete the second sentence")


@pytest.mark.parametrize(("instruction", "shown"), [
    ("Lena sagt es anders. Schreibe 2–5 Wörter.", "Lena sagt es anders. Schreibe 2–5 Wörter."),
    ("Use 15 words or 25.", 'Use 15 words or 25. <span class="len">At most 5 words</span>'),
])
def test_an_own_instruction_gets_the_limit_unless_it_states_it(instruction: str,
                                                                shown: str) -> None:
    assert _instruction(_lena(instruction=instruction)) == shown


def test_no_limit_without_max_words() -> None:
    assert 'class="len"' not in _instruction(_lena(max_words=None))


def test_the_instruction_speaks_the_learners_language() -> None:
    data = _lena()
    data["source_lang"] = "fr"  # (the instruction follows the source language)
    assert _instruction(data, page="epaper") == (
        "Complète la deuxième phrase pour qu’elle ait le même sens que la première. Utilise le "
        'mot en majuscules. <span class="len">5 mots au maximum</span>')
    data["source_lang"] = "de"
    data["target_lang"] = "fr"
    assert _instruction(data).endswith('<span class="len">Höchstens 5 Wörter</span>')


def test_user_text_is_escaped() -> None:
    data = _items({0: {"keyword": "<b>soll</b>", "prompt": "Pass <i>auf</i> & los",
                       "frame": "Lena <u>muss</u> {{auf die <b>Bohnen</b> aufpassen}} & mehr."},
                   1: {"cue": "<em>zu</em>"}})
    data["ui"] = {"kind.transform.max": "max. <b>{max}</b> Wörter"}
    section = _section(build_html(worksheet_from_dict(data)))
    assert '<span class="kw" lang="de">&lt;b&gt;soll&lt;/b&gt;</span>' in section
    assert "Pass &lt;i&gt;auf&lt;/i&gt; &amp; los" in section
    assert "Lena &lt;u&gt;muss&lt;/u&gt; <span class=\"gap\">" in section
    assert "</span></span> &amp; mehr." in section
    assert '<span class="cue">→ &lt;em&gt;zu&lt;/em&gt;</span>' in section
    assert '<span class="len">Max. &lt;b&gt;5&lt;/b&gt; Wörter</span>' in section
    assert "<b>" not in section and "<u>" not in section and "<em>" not in section


def test_the_height_estimate_makes_room_for_frames_and_key_words() -> None:
    def height(data: dict[str, Any]) -> float:
        b = Builder(worksheet_from_dict(data))
        return b.estimate_task_h(next(pt for pt in b.plan.tasks if pt.task.id == "t15"))

    short = height(_lena())
    # a longer frame takes another handwriting line (the last one had two already)
    tail = " und Lena riecht an den grünen Bohnen aus Äthiopien, die wie Heu riechen"
    longer = _lena(items=[{**item, "frame": item["frame"][:-1] + tail + "."}
                          for item in KWT["items"]])
    assert height(longer) > short + 3 * 7.5
    # a prompt beside a long key word has less room (one line more here)
    prompt = "Am Mittwoch hat Frau Berger die grünen Bohnen in der Rösterei geröstet."
    wide = _items({3: {"prompt": prompt}})
    narrow = _items({3: {"prompt": prompt, "keyword": "nichtsdestotrotz"}})
    assert height(narrow) > height(wide)


# ---------------------------------------------------------------------------
# The PDF
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_the_key_word_stands_in_capitals_at_the_end_of_the_prompts_row(
        page: str, tmp_path: Path) -> None:
    fitz = need_pdf(pymupdf=True)
    out = tmp_path / "kwt.pdf"
    render_worksheet(worksheet_from_dict(_lena()), out, RenderOptions(page=page))
    starts = {"SOLL": "„Pass", "ZU": "Der", "SO": "Eine", "WURDEN": "Frau"}
    seen = []
    for pdf_page in fitz.open(out):
        words = pdf_page.get_text("words")  # (x0, y0, x1, y1, word, …), case kept
        caps = [w for w in words if w[4] in starts]
        for kw in caps:
            # the prompt starts on the same row, left of the key word
            middle = (kw[1] + kw[3]) / 2
            assert any(w[4] == starts[kw[4]] and w[1] < middle < w[3] and w[2] < kw[0]
                       for w in words)
            seen.append(kw[4])
        # all flush right
        assert max((w[2] for w in caps), default=0) - min((w[2] for w in caps), default=0) < 1.0
    assert sorted(seen) == sorted(starts)
