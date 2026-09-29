"""Level-aware briefs and the task budget: each CEFR level gets its own
recommended task set, the rules of its own kinds and a task range that the
validator checks (task-count)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from langwich.model import STAGES, TASK_KINDS, MediaSearchTask, json_schema, worksheet_from_dict
from langwich.prompt import (
    COMPACT_SCENES,
    KIND_RULES,
    LEVELS,
    MINI_EXAMPLE,
    PromptOptions,
    build_prompt,
    compact_example,
    kind_rules,
)
from langwich.validate import (
    DEFAULT_SCENES,
    PAIRED_SCENE_LEVELS,
    SCENES_MAX,
    SCENES_MIN,
    STORY_WORDS,
    TASK_COUNT,
    task_range,
    validate,
)

#: The validator codes these tests trigger (see tests/test_validate.py).
COVERED_CODES = {"task-count"}

REPO = Path(__file__).resolve().parent.parent
LENA = REPO / "examples" / "lena_01_en_de.json"

#: The kinds the compact prompt's task list asks for (its picture task is a
#: draw task, or a label task with an attached picture).
COMPACT_KINDS = {"match", "true_false", "multiple_choice", "questions", "cloze", "writing",
                 "media_search"}


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(prompt: str, start: str, end: str) -> str:
    """The part of ``prompt`` from the heading ``start`` to the heading ``end``."""
    return prompt[prompt.index(start):prompt.index(end)]


def _named_kinds(text: str) -> set[str]:
    """Kinds named as bare words (not inside quotes, not part of a longer word)."""
    return {k for k in TASK_KINDS if re.search(rf'(?<![\w"]){k}(?![\w"])', text)}


def _rule_kinds(text: str) -> set[str]:
    """Kinds whose rule ('kind: …') the text prints."""
    return {k for k in TASK_KINDS if re.search(rf'(?<![\w"]){k}:\s', text)}


def _contract_words() -> set[str]:
    """Every field name and every literal value of the langwich/3 schema."""
    words: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            words.update(node.get("properties", {}))
            words.update(v for v in node.get("enum", []) if isinstance(v, str))
            if isinstance(node.get("const"), str):
                words.add(node["const"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json_schema())
    return words


def _steps(recipe: str) -> list[list[str]]:
    """The numbered steps of a recipe, each as its text between the markers."""
    return [[f for f in (_flat(p) for p in re.split(r"<<\w+>>", step)) if f]
            for step in re.split(r"\n(?=\d\. )", recipe)]


# ---------------------------------------------------------------------------
# One budget, in the brief and in the validator
# ---------------------------------------------------------------------------


def test_the_validator_checks_the_budgets_of_the_brief() -> None:
    assert TASK_COUNT == {level: spec.tasks for level, spec in LEVELS.items()}
    assert DEFAULT_SCENES == {level: spec.scenes for level, spec in LEVELS.items()}
    assert STORY_WORDS == {level: spec.words for level, spec in LEVELS.items()}
    assert all(low <= high for low, high in TASK_COUNT.values())
    for level in LEVELS:
        assert task_range(level, DEFAULT_SCENES[level]) == TASK_COUNT[level]


@pytest.mark.parametrize(("level", "scenes", "expected"), [
    ("A1", 7, (12, 15)), ("A2", 7, (12, 16)), ("A1", 5, (10, 13)),   # one task per scene more
    ("B1", 6, (12, 16)), ("A2", 2, (7, 12)), ("B1", 2, (8, 14)),     # fewer: the top stays
    ("C1", 6, (10, 14)), ("C1", 7, (11, 15)), ("C2", 7, (11, 15)),   # one per two scenes
    ("C1", 3, (9, 14)), ("C1", 2, (8, 14)),
])
def test_the_task_range_follows_the_scene_count(level: str, scenes: int,
                                                expected: tuple[int, int]) -> None:
    assert task_range(level, scenes) == expected


def _recipe_minimum(level: str, scenes: int, grammar_points: int) -> int:
    """The tasks a brief-following worksheet cannot do without: the match, the
    comprehension tasks, the picture task (optional at C1–C2), a form task per
    grammar point, the practice task, the writing task and the personal
    question."""
    paired = level in PAIRED_SCENE_LEVELS
    comprehension = -(-scenes // 2) if paired else scenes
    return 1 + comprehension + (0 if paired else 1) + grammar_points + 1 + 2


#: --scenes: none (the level's default) or each number the validator accepts
SCENE_COUNTS = [None, *range(SCENES_MIN, SCENES_MAX + 1)]


@pytest.mark.parametrize("level", list(LEVELS))
@pytest.mark.parametrize("scenes", SCENE_COUNTS)
def test_the_recipe_fits_the_range_at_every_scene_count(level: str, scenes: int | None) -> None:
    """A worksheet that has only what the recipe requires is never told to
    remove a task (A2 with 7 scenes needs 13: 'Tasks: 8–12' could not be met)."""
    n = scenes or DEFAULT_SCENES[level]
    low, high = task_range(level, n)
    for grammar_points in (1, 2):
        assert _recipe_minimum(level, n, grammar_points) <= high
    brief = _flat(build_prompt(PromptOptions(level=level, scenes=scenes)))
    assert f"Tasks: {low}–{high}" in brief
    assert f"Recommended set for {level} ({low}–{high} tasks):" in brief
    assert f"Yours follows the brief: {n} scenes, {low}–{high} tasks" in brief


@pytest.mark.parametrize("level", list(LEVELS))
@pytest.mark.parametrize("scenes", SCENE_COUNTS)
def test_the_compact_task_list_fits_its_range(level: str, scenes: int | None) -> None:
    """The compact brief's list is fixed — one task per step, one
    comprehension task per scene and the personal question besides the
    writing task — and always inside the range it states (C1 used to ask for
    10–14 and list 9)."""
    compact = _flat(build_prompt(PromptOptions(level=level, compact=True, scenes=scenes)))
    n = scenes or COMPACT_SCENES
    low, high = task_range(level, n)
    assert f"and {low}–{high} tasks about it" in compact
    assert f"**Tasks.** {low}–{high} in all" in compact
    tasks = compact.split("**Tasks.**", 1)[1].split("**Items.**", 1)[0]
    assert re.findall(r"(?<= )\d(?=\. )", tasks) == list("1234567")
    assert "gist/detail: one task per scene (" in tasks
    assert tasks.count("Plus one personal question") == 1
    listed = 7 + (n - 1) + 1  # the steps, the other scenes' tasks, the personal question
    assert low <= listed <= high


@pytest.mark.parametrize("example", [MINI_EXAMPLE, compact_example()], ids=["full", "compact"])
def test_the_examples_have_as_many_tasks_as_an_a2_worksheet_needs(example: dict) -> None:
    low, high = task_range(example["cefr_level"], len(example["story"]["scenes"]))
    assert low <= len(example["tasks"]) <= high
    heading = "2 scenes, " + str(len(example["tasks"])) + " tasks"
    assert heading in _flat(build_prompt(PromptOptions(compact=example is not MINI_EXAMPLE)))


# ---------------------------------------------------------------------------
# The recipes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", list(LEVELS))
def test_the_brief_prints_only_the_recipe_of_its_level(level: str) -> None:
    brief = _flat(build_prompt(PromptOptions(level=level)))
    assert brief.count("Recommended set for") == 1
    own = _steps(LEVELS[level].recipe)
    for step in own:
        for fragment in step:
            assert fragment in brief, fragment
    for other, spec in LEVELS.items():
        for step in _steps(spec.recipe):
            if step not in own:  # a step of another level's recipe
                assert not all(f in brief for f in step), (other, step)


@pytest.mark.parametrize("level", list(LEVELS))
def test_every_kind_a_recipe_names_is_one_of_its_level(level: str) -> None:
    spec = LEVELS[level]
    assert set(spec.kinds) <= set(TASK_KINDS)
    assert list(spec.kinds) == [k for k in TASK_KINDS if k in spec.kinds]  # TASK_KINDS order
    assert _named_kinds(spec.recipe) <= set(spec.kinds), _named_kinds(spec.recipe)
    # the lesson arc as printed (with the picture tasks filled in) as well
    for opts in (PromptOptions(level=level), PromptOptions(level=level, image="p.jpg")):
        arc = _section(build_prompt(opts), "## 6. The lesson arc", "## 7. Item quality")
        assert _named_kinds(arc) <= set(spec.kinds), _named_kinds(arc) - set(spec.kinds)


@pytest.mark.parametrize("level", list(LEVELS))
def test_recipes_use_only_kinds_stages_and_fields_that_exist(level: str) -> None:
    recipe = re.sub(r"<<\w+>>", "", LEVELS[level].recipe)
    known = _contract_words()
    for word in re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", recipe):
        assert word in set(TASK_KINDS) | set(STAGES) | known, word
    for word in re.findall(r'"([a-z_]+)"', recipe):
        assert word in known, word
    assert "<<picture_tasks>>" in LEVELS[level].recipe
    assert len(_steps(recipe)) == 7


@pytest.mark.parametrize("level", list(LEVELS))
def test_a_recipe_that_names_a_medium_sets_it(level: str) -> None:
    """media_search prints "video" unless "media" says otherwise."""
    assert MediaSearchTask.model_fields["media"].default == "video"
    recipe = _flat(LEVELS[level].recipe)
    for medium in ("article", "podcast", "image"):
        if re.search(rf"\b{medium}\b", recipe):
            assert f'"media": "{medium}"' in recipe, medium


@pytest.mark.parametrize("level", list(LEVELS))
def test_a_picture_is_optional_only_at_c1_c2_and_never_without_its_task(level: str) -> None:
    """C1–C2 may leave the picture out — but a picture there still needs its
    labels and label task, or a draw task (labels without a label task print
    markers with nothing to do)."""
    optional = level in ("C1", "C2")
    brief = build_prompt(PromptOptions(level=level))
    picture = _flat(_section(brief, "## 8. The picture", "## 9."))
    arc = _flat(_section(brief, "## 6. The lesson arc", "## 7. Item quality"))
    assert (f"At {level} a picture is optional" in picture) == optional
    assert ("gets a picture" in picture) == (not optional)
    assert ("3. picture: optional; if a scene has a picture, a label task" in arc) == optional
    if optional:
        assert "comes with its task: labels and a label task (A) or a draw task (B)" in picture
    # an attached picture, and the compact brief's fixed list, always have their task
    attached = _flat(build_prompt(PromptOptions(level=level, image="p.jpg")))
    assert "3. picture: a label task on the scene with the attached picture" in attached
    compact = _flat(build_prompt(PromptOptions(level=level, compact=True)))
    assert "3. picture: a draw task on the scene with the picture." in compact


@pytest.mark.parametrize("level", list(LEVELS))
def test_comprehension_tasks_per_scene_or_per_two_scenes(level: str) -> None:
    paired = level in PAIRED_SCENE_LEVELS
    assert paired == (level in ("C1", "C2"))
    text = _flat(build_prompt(PromptOptions(level=level)))
    assert ("one task per one or two scenes" in text) == paired
    assert ("one task per scene" in text) == (not paired)
    # the compact brief keeps to one per scene: its fixed list must reach its range
    compact = _flat(build_prompt(PromptOptions(level=level, compact=True)))
    assert "one task per scene" in compact and "one or two scenes" not in compact


# ---------------------------------------------------------------------------
# The kind rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", list(LEVELS))
def test_the_brief_prints_the_rules_of_the_level_kinds_only(level: str) -> None:
    spec = LEVELS[level]
    brief = build_prompt(PromptOptions(level=level))
    items = _section(brief, "## 7. Item quality", "## 8. The picture")
    assert _rule_kinds(items) == set(spec.kinds)
    flat = _flat(brief)
    for kind in TASK_KINDS:
        head = _flat(KIND_RULES[kind].split("<<")[0])
        assert (head in flat) == (kind in spec.kinds), kind
        assert re.search(rf"(?m)^{kind} +\S", brief), f"{kind} missing from the reference"


@pytest.mark.parametrize("level", list(LEVELS))
@pytest.mark.parametrize("image", [None, "p.jpg"], ids=["drawn", "photo"])
def test_the_compact_brief_prints_the_core_rules_of_its_own_kinds(level: str,
                                                                  image: str | None) -> None:
    spec = LEVELS[level]
    compact = build_prompt(PromptOptions(level=level, compact=True, image=image))
    rules = _flat(compact.split("**Kinds.**", 1)[1].split("**Picture.**", 1)[0])
    picture = "label" if image else "draw"
    assert _rule_kinds(rules) == (COMPACT_KINDS | {picture}) & set(spec.kinds)
    assert "From B1" not in rules and '"input"' not in rules  # options of other levels
    for kind in TASK_KINDS:
        assert re.search(rf"(?m)^{kind} +\S", compact), f"{kind} missing from the reference"


def test_core_rules_are_the_first_sentence_of_each_rule() -> None:
    for kind, rule in KIND_RULES.items():
        core = kind_rules([kind], core=True)
        assert core.startswith(f"{kind}: ") and core.endswith(".")
        first = core.removeprefix(f"{kind}: ")
        assert rule.startswith(first.rstrip(".")), kind
        assert len(first) > 20, kind
    assert kind_rules(["true_false"], core=True) == (
        'true_false: 3–5 statements, both kinds; a false one changes one detail and has a '
        '"correction".')
    assert "e.g." in kind_rules(["questions"])  # a sentence does not end after "e.g."


@pytest.mark.parametrize("level", list(LEVELS))
def test_compact_asks_for_simple_sentences_up_to_b1(level: str) -> None:
    compact = build_prompt(PromptOptions(level=level, compact=True))
    assert ("Keep sentences simple." in compact) == (level in ("A1", "A2", "B1"))
    assert ('questions with a "starter"' in _flat(compact)) == (level in ("A1", "A2"))


# ---------------------------------------------------------------------------
# The validator: task-count
# ---------------------------------------------------------------------------


def _lena_with(level: str, n: int, scenes: int = 4) -> dict[str, Any]:
    """Lena's episode (B1, 4 scenes, 14 tasks) as ``level`` with ``n`` tasks:
    cut from the end, or filled up with copies of its personal question; and
    with ``scenes`` scenes: more are copies of the last one."""
    data = json.loads(LENA.read_text(encoding="utf-8"))
    data["cefr_level"] = level
    story = data["story"]["scenes"]
    assert scenes >= len(story)
    while len(story) < scenes:
        story.append({**copy.deepcopy(story[-1]), "id": f"s{len(story) + 1}"})
    tasks = data["tasks"][:n]
    personal = next(t for t in data["tasks"] if t["kind"] == "questions"
                    and t["stage"] == "production")
    while len(tasks) < n:
        tasks.append({**copy.deepcopy(personal), "id": f"x{len(tasks)}"})
    data["tasks"] = tasks
    return data


def _task_count(data: dict[str, Any]) -> list[Any]:
    return [i for i in validate(worksheet_from_dict(data)).issues if i.code == "task-count"]


def test_lena_is_within_the_b1_budget() -> None:
    data = json.loads(LENA.read_text(encoding="utf-8"))
    assert len(data["tasks"]) == TASK_COUNT["B1"][1]
    assert _task_count(data) == []


@pytest.mark.parametrize("level", list(LEVELS))
@pytest.mark.parametrize("scenes", [4, 7])
def test_task_count_range_is_inclusive(level: str, scenes: int) -> None:
    low, high = task_range(level, scenes)
    for n in (low, high):
        assert _task_count(_lena_with(level, n, scenes)) == [], n
    for n in (low - 1, high + 1):
        issues = _task_count(_lena_with(level, n, scenes))
        assert [(i.level, i.where) for i in issues] == [("warning", "/tasks")], n


def test_too_many_tasks_says_how_many_to_remove_and_what_to_keep() -> None:
    [issue] = _task_count(_lena_with("B1", 16))
    assert issue.message.startswith("the worksheet has 16 tasks; a B1 worksheet with 4 scenes "
                                    "should have 10–14. Remove 2 or more tasks")
    assert "keep one comprehension task per scene, the picture, form, practice and " \
           "production tasks" in issue.message


def test_too_few_tasks_says_how_many_to_add_and_which() -> None:
    [issue] = _task_count(_lena_with("A2", 6))
    assert issue.message.startswith("the worksheet has 6 tasks; an A2 worksheet with 4 scenes "
                                    "should have 9–13. Add 3 or more tasks")
    for what in ("a comprehension task per scene", "a form task per grammar point",
                 "a personal question", "media_search"):
        assert what in issue.message, what


def test_task_count_message_follows_the_level() -> None:
    [a1] = _task_count(_lena_with("A1", 13))
    assert "an A1 worksheet with 4 scenes should have 9–12. Remove 1 or more tasks" in a1.message
    [c1] = _task_count(_lena_with("C1", 8))
    assert "a C1 worksheet with 4 scenes should have 9–14. Add 1 or more tasks" in c1.message
    assert "a comprehension task per one or two scenes" in c1.message


def _only_the_recipe(level: str, scenes: int) -> dict[str, Any]:
    """Lena's episode as ``level`` with ``scenes`` scenes and only the tasks
    the recipe cannot do without: the match, one comprehension task per scene,
    the label task, a form task per grammar point (2), the practice task, the
    writing task and the personal question."""
    data = _lena_with(level, 14, scenes)
    first = {(t["kind"], t["stage"]): t for t in reversed(data["tasks"])}
    tasks = [first["match", "warm_up"]]
    tasks += [{**copy.deepcopy(first["true_false", "gist"]), "id": f"c{k}", "scene": scene["id"]}
              for k, scene in enumerate(data["story"]["scenes"])]
    tasks.append(first["label", "picture"])
    tasks += [t for t in data["tasks"] if t["stage"] == "form"]
    tasks += [first[key] for key in (("cloze", "practice"), ("writing", "production"),
                                     ("questions", "production"))]
    data["tasks"] = tasks
    return data


@pytest.mark.parametrize("level", list(LEVELS))
@pytest.mark.parametrize("scenes", [4, 5, 6, 7])
def test_a_worksheet_with_only_what_the_recipe_needs_is_within_range(level: str,
                                                                       scenes: int) -> None:
    """At A2 with 7 scenes that is 14 tasks: the old fixed range (8–12) asked
    to remove tasks that the recipe (and the message itself) said to keep."""
    data = _only_the_recipe(level, scenes)
    assert len(data["tasks"]) == scenes + 7
    assert _task_count(data) == []
