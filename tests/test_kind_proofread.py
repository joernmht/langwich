"""proofread: a character's draft with mistakes, marked (underlined and
numbered) or unmarked (only their number is given). The contract, the checks
of the {{correct::wrong}} markup, the answer key and the HTML."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from langwich.answers import answer_key
from langwich.model import ContractError, canonical_kind, worksheet_from_dict
from langwich.plan import PlannedTask, plan
from langwich.render import RenderOptions, build_html
from langwich.validate import Issue, validate

#: The validator codes these tests trigger (see tests/test_validate.py).
COVERED_CODES = {"cloze-without-gaps", "missing-gap-hint", "hint-is-answer", "copies-story"}

REPO = Path(__file__).resolve().parent.parent
LENA = REPO / "examples" / "lena_01_en_de.json"

#: A practice task on scene 4 (it replaces the word_building task t8, and
#: its compound-noun grammar box stands beside it): Lena's note for the
#: Saturday shift, with six mistakes in compounds and the passive.
NOTE: dict[str, Any] = {
    "id": "t8", "kind": "proofread", "stage": "practice", "scene": "s4", "grammar": "g2",
    "title": "A note for the Saturday shift",
    "text": (
        "Hallo Jonas,\n\n"
        "morgen ist dein erster {{Arbeitstag::Arbeittag}} bei uns – keine Angst, das schaffst "
        "du! Um sieben kommt Herr Novak. Er trinkt seine Melange jetzt ohne Zucker, also stell "
        "{{die::der}} Zuckerdose gar nicht erst auf den Tisch. Die neuen Bohnen {{werden::wird}} "
        "am Montag {{geliefert::liefern}}, bitte bring die Säcke gleich in die Rösterei. Und wenn "
        "die Sonne scheint: Der {{Sonnenschirm::Sonneschirm}} steht hinter der "
        "{{Eingangstür::Eingangtür}}.\n\nViel Glück!\nLena"
    ),
}

#: NOTE's position in the task list (for JSON pointers).
INDEX = 7
WHERE = f"/tasks/{INDEX}/text"
WRONG = ["Arbeittag", "der", "wird", "liefern", "Sonneschirm", "Eingangtür"]
RIGHT = ["Arbeitstag", "die", "werden", "geliefert", "Sonnenschirm", "Eingangstür"]


def _lena(text: str | None = None, **fields: Any) -> dict[str, Any]:
    """The Lena example with NOTE as t8; ``text`` and ``fields`` replace its own."""
    data = json.loads(LENA.read_text(encoding="utf-8"))
    task = copy.deepcopy(NOTE)
    if text is not None:
        task["text"] = text
    task.update(fields)
    for key in [k for k, v in task.items() if v is None]:
        del task[key]
    assert data["tasks"][INDEX]["id"] == "t8"
    data["tasks"][INDEX] = task
    return data


def _issues(data: dict[str, Any], code: str | None = None) -> list[Issue]:
    issues = validate(worksheet_from_dict(data)).issues
    return [i for i in issues if code is None or i.code == code]


def _planned(data: dict[str, Any]) -> tuple[Any, PlannedTask]:
    ws = worksheet_from_dict(data)
    return ws, next(pt for pt in plan(ws).tasks if pt.task.id == "t8")


def _section(data: dict[str, Any], page: str = "a4") -> str:
    ws, pt = _planned(data)
    html = build_html(ws, RenderOptions(page=page))
    match = re.search(rf'<section class="task unit[^"]*" id="task-{pt.number}".*?</section>',
                      html, flags=re.S)
    assert match
    return match.group(0)


def _grid(section: str) -> list[str]:
    """The column templates of the rows of correction fields."""
    return re.findall(r'<div class="fr" style="grid-template-columns:([^"]*)">', section)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_mistakes_are_marked_by_default() -> None:
    task = worksheet_from_dict(_lena()).tasks[INDEX]
    assert task.kind == "proofread"
    assert task.marked is True
    assert worksheet_from_dict(_lena(marked=False)).tasks[INDEX].marked is False


@pytest.mark.parametrize("fields", [
    {"text": "   "},                                   # empty after stripping
    {"mistakes": 6},                                   # unknown field
    {"marked": "sometimes"},                           # not a bool
])
def test_invalid_tasks_are_contract_errors(fields: dict[str, Any]) -> None:
    with pytest.raises(ContractError):
        worksheet_from_dict(_lena(**fields))


@pytest.mark.parametrize("field", ["mistakes", "errors", "corrections"])
def test_a_list_of_mistakes_is_sent_to_the_markup(field: str) -> None:
    with pytest.raises(ContractError) as err:
        worksheet_from_dict(_lena(**{field: [{"wrong": "Arbeittag", "right": "Arbeitstag"}]}))
    ((where, message),) = err.value.problems
    assert where == f"/tasks/{INDEX}/{field}"
    assert message.startswith(f"'{field}' is not a field here (write each mistake into 'text' "
                              "as {{correct::wrong}})")


def test_a_task_without_text_is_a_contract_error() -> None:
    data = _lena()
    del data["tasks"][INDEX]["text"]
    with pytest.raises(ContractError):
        worksheet_from_dict(data)


@pytest.mark.parametrize("alias", ["error_correction", "Proofreading", "find-the-mistakes",
                                   "correct the mistakes"])
def test_llm_names_for_the_kind_mean_proofread(alias: str) -> None:
    assert canonical_kind(alias) == "proofread"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("marked", [True, False])
def test_the_task_is_clean(marked: bool) -> None:
    assert _issues(_lena(marked=marked)) == []


def test_a_draft_without_marked_mistakes_is_an_error() -> None:
    issues = _issues(_lena("Hallo Jonas, morgen ist dein erster Arbeitstag."), "cloze-without-gaps")
    assert [(i.level, i.where) for i in issues] == [("error", WHERE)]
    assert "this proofread text has no marked mistakes, so there is nothing to correct" in (
        issues[0].message)
    assert "Write each mistake as {{correct::wrong}}" in issues[0].message


def test_single_braces_are_named() -> None:
    issues = _issues(_lena("Hallo Jonas, morgen ist dein erster {Arbeitstag::Arbeittag}."),
                     "cloze-without-gaps")
    assert "It uses single braces ({Arbeitstag::Arbeittag})" in issues[0].message


def test_a_mistake_without_its_wrong_form_is_an_error() -> None:
    issues = _issues(_lena(NOTE["text"].replace("{{werden::wird}}", "{{werden}}")),
                     "missing-gap-hint")
    assert [(i.level, i.where) for i in issues] == [("error", WHERE)]
    assert "the mistake {{werden}} has no wrong form" in issues[0].message
    assert "{{werden::<the wrong form the character wrote>}}" in issues[0].message


def test_an_empty_wrong_form_is_no_wrong_form() -> None:
    issues = _issues(_lena(NOTE["text"].replace("{{werden::wird}}", "{{werden:: }}")),
                     "missing-gap-hint")
    assert [i.where for i in issues] == [WHERE]


@pytest.mark.parametrize(("gap", "keep"), [
    ("{{werden::wird|werdet}}", "{{werden::wird}}"),
    # the one to keep is a wrong one
    ("{{werden|sollen::werden|wird}}", "{{werden|sollen::wird}}"),
])
def test_more_than_one_wrong_form_is_an_error(gap: str, keep: str) -> None:
    issues = _issues(_lena(NOTE["text"].replace("{{werden::wird}}", gap)), "missing-gap-hint")
    assert [(i.level, i.where) for i in issues] == [("error", WHERE)]
    assert "has 2 wrong forms" in issues[0].message
    assert "'|' included" in issues[0].message
    assert f"Keep one wrong form after the '::' ({keep})" in issues[0].message


@pytest.mark.parametrize("gap", [
    "{{werden::werden}}",
    "{{werden|sollen::sollen}}",           # an accepted alternative
    "{{am Montag::am  Montag}}",           # (spacing does not count)
])
def test_a_correct_form_as_the_mistake_is_flagged(gap: str) -> None:
    issues = _issues(_lena(NOTE["text"].replace("{{werden::wird}}", gap)), "hint-is-answer")
    assert [(i.level, i.where) for i in issues] == [("warning", WHERE)]
    assert "prints a correct form as the mistake, so there is nothing to correct" in (
        issues[0].message)


def test_a_capitalisation_mistake_is_a_mistake() -> None:
    text = NOTE["text"].replace("{{die::der}} Zuckerdose", "die {{Zuckerdose::zuckerdose}}")
    assert _issues(_lena(text)) == []


def test_a_draft_that_copies_the_story_is_flagged() -> None:
    text = ("Seit vierzig Jahren trinkt er hier jeden Morgen eine Melange, immer mit drei "
            "{{Löffeln::Löffel}} Zucker.")
    issues = _issues(_lena(text), "copies-story")
    assert [i.where for i in issues] == [WHERE]


def test_gap_markup_is_read_in_the_text_only() -> None:
    issues = _issues(_lena(title="A {{note}} for Jonas"), "markup-outside-gaps")
    assert [i.where for i in issues] == [f"/tasks/{INDEX}/title"]


# ---------------------------------------------------------------------------
# Answer key
# ---------------------------------------------------------------------------


def test_the_key_gives_each_mistake_and_its_correction() -> None:
    ws, pt = _planned(_lena())
    assert answer_key(pt, ws) == [f"{w}\u00a0→ {r}" for w, r in zip(WRONG, RIGHT)]


def test_the_key_lists_every_accepted_correction() -> None:
    text = "Die Bohnen {{werden|sind::wird}} am Montag {{geliefert::liefern}}."
    ws, pt = _planned(_lena(text))
    assert answer_key(pt, ws) == ["wird\u00a0→ werden / sind", "liefern\u00a0→ geliefert"]


def test_a_mistake_without_its_wrong_form_keys_the_correction() -> None:
    ws, pt = _planned(_lena("Die Bohnen {{werden}} am Montag {{geliefert::liefern}}."))
    assert answer_key(pt, ws) == ["werden", "liefern\u00a0→ geliefert"]


def test_the_key_is_printed_with_numbers() -> None:
    ws, _ = _planned(_lena())
    html = build_html(ws, part="solutions")
    assert '<span class="kn">4</span>\u00a0<span class="k" lang="de">liefern\u00a0→ geliefert' in (
        html)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_marked_mistakes_are_underlined_and_numbered(page: str) -> None:
    section = _section(_lena(), page)
    assert 'class="task unit k-proofread keep' in section
    assert '<div class="draft tl" lang="de">' in section
    assert re.findall(r"<u>(.*?)</u>", section) == WRONG
    assert re.findall(r'<span class="gn">(\d+)</span>', section) == ["1", "2", "3", "4", "5", "6"]
    assert section.count('<div class="fld"><span>') == 6
    assert '<p class="ins">Correct the underlined mistakes.</p>' in section
    assert "todo" not in section


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_unmarked_mistakes_stand_in_the_text_as_they_are(page: str) -> None:
    section = _section(_lena(marked=False), page)
    assert "<u>" not in section and 'class="gn"' not in section
    assert "also stell der Zuckerdose gar nicht erst" in section
    assert "Die neuen Bohnen wird am Montag liefern, bitte" in section
    assert re.findall(r'<div class="fx"><span>(\d+)</span>', section) == [
        "1", "2", "3", "4", "5", "6"]
    assert section.count('<span class="ar">→</span>') == 6
    assert '<p class="ins">The text has 6 mistakes. Find them and correct them.</p>' in section


@pytest.mark.parametrize("marked", [True, False])
def test_the_corrections_are_not_on_the_page(marked: bool) -> None:
    section = _section(_lena(marked=marked))
    for right in ("Arbeitstag", "werden", "geliefert", "Sonnenschirm", "Eingangstür"):
        assert right not in section


def test_the_task_instruction_wins() -> None:
    section = _section(_lena(marked=False, instruction="Lena is tired. Find six mistakes."))
    assert '<p class="ins">Lena is tired. Find six mistakes.</p>' in section


def test_paragraphs_and_line_breaks_are_kept() -> None:
    section = _section(_lena())
    assert "<p>Hallo Jonas,</p><p>morgen ist dein erster" in section
    assert "<p>Viel Glück!<br>Lena</p>" in section


def test_punctuation_stays_with_the_number() -> None:
    section = _section(_lena())
    assert '<span class="nw"><u>liefern</u><span class="gn">4</span>,</span> bitte' in section
    assert '<span class="nw"><u>Eingangtür</u><span class="gn">6</span>.</span></p>' in section


def test_only_the_last_word_of_a_long_mistake_is_kept_with_its_number() -> None:
    text = "Der Kaffee {{hat so bitter geschmeckt::ist so bitter geschmeckt}}, dass sie lacht."
    section = _section(_lena(text))
    assert ('<u>ist so bitter </u><span class="nw"><u>geschmeckt</u><span class="gn">1</span>,'
            '</span>') in section


@pytest.mark.parametrize(("fields", "page", "grid"), [
    ({}, "a4", "repeat(2, 1fr)"),                       # beside the grammar box
    ({"grammar": None}, "a4", "repeat(3, 1fr)"),        # the full width
    ({}, "epaper", "repeat(2, 1fr)"),
    ({"marked": False, "grammar": None}, "a4", "repeat(1, 1fr)"),
    ({"marked": False}, "epaper", "repeat(1, 1fr)"),
])
def test_the_fields_fill_the_width(fields: dict[str, Any], page: str, grid: str) -> None:
    section = _section(_lena(**fields), page)
    rows = _grid(section)
    assert set(rows) == {grid}
    cols = int(grid[len("repeat("):grid.index(",")])
    assert len(rows) == -(-6 // cols)


def test_short_corrections_share_a_row_even_unmarked() -> None:
    text = "Die Bohnen {{werden::wird}} am Montag {{geliefert::liefern}}. Er {{ist::hat}} müde."
    section = _section(_lena(text, marked=False, grammar=None))
    assert _grid(section) == ["repeat(2, 1fr)", "repeat(2, 1fr)"]


def test_rows_are_balanced() -> None:
    text = " ".join(f"Wort {{{{a{k}::b{k}}}}}." for k in range(5))
    section = _section(_lena(text, grammar=None))
    assert _grid(section) == ["repeat(3, 1fr)", "repeat(3, 1fr)"]  # 3 + 2, not 4 + 1
    assert section.count('<div class="fld">') == 5


def test_text_and_mistakes_are_escaped() -> None:
    text = "Lena <b>schreibt</b> {{schnell::<i>schnel</i>}} & müde."
    section = _section(_lena(text))
    assert "Lena &lt;b&gt;schreibt&lt;/b&gt;" in section
    assert "<u>&lt;i&gt;schnel&lt;/i&gt;</u>" in section and "&amp; müde" in section
    assert "<b>" not in section and "<i>" not in section
