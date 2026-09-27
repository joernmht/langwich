"""The authoring prompt (any LLM) and the repair prompt."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from langwich import locale
from langwich.model import (
    POS_VALUES,
    STAGES,
    TASK_KINDS,
    Character,
    ClozeTask,
    DialogueLine,
    DialogueTask,
    DrawTask,
    Fact,
    GrammarPoint,
    GrammarTable,
    Label,
    LabelTask,
    MatchTask,
    MediaSearchTask,
    MultipleChoiceTask,
    OrderEventsTask,
    Picture,
    QuestionsTask,
    Scene,
    Series,
    Story,
    TransformTask,
    TrueFalseTask,
    VocabItem,
    Vocabulary,
    WordBuildingTask,
    Worksheet,
    WritingTask,
    load_worksheet,
    worksheet_from_dict,
)
from langwich.model import _TaskBase as TaskBase
from langwich.prompt import (
    KIND_FIELDS,
    LEVELS,
    MINI_EXAMPLE,
    PromptOptions,
    ResolvedOptions,
    build_prompt,
    compact_example,
    field_reference,
    repair_prompt,
    resolve_options,
)

REPO = Path(__file__).resolve().parent.parent
LENA = REPO / "examples" / "lena_01_en_de.json"
IMAGE = "examples/pictures/cafe_lindner.svg"

#: A trimmed langwich v2 file (flat text, vocabulary, grammar, picture scene).
LEGACY: dict = {
    "title": "Le cinéma : une passion française",
    "content": "Le cinéma est né en France. En 1895, les frères Lumière ont montré leur premier "
               "film au public, à Paris.\n\nDans une petite salle à Lyon, un jeune homme cherche "
               "sa place.",
    "translation": "Das Kino wurde in Frankreich geboren.",
    "source_lang": "de",
    "target_lang": "fr",
    "cefr_level": "B1",
    "topic": "cinema",
    "picture_scene": {"description": "A small movie theater in Lyon.",
                      "elements": ["fauteuils", "écran"]},
    "vocabulary": {"items": [{"term": "le cinéma", "translation": "das Kino", "pos": "noun"}]},
    "grammar": {"phenomena": [{"name": "passé composé", "description": "…",
                               "examples": ["Les frères Lumière ont montré leur premier film."]}]},
    "exercises": [{"type": "fill_blanks"}],
}

KIND_MODELS = {
    "match": MatchTask, "true_false": TrueFalseTask, "multiple_choice": MultipleChoiceTask,
    "order_events": OrderEventsTask, "questions": QuestionsTask, "cloze": ClozeTask,
    "transform": TransformTask, "word_building": WordBuildingTask, "label": LabelTask,
    "writing": WritingTask, "dialogue": DialogueTask, "media_search": MediaSearchTask,
    "draw": DrawTask,
}
ITEM_MODELS = {
    "true_false": TrueFalseTask, "multiple_choice": MultipleChoiceTask,
    "questions": QuestionsTask, "transform": TransformTask, "word_building": WordBuildingTask,
}


def _flat(text: str) -> str:
    """The prompt with line wraps undone, for phrase checks."""
    return " ".join(text.split())


def _fields(model) -> set[str]:
    return {info.alias or name for name, info in model.model_fields.items()}


def _item_model(task_model):
    annotation = task_model.model_fields["items"].annotation
    return annotation.__args__[0]


@pytest.fixture(scope="module")
def lena() -> Worksheet:
    return load_worksheet(LENA)


@pytest.fixture(scope="module")
def normal() -> str:
    return build_prompt(PromptOptions(topic="bread", frame="reportage"))


# ---------------------------------------------------------------------------
# The example
# ---------------------------------------------------------------------------


def test_mini_example_matches_the_model():
    ws = worksheet_from_dict(MINI_EXAMPLE)
    assert ws.schema_id == "langwich/3"
    assert len(ws.story.scenes) == 2
    kinds = {t.kind for t in ws.tasks}
    assert len(kinds) >= 5
    assert all(s.translation for s in ws.story.scenes)


def test_compact_example_matches_the_model():
    ws = worksheet_from_dict(compact_example())
    assert any(t.kind == "draw" for t in ws.tasks)
    assert not any(t.kind == "label" for t in ws.tasks)
    assert all(s.picture is None or not s.picture.svg for s in ws.story.scenes)


@pytest.mark.parametrize("example", [MINI_EXAMPLE, compact_example()], ids=["full", "compact"])
def test_examples_pass_the_validator_cleanly(example):
    validate = pytest.importorskip("langwich.validate")
    report = validate.validate(worksheet_from_dict(example))
    assert report.ok, report.format_text()
    assert not report.issues, report.format_text()


def test_example_does_not_change_between_calls():
    before = json.dumps(MINI_EXAMPLE, sort_keys=True)
    compact_example()
    build_prompt(PromptOptions(compact=True))
    assert json.dumps(MINI_EXAMPLE, sort_keys=True) == before


def _embedded_json(prompt: str) -> dict:
    m = re.search(r"```json\n(\{\n \"schema\".*?)\n```", prompt, re.DOTALL)
    assert m, "no example JSON in the prompt"
    return json.loads(m.group(1))


def test_embedded_example_is_valid_json(normal: str):
    assert _embedded_json(normal) == json.loads(json.dumps(MINI_EXAMPLE))
    compact = build_prompt(PromptOptions(compact=True))
    assert _embedded_json(compact) == json.loads(json.dumps(compact_example()))


# ---------------------------------------------------------------------------
# Field reference: in sync with model.py
# ---------------------------------------------------------------------------


def test_every_task_kind_is_in_the_field_reference(normal: str):
    assert set(KIND_FIELDS) == set(TASK_KINDS)
    for kind in TASK_KINDS:
        assert re.search(rf"(?m)^{kind} +\S", normal), f"{kind} missing from the reference"


@pytest.mark.parametrize("kind", TASK_KINDS)
def test_kind_line_names_every_field_of_its_model(kind: str):
    line = KIND_FIELDS[kind]
    own = _fields(KIND_MODELS[kind]) - _fields(TaskBase) - {"kind"}
    if kind == "label":
        own.add("scene")  # required for label tasks, so repeated in its line
    for name in own:
        assert f'"{name}"' in line, f"{kind}: field {name!r} missing"
    if kind in ITEM_MODELS:
        for name in _fields(_item_model(KIND_MODELS[kind])):
            assert f'"{name}"' in line, f"{kind} item: field {name!r} missing"
    if kind == "match":
        assert '"left"' in line and '"right"' in line
    if kind == "dialogue":
        for name in _fields(DialogueLine):
            assert f'"{name}"' in line


@pytest.mark.parametrize("terse", [False, True])
def test_reference_names_every_model_field(terse: bool):
    ref = field_reference({"S": "English", "T": "German", "src": "en", "tgt": "de",
                           "level": "B1"}, terse=terse)
    models = [Worksheet, Story, Character, Scene, Picture, Label, Fact, Series, VocabItem,
              Vocabulary, GrammarPoint, GrammarTable, TaskBase]
    for model in models:
        for name in _fields(model):
            assert f'"{name}"' in ref, f"{model.__name__}.{name} missing"
    for value in (*STAGES, *POS_VALUES, "setup", "climax", "reportage", "case_study"):
        assert value in ref


def test_terse_reference_is_shorter_but_complete():
    values = {"S": "English", "T": "German", "src": "en", "tgt": "de", "level": "B1"}
    full, terse = field_reference(values), field_reference(values, terse=True)
    assert len(terse) < len(full)
    for kind in TASK_KINDS:
        assert kind in terse


# ---------------------------------------------------------------------------
# The normal prompt
# ---------------------------------------------------------------------------


def test_normal_prompt_has_the_brief(normal: str):
    assert "English (en)" in normal and "German (de)" in normal
    assert "Topic: bread" in normal
    assert "reportage" in normal
    assert "4 scenes" in normal
    assert "220–450 words" in normal
    assert "10–14" in normal


def test_normal_prompt_covers_craft_levels_and_arc(normal: str):
    flat = _flat(normal)
    for phrase in (
        "Facts must be true", "Never invent numbers", "Show, don't lecture", "complication",
        "Did you know?", "Which language where", "at least three tasks", "The lesson arc",
        "CONTINUES the story", "One defensible answer", "No give-aways", "Gap markup",
        "Before you answer, check", "Reply with the JSON object only", '"schema": "langwich/3"',
    ):
        assert phrase in flat, phrase
    for level, spec in LEVELS.items():
        low, high = spec.words
        assert re.search(rf"\| \**{level}\** \| {low}–{high} \|", normal), level
    for stage in STAGES:
        assert stage in normal
    assert "Learner's wishes" not in normal


def test_no_unfilled_markers(lena: Worksheet):
    legacy = LEGACY
    variants = [
        PromptOptions(),
        PromptOptions(compact=True),
        PromptOptions(image=IMAGE, color=True),
        PromptOptions(image=IMAGE, compact=True),
        PromptOptions(continue_from=lena),
        PromptOptions(continue_from=lena, compact=True, image="x.jpg"),
        PromptOptions(frame="episode", topic="Kaffee"),
        PromptOptions(from_text="Ein Text.", from_legacy=legacy, notes="Mehr Humor."),
        PromptOptions(source_lang="nl", target_lang="ja", level="C2"),
    ]
    for opts in variants:
        text = build_prompt(opts)
        assert not re.search(r"<<\w+>>", text), opts
        assert text.endswith("\n")


@pytest.mark.parametrize(("level", "scenes"), [
    ("A1", 3), ("A2", 3), ("B1", 4), ("B2", 4), ("C1", 5), ("C2", 5),
])
def test_default_scene_count_by_level(level: str, scenes: int):
    assert f"{scenes} scenes" in build_prompt(PromptOptions(level=level))


def test_explicit_scene_count_wins():
    text = _flat(build_prompt(PromptOptions(level="B1", scenes=6)))
    assert "6 scenes" in text
    assert "setup → development → development → complication → climax → resolution" in text
    assert "3 scenes" in build_prompt(PromptOptions(level="C1", compact=True))


def test_unknown_level_is_rejected():
    with pytest.raises(ValueError):
        build_prompt(PromptOptions(level="D1"))


def test_prompt_is_deterministic():
    opts = PromptOptions(topic="bees", level="A2")
    assert build_prompt(opts) == build_prompt(opts)


def test_examples_follow_the_target_language():
    fr = build_prompt(PromptOptions(source_lang="de", target_lang="fr"))
    assert "{{prend::prendre}}" in fr and "{{farine::Mehl}}" in fr
    assert "{{wird::werden}}" not in fr
    assert "« … »" in fr
    de = build_prompt(PromptOptions())
    assert "{{wird::werden}}" in de and "{{Mehl::flour}}" in de


def test_monochrome_and_colour():
    mono = _flat(build_prompt(PromptOptions()))
    assert "black and white" in mono
    assert "black-and-white line drawing" in mono
    colour = _flat(build_prompt(PromptOptions(color=True)))
    assert "Colour is allowed" in colour


def test_notes_are_appended_verbatim():
    notes = "Please make Herr Novak grumpy — and set it in winter."
    text = build_prompt(PromptOptions(notes=notes))
    assert "## Learner's wishes" in text
    assert notes in text.split("## Learner's wishes", 1)[1]


def test_multiline_notes_keep_their_line_breaks():
    notes = "1. Mehr Humor\n2. Herr Novak ist mürrisch\n   (aber nett)"
    text = build_prompt(PromptOptions(notes=notes))
    assert notes in text


def test_ui_strings_for_a_source_language_without_labels():
    text = build_prompt(PromptOptions(source_lang="nl"))
    assert "## Page labels in Dutch" in text
    assert '"did_you_know": "Did you know?"' in text
    assert "## Page labels" not in build_prompt(PromptOptions(source_lang="fr",
                                                              target_lang="de"))
    assert set(locale.BUILTIN_LANGUAGES) >= {"en", "de", "fr"}


# ---------------------------------------------------------------------------
# Picture mode
# ---------------------------------------------------------------------------


def test_image_mode_builds_the_story_around_the_picture():
    raw = build_prompt(PromptOptions(source_lang="de", target_lang="fr", image=IMAGE))
    text = _flat(raw)
    assert "A picture is attached to this conversation." in text
    assert f'"image": "{IMAGE}"' in raw.splitlines()
    assert "fractions of the picture's width and height" in text
    assert '"x"' in text and '"y"' in text
    assert "0, 0 = top-left" in text
    assert "NO PICTURE ATTACHED" in text
    assert "A. Line drawing" not in text
    assert "Topic: derive it from the attached picture" in text


def test_image_mode_compact():
    raw = build_prompt(PromptOptions(image="photo.jpg", compact=True))
    assert "fractions of the" in _flat(raw)
    assert '"image": "photo.jpg"' in raw.splitlines()


def _image_line(prompt: str) -> str:
    lines = [line for line in prompt.splitlines() if line.startswith('"image": ')]
    assert len(lines) == 1, lines
    return lines[0]


@pytest.mark.parametrize("image", [
    "pictures/stall-at-the-mercado-central.jpg",
    "C:\\Users\\Jörn Maurischat\\Pictures\\Urlaub 2025\\IMG_2034.jpg",
    "/Users/joern/Library/Mobile Documents/com~apple~CloudDocs/Fotos/Wien Café  2.jpg",
    "Screenshot 2026-09-26 at 10.41.07\u202fAM.png",
    "https://example.org/photos/market%20stall.jpg",
])
@pytest.mark.parametrize("compact", [False, True])
def test_picture_path_is_valid_json_on_its_own_line(image: str, compact: bool):
    """The path is JSON-escaped (backslashes stay valid JSON) and printed on
    a line of its own, never re-wrapped or whitespace-normalised."""
    prompt = build_prompt(PromptOptions(image=image, compact=compact, topic="a market"))
    line = _image_line(prompt)
    assert line == '"image": ' + json.dumps(image, ensure_ascii=False)
    assert json.loads("{" + line + "}") == {"image": image}
    assert "\x1f" not in prompt


def test_picture_path_is_not_repeated_in_reflowed_prose():
    image = "My Photos/Holiday 2026 Valencia market/stall at the Mercado Central.png"
    prompt = build_prompt(PromptOptions(image=image))
    assert prompt.count(image) == 1
    assert "Pictures: built around the attached picture (see the picture section)" in _flat(prompt)


def test_drawn_picture_mode_offers_svg_or_draw_task(normal: str):
    assert "A. Line drawing" in normal and "B. No drawing" in normal
    assert "viewBox" in normal
    compact = build_prompt(PromptOptions(compact=True))
    assert "draw task" in compact and "no \"svg\"" in compact


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------


def test_continuation_mode(lena: Worksheet):
    text = _flat(build_prompt(PromptOptions(continue_from=lena)))
    assert "episode 2" in text
    assert '"episode": 2' in text
    assert '"id": "lena-in-wien"' in text
    for name in ("Lena", "Frau Berger", "Herr Novak"):
        assert name in text
    for cid in ('"lena"', '"berger"', '"novak"'):
        assert cid in text
    assert lena.series.next in text
    for word in lena.vocabulary.target:
        assert word in text
    assert "previously" in text
    assert _flat(lena.story.scenes[-1].text.split("\n\n")[0]) in text
    assert "episode 3" in text  # the new teaser


def test_continuation_with_an_explicit_level_uses_it():
    """Levelling up a series: an explicit level wins even when it equals the
    built-in default (B1), and so does an explicit source language ('en')."""
    valencia = load_worksheet(REPO / "examples" / "mercado_valencia_en_es.json")
    assert valencia.cefr_level == "A2"
    text = _flat(build_prompt(PromptOptions(continue_from=valencia, level="B1")))
    assert "Level: B1 (intermediate)" in text and "Use the **B1** row" in text
    assert "Level: A2" not in text
    assert "Level: A2" in build_prompt(PromptOptions(continue_from=valencia))
    lyon = load_worksheet(REPO / "examples" / "festival_lyon_de_fr.json")
    assert lyon.source_lang == "de"
    text = _flat(build_prompt(PromptOptions(continue_from=lyon, source_lang="en")))
    assert "an adult who speaks English and is learning French" in text


def test_from_legacy_with_an_explicit_default_level_uses_it():
    legacy = dict(LEGACY, cefr_level="A2")
    assert "Level: A2" in build_prompt(PromptOptions(from_legacy=legacy))
    text = _flat(build_prompt(PromptOptions(from_legacy=legacy, level="B1")))
    assert "Level: B1" in text and "Level: A2" not in text
    assert "this worksheet follows the brief (de → fr, B1)" in text


def test_resolve_options_precedence(lena: Worksheet):
    profile = {"source_lang": "fr", "target_lang": "es", "level": "A1", "frame": "diary"}
    assert resolve_options(PromptOptions()) == ResolvedOptions("en", "de", "B1", None)
    assert resolve_options(PromptOptions(profile=profile)) == ResolvedOptions(
        "fr", "es", "A1", "diary")
    # the legacy file beats the profile, the previous episode beats both
    assert resolve_options(PromptOptions(from_legacy=LEGACY, profile=profile)) == (
        ResolvedOptions("de", "fr", "B1", "diary"))
    assert resolve_options(PromptOptions(continue_from=lena, from_legacy=LEGACY,
                                         profile=profile)) == (
        ResolvedOptions("en", "de", "B1", "episode"))
    # explicit values beat everything, also when they equal the defaults
    assert resolve_options(PromptOptions(source_lang="EN", target_lang="de", level="b1",
                                         frame="mystery", continue_from=lena,
                                         profile=profile)) == (
        ResolvedOptions("en", "de", "B1", "mystery"))


def test_resolve_options_skips_unusable_file_values_but_rejects_explicit_ones():
    legacy = dict(LEGACY, source_lang="German", cefr_level="B3")
    profile = {"source_lang": "nl", "level": "Z9", "frame": "saga"}
    assert resolve_options(PromptOptions(from_legacy=legacy, profile=profile)) == (
        ResolvedOptions("nl", "fr", "B1", None))
    with pytest.raises(ValueError, match="language code"):
        resolve_options(PromptOptions(target_lang="German"))
    with pytest.raises(ValueError, match="CEFR"):
        resolve_options(PromptOptions(level="B3"))


def test_continuation_takes_languages_from_the_previous_episode():
    data = json.loads(LENA.read_text(encoding="utf-8"))
    data.update(source_lang="fr", cefr_level="A2")
    prev = worksheet_from_dict(data)
    text = build_prompt(PromptOptions(continue_from=prev))
    assert "French (fr)" in text and "Level: A2" in text
    text = build_prompt(PromptOptions(continue_from=prev, level="B2"))
    assert "Level: B2" in text


def test_first_episode_of_a_new_series():
    text = _flat(build_prompt(PromptOptions(frame="episode", topic="Kaffee")))
    assert "This is episode 1 of a series" in text
    assert '"episode": 1, "next"' in text
    assert "teaser for episode 2" in text
    assert "kaffee-series" in text
    assert "episode 1 of a series" not in build_prompt(PromptOptions(frame="mystery"))


# ---------------------------------------------------------------------------
# From text / from a langwich 2 file
# ---------------------------------------------------------------------------


def test_from_text_embeds_the_text():
    source = "Die Brezel ist ein Gebäck.\n\n```\nSie wird in Lauge getaucht.\n```"
    text = build_prompt(PromptOptions(from_text=source))
    assert "Build on the text in the Material section" in text
    assert "Sie wird in Lauge getaucht." in text
    assert "````text" in text  # the fence grows past the backticks in the text


def test_from_legacy_reuses_languages_and_topic():
    legacy = LEGACY
    text = _flat(build_prompt(PromptOptions(from_legacy=legacy)))
    assert "German (de)" in text and "French (fr)" in text
    assert "Topic: cinema" in text
    assert "Upgrade the langwich 2 file" in text
    assert "Le cinéma est né en France" in text
    assert '"exercises"' not in text
    explicit = _flat(build_prompt(PromptOptions(from_legacy=legacy, level="B2")))
    assert "Level: B2" in explicit
    assert "this worksheet follows the brief" in explicit


# ---------------------------------------------------------------------------
# Compact
# ---------------------------------------------------------------------------


def test_compact_is_shorter_and_keeps_the_contract():
    for opts in (dict(), dict(target_lang="es", level="A2"), dict(image="p.jpg")):
        normal = build_prompt(PromptOptions(**opts))
        compact = build_prompt(PromptOptions(compact=True, **opts))
        assert len(compact) < 0.6 * len(normal)
        for kind in TASK_KINDS:
            assert re.search(rf"(?m)^{kind} +\S", compact), kind
        assert "Reply with the JSON object only" in compact
        assert "Keep sentences simple" in compact
        assert "3 scenes" in compact


def test_prompt_sizes_stay_reasonable(lena: Worksheet):
    assert len(build_prompt(PromptOptions(topic="bread", frame="reportage"))) < 28_000
    assert len(build_prompt(PromptOptions(continue_from=lena))) < 31_000
    assert len(build_prompt(PromptOptions(compact=True, target_lang="es", level="A2"))) < 14_000


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Issue:
    level: str
    code: str
    where: str
    message: str


@dataclass
class _Report:
    issues: list


def test_repair_prompt_lists_issues_and_the_json():
    report = _Report([
        _Issue("error", "unknown-scene", "/tasks/5/scene", "there is no scene with id 's9'."),
        _Issue("warning", "no-facts", "/facts", "the worksheet has no facts."),
    ])
    json_text = json.dumps(MINI_EXAMPLE, ensure_ascii=False)
    text = repair_prompt(report, json_text)
    assert "/tasks/5/scene" in text and "[unknown-scene]" in text and "'s9'" in text
    assert "/facts" in text and "no facts" in text
    assert text.index("## Errors") < text.index("## Warnings") < text.index("## The JSON")
    assert json_text in text
    assert "errors must be fixed" in text.lower()
    assert "Field reference" not in text


def test_repair_prompt_adds_the_reference_for_contract_errors():
    report = _Report([_Issue("error", "contract", "/tasks/0/pairz",
                             "'pairz' is not a field here")])
    text = repair_prompt(report, '{"source_lang": "de", "target_lang": "fr", "tasks": []}')
    assert "## Field reference" in text
    assert "text in French" in text and "text in German" in text
    broken = repair_prompt(report, "{not json")
    assert "## Field reference" in broken and "{not json" in broken


def test_repair_prompt_with_a_real_report(tmp_path: Path):
    validate = pytest.importorskip("langwich.validate")
    data = json.loads(json.dumps(MINI_EXAMPLE))
    data["tasks"][3]["items"][0] = "Im Watt {{müsst}} ihr immer bei der Gruppe bleiben."
    data["vocabulary"]["target"].append("der Hafen")
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    report = validate.check_file(path)
    assert not report.ok
    text = repair_prompt(report, path.read_text(encoding="utf-8"))
    for issue in report.issues:
        assert issue.where in text
    assert "der Hafen" in text


def test_series_switch_overrides_the_frame_default():
    from langwich.prompt import PromptOptions, build_prompt

    mystery_series = build_prompt(PromptOptions(topic="film", frame="mystery", series=True))
    plain_mystery = build_prompt(PromptOptions(topic="film", frame="mystery"))
    episode_without = build_prompt(PromptOptions(topic="tea", frame="episode", series=False))
    episode_default = build_prompt(PromptOptions(topic="tea", frame="episode"))
    marker = "film-series"
    assert marker in mystery_series and marker not in plain_mystery
    assert "tea-series" in episode_default and "tea-series" not in episode_without


# ---------------------------------------------------------------------------
# Wording that must agree with the validator, the planner and the renderer
# ---------------------------------------------------------------------------


def test_example_grammar_box_shows_the_pattern_with_other_verbs():
    """The prompt's rule — the box beside a task never shows its answers — holds
    for its own example: the table conjugates other modal verbs."""
    grammar = {g["id"]: g for g in MINI_EXAMPLE["grammar"]}
    cells = {c.casefold() for g in grammar.values() for row in g["table"]["rows"] for c in row}
    boxed = [t for t in MINI_EXAMPLE["tasks"] if t.get("grammar")]
    assert boxed
    for task in boxed:
        answers = re.findall(r"\{\{([^}|:]+)", " ".join(task.get("items") or [task.get("text")]))
        assert answers
        assert not {a.casefold() for a in answers} & cells, task["id"]
    flat = _flat(build_prompt(PromptOptions()))
    assert "It may show the same pattern with OTHER words" in flat
    assert "never show that task's answers" in flat


@pytest.mark.parametrize("compact", [False, True])
def test_prompt_says_langwich_prints_the_word_range(compact: bool):
    flat = _flat(build_prompt(PromptOptions(compact=compact)))
    assert "langwich prints the word range" in flat
    assert "don't repeat" in flat


def test_forms_are_required_for_irregular_separable_and_reflexive_verbs():
    de = _flat(build_prompt(PromptOptions()))
    assert '"forms" is REQUIRED for every irregular, separable and reflexive verb' in de
    assert '"anziehen": "zieht an, zog an, hat angezogen"' in de
    fr = _flat(build_prompt(PromptOptions(target_lang="fr")))
    assert '"forms" is REQUIRED for every irregular and reflexive verb' in fr
    en = _flat(build_prompt(PromptOptions(source_lang="de", target_lang="en")))
    assert '"forms" is REQUIRED for every irregular verb' in en and "separable" not in en


def test_label_word_box_and_articles_follow_the_target_language():
    de = _flat(build_prompt(PromptOptions()))
    assert "word box shows the terms without their articles" in de
    assert '"with der, die or das"' in de
    assert "Nouns with article and plural" in de
    en = _flat(build_prompt(PromptOptions(source_lang="de", target_lang="en")))
    for phrase in ("with article", "with its article", "Nouns with their", "if English has them",
                   "word box shows the terms without their articles"):
        assert phrase not in en, phrase
    assert "Nouns without an article, as an English word list gives them" in en
    assert '"term" in T without an article' in en
    en_photo = _flat(build_prompt(PromptOptions(source_lang="de", target_lang="en",
                                                image="pictures/p.jpg")))
    assert "with article" not in en_photo and "with its article" not in en_photo
    en_compact = _flat(build_prompt(PromptOptions(source_lang="de", target_lang="en",
                                                  image="pictures/p.jpg", compact=True)))
    assert "with article" not in en_compact


def test_dialogue_word_boxes_have_distractors():
    assert '"distractors": [T]?' in KIND_FIELDS["dialogue"]
    flat = _flat(build_prompt(PromptOptions()))
    assert 'a dialogue with "bank": true' in flat
    assert "the last gap is not free by elimination" in flat


@pytest.mark.parametrize("opts", [
    PromptOptions(level="A1"), PromptOptions(level="A2", compact=True),
    PromptOptions(source_lang="de", target_lang="it"), PromptOptions(target_lang="en"),
    PromptOptions(source_lang="en", target_lang="es", level="A2", scenes=2),
], ids=["A1", "A2-compact", "it", "en", "es-2-scenes"])
def test_no_template_grammar_slips(opts: PromptOptions):
    text = _flat(build_prompt(opts))
    assert not re.search(r"\ba (A1|A2|English|Italian|Arabic)\b", text)
    assert not re.search(r"\b1 scenes\b", text)
    assert "section below asks" not in text
    assert "Frau Berger" not in text and "lena-in-wien" not in text


def test_articles_before_level_and_language():
    a2 = _flat(build_prompt(PromptOptions(level="A2", target_lang="it", source_lang="de")))
    assert "that an A2 learner may not know" in a2
    assert "find an Italian video" in a2
    b1 = _flat(build_prompt(PromptOptions(level="B1")))
    assert "that a B1 learner may not know" in b1 and "find a German video" in b1


@pytest.mark.parametrize("scenes", [1, 8, 12])
def test_scene_count_outside_the_validator_range_is_rejected(scenes: int):
    with pytest.raises(ValueError, match="between 2 and 7"):
        build_prompt(PromptOptions(scenes=scenes))


def test_scene_range_matches_the_validator():
    validate = pytest.importorskip("langwich.validate")
    assert (validate.SCENES_MIN, validate.SCENES_MAX) == (2, 7)
    assert "2 scenes" in build_prompt(PromptOptions(scenes=2))
    assert "7 scenes" in build_prompt(PromptOptions(scenes=7))


def test_example_heading_names_the_learner_languages():
    es = _flat(build_prompt(PromptOptions(target_lang="es", level="A2")))
    assert "It is English → German; yours is English → Spanish" in es
    de = _flat(build_prompt(PromptOptions()))
    assert "It has the same languages as yours" in de


def test_lesson_arc_puts_pictures_after_comprehension():
    flat = _flat(build_prompt(PromptOptions()))
    assert "sorted gist → detail → picture → form → practice" in flat
    assert "every gist, detail, picture, form and practice task has a \"scene\"" in flat
    assert flat.index("4. picture:") < flat.index("5. form:") < flat.index("6. practice:")
    compact = _flat(build_prompt(PromptOptions(compact=True)))
    assert compact.index("3. picture:") < compact.index("4. form:")
    assert "stage: " + " | ".join(STAGES) in build_prompt(PromptOptions())


def test_no_picture_sentinel_comes_from_the_model():
    from langwich.model import NO_PICTURE_SENTINEL

    for compact in (False, True):
        text = build_prompt(PromptOptions(image="pictures/p.jpg", compact=compact))
        assert f"reply only with: {NO_PICTURE_SENTINEL}" in _flat(text) or (
            f"reply only: {NO_PICTURE_SENTINEL}" in _flat(text))


# ---------------------------------------------------------------------------
# Repair: what an LLM cannot fix stays out
# ---------------------------------------------------------------------------


def test_repair_prompt_leaves_out_environment_issues():
    report = _Report([
        _Issue("error", "image-not-found", "/story/scenes/1/picture/image",
               "the picture file pictures/stall.jpg was not found."),
        _Issue("warning", "image-unreadable", "/story/scenes/2/picture/image",
               "HEIC without pillow-heif."),
        _Issue("warning", "no-facts", "/facts", "the worksheet has no facts."),
    ])
    text = repair_prompt(report, json.dumps(MINI_EXAMPLE, ensure_ascii=False))
    assert "no-facts" in text
    assert "image-not-found" not in text and "image-unreadable" not in text
    assert "## Errors" not in text


def test_repair_prompt_refuses_the_no_picture_reply():
    report = _Report([_Issue("error", "no-picture-attached", "/",
                             "the file contains only the reply 'NO PICTURE ATTACHED'")])
    with pytest.raises(ValueError, match="NO PICTURE ATTACHED"):
        repair_prompt(report, "NO PICTURE ATTACHED")


def test_repair_prompt_reads_languages_from_wrapped_json():
    report = _Report([_Issue("error", "contract", "/tasks/0/pairz", "not a field")])
    wrapped = ("Here is your worksheet:\n\n```json\n"
               '{"schema": "langwich/3", "source_lang": "de", "target_lang": "fr", '
               '"tasks": []}\n```\nEnjoy!')
    text = repair_prompt(report, wrapped)
    assert "text in French" in text and "text in German" in text
