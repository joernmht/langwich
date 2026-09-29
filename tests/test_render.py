"""The renderer: HTML + print CSS + PDF for langwich/3 worksheets."""

from __future__ import annotations

import base64
import copy
import importlib.util
import io
import json
import os
import re
import sys
from pathlib import Path

import pytest

from langwich.answers import answer_key
from langwich.images import prepare_picture
from langwich.model import TASK_KINDS, MatchTask, Picture, load_worksheet, worksheet_from_dict
from langwich.plan import plan, strip_article
from langwich.plan import tested_terms as collect_tested_terms
from langwich.render import RenderOptions, build_html, render_worksheet
from langwich.validate import validate

ROOT = Path(__file__).resolve().parent.parent
LENA = ROOT / "examples" / "lena_01_en_de.json"
FESTIVAL = ROOT / "examples" / "festival_lyon_de_fr.json"
CAFE_SVG = ROOT / "examples" / "pictures" / "cafe_lindner.svg"
SHOWCASE = ROOT / "tests" / "fixtures" / "kinds_showcase.json"
EXAMPLES = sorted((ROOT / "examples").glob("*.json")) + [SHOWCASE]

MM = 72 / 25.4
NBSP = "\u00a0"

#: CI sets LANGWICH_REQUIRE_PDF=1: the PDF tests must run there, so a missing
#: WeasyPrint or pymupdf is a failure instead of a skip.
REQUIRE_PDF = os.environ.get("LANGWICH_REQUIRE_PDF", "").strip() not in ("", "0")


def _has_weasyprint() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def need_pdf(pymupdf: bool = False):
    """Skip when WeasyPrint (and, if asked, pymupdf) is missing — or fail
    when LANGWICH_REQUIRE_PDF=1. Returns the pymupdf module when asked."""
    missing = []
    if not _has_weasyprint():
        missing.append("WeasyPrint")
    if pymupdf and importlib.util.find_spec("pymupdf") is None:
        missing.append("pymupdf")
    if missing:
        reason = f"{' and '.join(missing)} not available"
        if REQUIRE_PDF:
            pytest.fail(f"{reason}, but LANGWICH_REQUIRE_PDF is set")
        pytest.skip(reason)
    if pymupdf:
        import pymupdf as module

        return module
    return None


@pytest.fixture
def weasy():
    """For tests that write a PDF."""
    need_pdf()


@pytest.fixture
def fitz():
    """For tests that read a PDF back (WeasyPrint + pymupdf)."""
    return need_pdf(pymupdf=True)


def _lena() -> dict:
    return json.loads(LENA.read_text(encoding="utf-8"))


def _showcase() -> dict:
    return json.loads(SHOWCASE.read_text(encoding="utf-8"))


def _body(html: str) -> str:
    """The <body> without HTML comments."""
    body = html.split("<body>", 1)[1]
    return re.sub(r"<!--.*?-->", "", body, flags=re.S)


def _text(html_fragment: str) -> str:
    return re.sub(r"<[^>]+>", "", html_fragment)


def _number(ws, task_id: str) -> int:
    return next(pt.number for pt in plan(ws).tasks if pt.task.id == task_id)


def _task_section(html: str, number: int) -> str:
    """The <section> of task ``number`` (with its opening tag)."""
    m = re.search(rf'<section class="task unit [^"]*" id="task-{number}"[^>]*>.*?</section>', html,
                  flags=re.S)
    assert m, f"task {number} not found"
    return m.group(0)


# ---------------------------------------------------------------------------
# The reference example, rendered once to PDF
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lena_pdf(tmp_path_factory):
    need_pdf()
    out = tmp_path_factory.mktemp("lena") / "lena.pdf"
    ws = load_worksheet(LENA)
    result = render_worksheet(ws, out, RenderOptions(base_dir=LENA.parent))
    return ws, result


def test_lena_renders_to_pdf_and_html(lena_pdf):
    _, result = lena_pdf
    assert result.pdf is not None and result.pdf.exists()
    assert result.html.exists() and result.html.suffix == ".html"
    assert result.pages and result.pages >= 6
    assert result.weasyprint_error is None
    assert result.warnings == []
    assert result.solutions_pdf is None


def test_lena_pdf_embeds_only_the_bundled_fonts(lena_pdf, fitz):
    pymupdf = fitz
    _, result = lena_pdf
    doc = pymupdf.open(result.pdf)
    fonts = {f[3].split("+", 1)[-1] for page in doc for f in page.get_fonts()}
    assert fonts, "no fonts embedded"
    assert all(f.startswith(("Literata", "Atkinson-Hyperlegible-Next")) for f in fonts), fonts
    assert any(f.startswith("Literata") for f in fonts)
    assert any(f.startswith("Atkinson") for f in fonts)


def test_lena_pdf_text_stays_inside_the_page(lena_pdf, fitz):
    pymupdf = fitz
    _, result = lena_pdf
    doc = pymupdf.open(result.pdf)
    left, right = 20 * MM, 12 * MM
    for number, page in enumerate(doc, 1):
        width = page.rect.width
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if not span["text"].strip():
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    assert x0 >= left - 2 and x1 <= width - right + 2, (number, span["text"])
                    assert y0 >= 0 and y1 <= page.rect.height, (number, span["text"])


def test_lena_image_prompt_is_never_printed(lena_pdf, fitz):
    pymupdf = fitz
    ws, result = lena_pdf
    prompt = ws.scene("s4").picture.prompt
    html = result.html.read_text(encoding="utf-8")
    assert prompt[:40] not in _body(html)
    assert "image prompt" in html  # kept as an HTML comment for the author
    pdf_text = " ".join(page.get_text() for page in pymupdf.open(result.pdf))
    assert "Black-and-white line drawing" not in pdf_text
    # the café picture has an svg, so it is not reported as "needs a picture"
    assert result.image_prompts == []


def test_lena_glosses_never_give_away_tested_words(lena_pdf):
    ws, result = lena_pdf
    html = result.html.read_text(encoding="utf-8")
    gloss_terms = re.findall(r'<div class="gls">(.*?)</div></div>', html, flags=re.S)
    terms = [strip_article(_text(t)).casefold()
             for block in gloss_terms for t in re.findall(r"<b [^>]*>(.*?)</b>", block)]
    assert terms, "the story has glosses"
    tested = collect_tested_terms(ws)
    targets = {strip_article(t).casefold() for t in ws.vocabulary.target}
    for term in terms:
        assert term not in targets
        assert term not in tested


def test_lena_solutions_and_translations_are_appended(lena_pdf, fitz):
    pymupdf = fitz
    ws, result = lena_pdf
    html = result.html.read_text(encoding="utf-8")
    p = plan(ws)
    assert html.count('<div class="sb">') == len(p.tasks)
    match = next(pt for pt in p.tasks if isinstance(pt.task, MatchTask))
    key = answer_key(match, ws)
    # a non-breaking space keeps each number with its answer
    assert " · ".join(f"{i}{NBSP}{k}" for i, k in enumerate(key, 1)) in _text(html)
    pdf_text = " ".join(page.get_text() for page in pymupdf.open(result.pdf))
    assert "Solutions" in pdf_text and "Translation" in pdf_text
    assert "It's Monday, seven o'clock" in pdf_text


def test_lena_route_lists_every_task_and_the_reading(lena_pdf):
    ws, result = lena_pdf
    html = result.html.read_text(encoding="utf-8")
    route = re.search(r'<nav class="route">(.*?)</nav>', html, flags=re.S).group(1)
    numbers = re.findall(r'<span class="rn">(\d+)</span>', route)
    assert numbers == [str(i) for i in range(1, len(ws.tasks) + 1)]
    for task in ws.tasks:
        assert _text(route).count(task.title.replace("'", "&#x27;")) >= 1
    assert route.count('class="read"') == len(ws.story.scenes)


def test_lena_picture_markers_follow_the_labels():
    ws = load_worksheet(LENA)
    html = build_html(ws, RenderOptions(base_dir=LENA.parent))
    figure = re.search(r'<figure class="fig" .*?</figure>', html, flags=re.S).group(0)
    markers = re.findall(r'<span class="mk" style="left:([\d.]+)mm;top:([\d.]+)mm">(\d+)</span>',
                         figure)
    labels = {lb.n: lb for lb in ws.scene("s4").picture.labels}
    assert [int(n) for _, _, n in markers] == sorted(labels)
    pic = re.search(r'<div class="pic" style="width:([\d.]+)mm;height:([\d.]+)mm">', figure)
    width, height = float(pic.group(1)), float(pic.group(2))
    assert width == pytest.approx(178 - 0.71, abs=0.05)
    assert height / width == pytest.approx(92 / 178, rel=0.01)  # the svg viewBox ratio
    off = 3 + 0.35  # radius + white ring: the disc's centre is the label position
    for left, top, n in markers:
        lb = labels[int(n)]
        assert float(left) + off == pytest.approx(min(max(lb.x * width, 3), width - 3), abs=0.02)
        assert float(top) + off == pytest.approx(min(max(lb.y * height, 3), height - 3), abs=0.02)


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def test_same_worksheet_and_seed_give_identical_html():
    ws = load_worksheet(SHOWCASE)
    opts = RenderOptions(base_dir=SHOWCASE.parent)
    assert build_html(ws, opts) == build_html(load_worksheet(SHOWCASE), opts)
    seeded = RenderOptions(seed=7)
    assert build_html(ws, seeded) == build_html(ws, RenderOptions(seed=7))


def test_separate_solutions_write_a_second_pdf(tmp_path, weasy):
    ws = load_worksheet(LENA)
    result = render_worksheet(ws, tmp_path / "lena.pdf", RenderOptions(solutions="separate"))
    assert result.pdf.exists()
    assert result.solutions_pdf == tmp_path / "lena-solutions.pdf"
    assert result.solutions_pdf.exists()
    assert (tmp_path / "lena-solutions.html").exists()
    main_html = result.html.read_text(encoding="utf-8")
    sol_html = (tmp_path / "lena-solutions.html").read_text(encoding="utf-8")
    assert 'class="solutions' not in main_html
    assert 'class="solutions' in sol_html and 'class="cover"' not in sol_html


def test_no_solutions_leaves_out_the_answer_section(tmp_path):
    ws = load_worksheet(LENA)
    result = render_worksheet(ws, tmp_path / "lena.pdf",
                              RenderOptions(solutions="none", html_only=True))
    html = result.html.read_text(encoding="utf-8")
    assert result.pdf is None and result.solutions_pdf is None
    assert 'class="solutions' not in html
    assert "trans-sec" not in html
    assert not (tmp_path / "lena-solutions.pdf").exists()
    assert "Word list" in html  # the back matter stays


def test_translations_can_be_left_out():
    ws = load_worksheet(LENA)
    assert "trans-sec" in build_html(ws)
    assert "trans-sec" not in build_html(ws, RenderOptions(translations=False))


def test_epaper_page_size(tmp_path, fitz):
    pymupdf = fitz
    ws = load_worksheet(SHOWCASE)
    result = render_worksheet(ws, tmp_path / "ep.pdf",
                              RenderOptions(page="epaper", base_dir=SHOWCASE.parent))
    doc = pymupdf.open(result.pdf)
    for page in doc:
        assert page.rect.width == pytest.approx(157.8 * MM, abs=0.5)
        assert page.rect.height == pytest.approx(210.4 * MM, abs=0.5)
    assert result.pages == len(doc)


def test_one_task_per_page_adds_pages(tmp_path, weasy):
    ws = load_worksheet(LENA)
    flowing = render_worksheet(ws, tmp_path / "a.pdf", RenderOptions(solutions="none"))
    single = render_worksheet(ws, tmp_path / "b.pdf",
                              RenderOptions(solutions="none", one_task_per_page=True))
    assert single.pages >= len(ws.tasks) > flowing.pages
    assert 'class="page-a4 otp"' in single.html.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------


def test_label_task_without_a_visual_becomes_draw_and_label():
    ws = load_worksheet(SHOWCASE)
    html = build_html(ws, RenderOptions(base_dir=SHOWCASE.parent))
    section = _task_section(html, _number(ws, "t6"))
    assert "Zeichne die Szene" in section and "Perdus dans la traboule" in section
    assert 'class="frame"' in section and 'class="mk"' not in section
    assert "l&#x27;escalier" in section and "le chien" in section  # terms as a word box
    p = plan(ws)
    fallback = next(pt for pt in p.tasks if pt.task.id == "t6")
    assert answer_key(fallback, ws) == []


def test_pictures_without_a_visual_report_their_prompt(tmp_path):
    ws = load_worksheet(SHOWCASE)
    result = render_worksheet(ws, tmp_path / "k.pdf", RenderOptions(html_only=True))
    assert [sid for sid, _ in result.image_prompts] == ["s2"]
    assert result.image_prompts[0][1] not in _body(result.html.read_text(encoding="utf-8"))


def test_missing_image_file_is_a_warning_not_a_crash(tmp_path):
    data = _lena()
    pic = data["story"]["scenes"][3]["picture"]
    pic.pop("svg")
    pic["image"] = "pictures/does_not_exist.png"
    ws = worksheet_from_dict(data)
    result = render_worksheet(ws, tmp_path / "x.pdf",
                              RenderOptions(base_dir=tmp_path, html_only=True))
    assert any("not found" in w for w in result.warnings)
    html = result.html.read_text(encoding="utf-8")
    assert "data:image" not in html
    assert "Draw the scene" in html  # the label task falls back to drawing
    assert result.image_prompts == [("s4", pic["prompt"])]


@pytest.mark.parametrize("payload", [b"not an image at all", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, b""])
def test_invalid_image_bytes_are_a_warning_not_a_crash(tmp_path, payload):
    (tmp_path / "broken.png").write_bytes(payload)
    warnings: list[str] = []
    assert prepare_picture(Picture(image="broken.png"), tmp_path, True, warnings) is None
    assert warnings
    data = _lena()
    pic = data["story"]["scenes"][3]["picture"]
    pic.pop("svg")
    pic["image"] = "broken.png"
    html = build_html(worksheet_from_dict(data), RenderOptions(base_dir=tmp_path))
    assert "Draw the scene" in html


def test_invalid_svg_is_a_warning_not_a_crash():
    warnings: list[str] = []
    assert prepare_picture(Picture(svg="<svg><g></svg>"), None, True, warnings) is None
    assert warnings and "not valid XML" in warnings[0]


def test_svg_file_path_image_is_embedded_as_vector(tmp_path):
    (tmp_path / "pics").mkdir()
    (tmp_path / "pics" / "cafe.svg").write_text(CAFE_SVG.read_text(encoding="utf-8"), encoding="utf-8")
    data = _lena()
    pic = data["story"]["scenes"][3]["picture"]
    pic.pop("svg")
    pic["image"] = "pics/cafe.svg"
    ws = worksheet_from_dict(data)
    warnings: list[str] = []
    prepared = prepare_picture(ws.scene("s4").picture, tmp_path, True, warnings)
    assert warnings == []
    assert prepared.is_vector and prepared.data_uri.startswith("data:image/svg+xml;base64,")
    assert prepared.height / prepared.width == pytest.approx(92 / 178, rel=0.01)
    html = build_html(ws, RenderOptions(base_dir=tmp_path))
    assert html.count('class="mk"') == 6


def test_svg_without_namespace_gets_one():
    warnings: list[str] = []
    prepared = prepare_picture(
        Picture(svg='```svg\n<svg viewBox="0 0 40 30"><rect width="10" height="10"/></svg>\n```'),
        None, True, warnings)
    assert warnings == []
    svg = base64.b64decode(prepared.data_uri.split(",", 1)[1]).decode()
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"') and svg.endswith("</svg>")
    assert (prepared.width, prepared.height) == (1000, 750)


def test_raster_images_become_high_contrast_greyscale(tmp_path):
    PIL = pytest.importorskip("PIL.Image")
    img = PIL.new("RGB", (40, 20), (200, 120, 40))
    img.paste((20, 60, 180), (0, 0, 20, 20))
    img.save(tmp_path / "photo.png")
    warnings: list[str] = []
    mono = prepare_picture(Picture(image="photo.png"), tmp_path, True, warnings)
    colour = prepare_picture(Picture(image=str(tmp_path / "photo.png")), None, False, warnings)
    assert warnings == []
    assert (mono.width, mono.height) == (40, 20) and not mono.is_vector
    decoded = PIL.open(io.BytesIO(base64.b64decode(mono.data_uri.split(",", 1)[1])))
    assert decoded.mode == "L"
    assert decoded.getextrema() == (0, 255)  # autocontrast stretches to black and white
    assert PIL.open(io.BytesIO(base64.b64decode(colour.data_uri.split(",", 1)[1]))).mode == "RGB"


def test_picture_without_a_picture_task_follows_the_scene_text():
    data = _lena()
    data["tasks"] = [t for t in data["tasks"] if t["id"] not in ("t9", "t10")]
    html = build_html(worksheet_from_dict(data))
    scene = re.search(r'<section class="scene unit" id="scene-s4">(.*?)</section>', html,
                      flags=re.S).group(1)
    assert 'class="scene-fig"' in scene and scene.count('class="mk"') == 6
    assert html.count('<figure class="fig"') == 1


def test_picture_sits_in_its_label_task():
    ws = load_worksheet(LENA)
    html = build_html(ws)
    label = _task_section(html, _number(ws, "t9"))
    assert '<figure class="fig" ' in label and 'class="name-grid"' in label
    assert html.count('<figure class="fig" ') == 1  # one full-size picture


def test_sidebars_without_room_move_into_a_band_below_the_scene():
    data = _showcase()
    first = data["story"]["scenes"][0]
    first["text"] = first["text"].split("\n\n")[1]
    long_text = "Les canuts travaillaient sur des métiers à tisser Jacquard. " * 6
    data["facts"] += [{"scene": "s1", "title": f"Fait {i}", "text": long_text} for i in range(4)]
    html = build_html(worksheet_from_dict(data))
    scene = re.search(r'id="scene-s1">(.*?)</section>', html, flags=re.S).group(1)
    band = scene.split('<div class="notes-band n3">', 1)[1]
    assert band.count('class="fact"') >= 3
    assert scene.count('class="fact"') == 5  # nothing is dropped
    epaper = build_html(worksheet_from_dict(data), RenderOptions(page="epaper"))
    assert '<div class="notes-band' not in epaper  # one column: notes follow the text


# ---------------------------------------------------------------------------
# Content and language
# ---------------------------------------------------------------------------


def test_the_showcase_warns_only_where_it_means_to():
    """The showcase is checked like any worksheet and departs from the brief
    only where the tests need it to: the picture of scene 2 has labels but
    no drawing, so its label task t6 is printed as 'draw and label' (see
    test_label_task_without_a_visual_becomes_draw_and_label), and it holds a
    task of every kind — far more tasks than an A2 sheet should have."""
    report = validate(load_worksheet(SHOWCASE), SHOWCASE.parent)
    assert sorted((i.code, i.where) for i in report.issues) == [
        ("label-draws-instead", "/tasks/5"), ("task-count", "/tasks"),
    ]


def test_every_kind_is_rendered():
    """Every task kind, and the optional fields of the kinds, each with its
    own markup."""
    ws = load_worksheet(SHOWCASE)
    html = build_html(ws, RenderOptions(base_dir=SHOWCASE.parent))
    assert {t.kind for t in ws.tasks} == set(TASK_KINDS)
    for kind in TASK_KINDS:
        assert f"k-{kind}" in html, kind

    def section(task_id: str) -> str:
        return _task_section(html, _number(ws, task_id))

    assert 'class="dlg"' in html and 'class="search"' in html and 'class="wbi"' in html
    assert 'class="cls grid"' in section("t21")  # classify: a tick box per row and column
    assert section("t16").count('<p class="q src"') == 5  # find_in_text: German clues
    assert section("t18").count('class="tile"') == 5 + 3 + 5 + 6  # scramble: word tiles
    assert 'class="gts"' in section("t20")  # gapped_text: the lettered sentences
    table = section("t24")
    assert 'class="gtab tl"' in table and table.count('class="open"') == 2  # open cells
    assert 'class="draft tl"' in section("t25")  # proofread: the draft in a box
    assert 'class="cwg"' in section("t27")  # crossword: the grid
    # the kinds' optional fields
    tf = section("t22")  # not_given: a third box; justify: a line for the words
    assert 'class="tf3 just"' in tf and tf.count('class="wl evd"') == 5
    writing = section("t13")  # a message to answer, its points, who it is for
    for marker in ('class="box input tl"', 'class="points"', 'class="wmeta"', 'class="reg"'):
        assert marker in writing, marker
    assert section("t23").count('class="choice"') == 4  # cloze choice, options inline
    assert section("t19").count('class="chr"') == 4  # cloze choice, options below
    transform = section("t17")  # key words and a word limit
    assert transform.count('class="kw"') == 4 and 'class="len"' in transform
    assert section("t9").count('class="starter tl"') == 3  # starters on the answer lines
    assert section("t26").count('<p class="q src"') == 2  # question_lang: source
    # a blank for every gap the learner writes in; inline choices print their
    # options instead, the proofread draft its mistakes
    blanks = {pt.task.id: _task_section(html, pt.number).count('class="blank"')
              for pt in plan(ws).tasks}
    assert {task_id: n for task_id, n in blanks.items() if n} == {
        "t4": 4, "t8": 4, "t10": 4,  # word-bank passage, first-letter items, dialogue
        "t17": 4,  # the frames of the key word transformations
        "t19": 4,  # the numbered choice gaps above their options
        "t20": 4,  # gapped text: a box for the letter of each removed sentence
        "t24": 5,  # the table's gaps (its open cells get writing lines)
    }


def test_user_text_is_escaped():
    data = _lena()
    data["title"] = "<Hinweis> & Łódź"
    data["story"]["scenes"][0]["heading"] = 'Montag <script>alert("x")</script>'
    data["tasks"][0]["title"] = "Words & <more>"
    html = build_html(worksheet_from_dict(data))
    body = _body(html)
    assert "&lt;Hinweis&gt; &amp; Łódź" in body
    assert "<Hinweis>" not in html
    assert "<script>" not in html
    assert "Words &amp; &lt;more&gt;" in body
    assert "<title>&lt;Hinweis&gt; &amp; Łódź</title>" in html


def test_german_learners_get_german_furniture():
    ws = load_worksheet(SHOWCASE)
    html = build_html(ws, RenderOptions(base_dir=SHOWCASE.parent))
    body = _text(_body(html))
    for phrase in ("Bevor du liest", "Szene 1", "Jetzt du", "Weiter geht’s", "Wortliste",
                   "Lösungen", "Wusstest du?", "Was bisher geschah", "Nächstes Mal", "Dein Weg",
                   "Personen", "Wortkasten", "richtig", "falsch", "Übersetzung", "Folge 2",
                   "Deutsch → Français · A2", "Nomen", "Verben", "Suche nach"):
        assert phrase in body, phrase
    assert '<html lang="de"' in html and 'lang="fr"' in html
    assert "Before you read" not in body


def test_ui_overrides_serve_other_source_languages():
    data = _lena()
    data["source_lang"] = "nl"
    data["ui"] = {"phase.before": "Voor het lezen", "solutions": "Oplossingen",
                  "pos.noun": "Zelfstandige naamwoorden"}
    html = build_html(worksheet_from_dict(data))
    body = _text(_body(html))
    assert "Voor het lezen" in body and "Oplossingen" in body
    assert "Zelfstandige naamwoorden" in body
    assert "Nederlands → Deutsch · B1" in body
    assert "Word list" in body  # no override: English fallback


def test_broken_ui_override_falls_back_instead_of_crashing():
    data = _showcase()
    data["ui"] = {"kind.label.draw": "Zeichne {Szene}", "kind.writing.length": "{min} bis {oops}"}
    ws = worksheet_from_dict(data)
    result_html = build_html(ws)
    assert "Zeichne die Szene" in result_html and "Schreibe 40–60 Wörter." in result_html


def test_series_previously_teaser_and_characters_on_the_page():
    html = build_html(load_worksheet(SHOWCASE))
    body = _text(_body(html))
    assert "Mila à Lyon · Folge 2" in body
    assert "Mila, une étudiante autrichienne" in body
    assert "Mila à Lyon · Folge 3" in body and "Fête des Lumières" in body
    assert "Madame Roux" in body and "ihr Mitbewohner, studiert Kochen" in body
    # the colon in the title becomes a line break on the cover
    assert "Mila à Lyon :<br>Un samedi à la Croix-Rousse" in html


def test_writing_task_gets_length_line_and_sized_lines():
    data = _showcase()
    html = build_html(worksheet_from_dict(data))
    section = re.search(r'<section class="task unit k-writing[^"]*".*?</section>', html,
                        flags=re.S).group(0)
    assert "Schreibe 40–60 Wörter." in section
    assert 'class="starter tl"' in section
    assert section.count("<div></div>") + 1 == 6 + 1  # 60 words ≈ 6 lines, plus the starter line
    assert "le chemin" in section and "Verwende diese Wörter:" in section


def test_blanks_share_the_width_of_the_longest_answer():
    ws = load_worksheet(LENA)
    section = _task_section(build_html(ws), _number(ws, "t6"))
    widths = set(re.findall(r'class="blank" style="width:([\d.]+)mm"', section))
    assert len(widths) == 1 and float(widths.pop()) > 18


# ---------------------------------------------------------------------------
# Answer keys
# ---------------------------------------------------------------------------


def test_answer_keys_follow_the_shuffles():
    ws = load_worksheet(SHOWCASE)
    p = plan(ws)
    by_id = {pt.task.id: pt for pt in p.tasks}

    match = by_id["t1"]
    key = answer_key(match, ws)
    for pair, letter in zip(match.task.pairs, key):
        assert match.right_column["ABCDEFGHI".index(letter)] == pair.right

    assert answer_key(by_id["t2"], ws) == [
        "falsch – Elle habite à Lyon depuis un mois.", "richtig",
        "falsch – Elle achète un kilo de tomates.",
    ]
    mc = by_id["t5"]
    for item, entry, order in zip(mc.task.items, answer_key(mc, ws), mc.option_orders):
        letter, _, text = entry.partition(" – ")
        assert text == item.answer and order["abc".index(letter)] == item.answer

    events = by_id["t11"]
    numbers = [int(n) for n in answer_key(events, ws)]
    assert [events.task.events[n - 1] for n in numbers] == events.events

    assert answer_key(by_id["t4"], ws) == ["marché", "balance", "fromage", "panier"]
    assert answer_key(by_id["t3"], ws) == ["le parasol", "la balance", "les tomates",
                                           "le fromage", "le panier"]
    assert answer_key(by_id["t10"], ws) == [
        "choisi", "salade", "Une carafe d'eau, s'il vous plaît.", "quenelles", "délicieux",
        "L'addition, s'il vous plaît !",
    ]
    assert answer_key(by_id["t12"], ws)[0] == "le tire-bouchon"
    for open_task in ("t13", "t14", "t15", "t26"):
        assert answer_key(by_id[open_task], ws) == []

    classify = by_id["t21"]
    assert classify.row_order is not None
    assert answer_key(classify, ws) == [classify.task.items[i].answer for i in classify.row_order]
    gapped = by_id["t20"]
    removed = re.findall(r"\{\{(.+?)\}\}", gapped.task.text)
    assert gapped.slot_options is not None
    assert [gapped.slot_options["ABCDE".index(k)] for k in answer_key(gapped, ws)] == removed
    choice = by_id["t19"]
    assert choice.gap_options is not None
    for options, entry, answer in zip(choice.gap_options, answer_key(choice, ws),
                                      ["veut", "monte", "connaît", "viens"], strict=True):
        letter, _, text = entry.partition(f"{NBSP}–⁠{NBSP}")
        assert text == answer and options["abc".index(letter)] == answer
    assert answer_key(by_id["t18"], ws)[1] == (
        f"Combien coûte le saint-marcellin{NBSP}? / Le saint-marcellin coûte combien{NBSP}?"
    )
    assert answer_key(by_id["t22"], ws) == [
        "richtig – «Les nappes sont rouges et blanches»",
        "falsch – Le serveur parle très vite. «le serveur parle très vite»",
        "falsch – Karim prend des quenelles. «Karim prend des quenelles»",
        "steht nicht im Text", "steht nicht im Text",
    ]
    assert answer_key(by_id["t25"], ws) == [
        f"{wrong}{NBSP}→ {right}" for wrong, right in
        [("ai", "suis"), ("des", "de"), ("avons", "sommes"), ("la", "le"), ("mangés", "mangé")]
    ]


def test_letters_never_run_out():
    from langwich.answers import letter

    assert [letter(i) for i in (0, 25, 26, 27, 51, 52)] == ["A", "Z", "AA", "AB", "AZ", "BA"]
    assert letter(2, upper=False) == "c"
    data = _lena()
    data["tasks"][0]["extra"] = [f"distractor {i}" for i in range(30)]
    ws = worksheet_from_dict(data)
    html = build_html(ws)
    assert '<td class="l">AF</td>' in html
    match = next(pt for pt in plan(ws).tasks if pt.task.id == "t1")
    assert len(answer_key(match, ws)) == 8


def test_cloze_items_join_several_gaps():
    ws = load_worksheet(LENA)
    pt = next(pt for pt in plan(ws).tasks if pt.task.id == "t5")
    assert answer_key(pt, ws)[0] == "werden … geerntet"


def test_open_tasks_show_the_model_answer_in_the_solutions():
    ws = load_worksheet(SHOWCASE)
    html = build_html(ws)
    solutions = html.split('class="solutions', 1)[1]
    assert "Musterlösung" in solutions and "Chère Mamie, samedi" in solutions
    assert "Individuelle Lösungen." in solutions


# ---------------------------------------------------------------------------
# Without WeasyPrint
# ---------------------------------------------------------------------------


def test_without_weasyprint_the_html_is_still_written(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    monkeypatch.setitem(sys.modules, "weasyprint.text.fonts", None)
    ws = load_worksheet(LENA)
    result = render_worksheet(ws, tmp_path / "lena.pdf", RenderOptions(solutions="separate"))
    assert result.pdf is None and result.solutions_pdf is None and result.pages is None
    assert result.weasyprint_error and "weasyprint" in result.weasyprint_error
    assert result.html.exists() and (tmp_path / "lena-solutions.html").exists()
    assert not (tmp_path / "lena.pdf").exists()
    html = result.html.read_text(encoding="utf-8")
    assert "@font-face" in html and "Literata-400.ttf" in html


def test_build_html_does_not_touch_the_worksheet():
    ws = load_worksheet(LENA)
    before = copy.deepcopy(ws.model_dump())
    build_html(ws, RenderOptions(page="epaper", one_task_per_page=True))
    assert ws.model_dump() == before


# ---------------------------------------------------------------------------
# Layout (HTML): side column, boxes, blanks, word list, key
# ---------------------------------------------------------------------------


def _grammar_ws(table: dict, lang_pair=("de", "fr"), **extra) -> tuple:
    """The showcase with task t7's grammar point replaced."""
    data = _showcase()
    data["source_lang"], data["target_lang"] = lang_pair
    gp = data["grammar"][0]
    gp.update({"table": table, **extra})
    ws = worksheet_from_dict(data)
    return ws, gp["id"]


WIDE_TABLE = {
    "head": ["", "Imparfait – Hintergrund", "Passé composé – Ereignis"],
    "rows": [
        ["Wofür?", "Zustand, Beschreibung, laufende Handlung", "einzelnes, abgeschlossenes Ereignis"],
        ["Signalwörter", "pendant que, d'habitude, toujours", "soudain, tout à coup, à 20 heures"],
        ["Bildung", "ranger → nous rangeons → je rangeais", "voir → j'ai vu · partir → elle est partie"],
    ],
}


def test_a_grammar_table_too_wide_for_the_side_column_spans_the_page():
    ws, _ = _grammar_ws(WIDE_TABLE)
    number = next(pt.number for pt in plan(ws).tasks if pt.sidebars)
    section = _task_section(build_html(ws), number)
    assert re.search(r'<div class="before"[^>]*><div class="snippet full">', section)
    assert 'class="aside-stack"' not in section  # nothing else needed a side column
    # a small table stays beside the items
    small, _ = _grammar_ws({"head": ["", "avoir"], "rows": [["je", "j'ai"], ["tu", "tu as"]]})
    number = next(pt.number for pt in plan(small).tasks if pt.sidebars)
    section = _task_section(build_html(small), number)
    assert '<aside class="aside-stack"><div class="snippet">' in section
    assert 'class="before"' not in section


def test_grammar_table_cells_carry_their_own_language():
    ws, _ = _grammar_ws(WIDE_TABLE)
    html = build_html(ws, RenderOptions(page="epaper"))
    table = re.search(r'<div class="snippet[^"]*">.*?(<table.*?</table>)', html, flags=re.S).group(1)
    assert not re.match(r"<table[^>]*lang=", table)  # never the whole table as French
    assert re.search(r'<td class="src[^"]*" lang="de">Signalwörter</td>', table)
    assert re.search(r'<td class="src[^"]*" lang="de">Wofür\?</td>', table)
    assert re.search(r'<td lang="fr">soudain, tout à coup', table)
    assert 'lang="fr">Zustand' not in table


def test_suffixes_and_hyphenated_words_never_break_at_the_hyphen():
    ws, _ = _grammar_ws(WIDE_TABLE, explanation="Nomen auf -ie sind weiblich, auf -eur männlich.")
    html = build_html(ws)
    assert 'Nomen auf <span class="nw">-ie</span> sind' in html
    assert '<span class="nw">-eur</span>' in html
    search = re.search(r'<div class="search">.*?</div>', html, flags=re.S).group(0)
    assert '<span class="nw">Croix-Rousse</span>' in search


def test_epaper_puts_grammar_and_word_boxes_before_the_items():
    ws = load_worksheet(LENA)
    html = build_html(ws, RenderOptions(page="epaper"))
    assert 'class="aside-stack"' not in html
    cloze = _task_section(html, _number(ws, "t6"))  # word bank
    assert cloze.index('class="before"') < cloze.index('class="box wordbox"') < cloze.index(
        'class="body')
    grammar_task = next(pt for pt in plan(ws).tasks if pt.sidebars)
    section = _task_section(html, grammar_task.number)
    assert (section.index('class="before"') < section.index('class="snippet full"')
            < section.index('class="body'))
    assert 'class="pre"' not in section  # grammar does not make the task unbreakable
    assert " flow" in section.split(">", 1)[0]


def test_flowing_tasks_and_kept_tasks():
    ws = load_worksheet(LENA)
    html = build_html(ws)
    by_kind = {pt.task.kind: pt.number for pt in plan(ws).tasks}
    assert " flow" in _task_section(html, by_kind["questions"]).split(">", 1)[0]
    for kind in ("match", "label", "order_events"):
        head = _task_section(html, by_kind[kind]).split(">", 1)[0]
        assert " keep" in head and " flow" not in head
    # every task body names the task for a page that starts inside it
    for pt in plan(ws).tasks:
        body = re.search(r'<div class="body[^"]*" data-cont="([^"]+)"', _task_section(html, pt.number))
        assert body and body.group(1).startswith(f"Task {pt.number} · ")
        assert body.group(1).endswith("(continued)")
    assert f'string-set: hd "{ws.title}"' in html


def test_a_label_task_and_its_picture_task_share_a_page_or_a_small_copy():
    ws = load_worksheet(LENA)
    label, questions = _number(ws, "t9"), _number(ws, "t10")
    a4 = build_html(ws)
    pair = re.search(rf'<div class="pair" data-pair="{questions}">.*?</section></div>', a4,
                     flags=re.S)
    assert pair and f'id="task-{label}"' in pair.group(0) and f'id="task-{questions}"' in pair.group(0)
    assert 'fig mini' not in a4
    otp = build_html(ws, RenderOptions(one_task_per_page=True))
    section = _task_section(otp, questions)
    assert 'class="pair"' not in otp and '<figure class="fig mini"' in section
    assert section.count('class="mk"') == len(ws.scene("s4").picture.labels)


def test_blanks_sit_flush_after_elisions_and_keep_their_punctuation():
    from langwich.render.html import Builder
    from langwich.render.tasks import gapped_html

    b = Builder(load_worksheet(SHOWCASE))
    html = gapped_html(b, "il faut prendre l'{{escalier}}. Oui", 20.0, "first_letter")
    assert 'class="gap el pu"' in html
    assert re.search(r'<span class="fl">e</span></span>\.</span> Oui', html)
    html = gapped_html(b, "Vous avez {{choisi}} ? Bien", 20.0)
    assert re.search(r'</span> \?</span> Bien', html)  # French space, glued
    html = gapped_html(b, "Le {{pain}}, s'il vous plaît.", 20.0)
    assert '</span>,</span> s&#x27;il' in html
    html = gapped_html(b, "Das ist {{gut}} (sehr).", 20.0)
    assert 'class="gap"' in html  # an opening bracket stays outside


def test_writing_word_range_is_not_repeated():
    data = _showcase()
    writing = next(t for t in data["tasks"] if t["kind"] == "writing")
    writing["instruction"] = "Schreib auf Französisch (40–60 Wörter)."
    html = build_html(worksheet_from_dict(data))
    section = re.search(r'<section class="task unit k-writing.*?</section>', html,
                        flags=re.S).group(0)
    assert 'class="len"' not in section and section.count("40–60") == 1
    writing["instruction"] = "Schreib auf Französisch."
    html = build_html(worksheet_from_dict(data))
    assert 'class="len"' in html


def test_word_bank_instruction_and_repeated_answers():
    data = _lena()
    cloze = next(t for t in data["tasks"] if t["id"] == "t6")
    cloze.pop("instruction", None)
    cloze["distractors"] = []
    first = re.search(r"\{\{([^}|:]+)", cloze["text"]).group(1)
    cloze["text"] += " Noch einmal: {{" + first + "}}."
    ws = worksheet_from_dict(data)
    section = _task_section(build_html(ws), _number(ws, "t6"))
    assert "Fill the gaps with the words from the box." in section
    assert "left over" not in section
    assert re.search(rf"<li>{re.escape(first)}<span class=\"cnt\">2×</span></li>", section)
    cloze["distractors"] = ["Tasse"]
    section = _task_section(build_html(worksheet_from_dict(data)), _number(ws, "t6"))
    assert "Some words are left over." in section


def test_word_list_rows():
    data = _showcase()
    items = data["vocabulary"]["items"]
    items.append({"term": "l'écran", "translation": "der Bildschirm", "pos": "noun", "note": "m"})
    items.append({"term": "la bénévole", "translation": "die Freiwillige", "pos": "noun",
                  "note": "m.: le bénévole"})
    items.append({"term": "le balcon", "translation": "der Balkon", "pos": "noun", "note": "(Lyon)"})
    html = build_html(worksheet_from_dict(data))
    words = html.split('class="vocab-list')[1]
    # a bare gender note belongs to the headword, not to the translation
    assert re.search(r'l&#x27;écran <span class="gd">m</span></div><div class="en" lang="de">'
                     r"der Bildschirm</div>", words)
    assert re.search(r'la bénévole<span class="forms">m\.: le bénévole</span>', words)
    assert "der Balkon <i>((Lyon))</i>" in words
    assert "le balcon" in words  # the article never ends a line
    german = build_html(load_worksheet(LENA)).split('class="vocab-list')[1]
    assert re.search(r'<i class="nw">, -n</i>', german) or re.search(
        r'<i class="nw">, ¨?-?\w*</i>', german)


def test_rtl_targets_and_sources_get_a_direction():
    data = _lena()
    data["target_lang"] = "ar"
    html = build_html(worksheet_from_dict(data))
    assert '<html lang="en" class=' in html
    assert re.search(r'<h1 class="tl" lang="ar" dir="rtl">', html)
    assert re.search(r'<p class="tl" lang="ar" dir="rtl">', html)
    data = _lena()
    data["source_lang"] = "he"
    html = build_html(worksheet_from_dict(data))
    assert '<html lang="he" dir="rtl"' in html
    assert re.search(r'<p class="tl" lang="de" dir="ltr">', html)


def test_photos_are_capped_lower_than_line_art(tmp_path):
    from PIL import Image

    Image.new("RGB", (1200, 900), (90, 90, 90)).save(tmp_path / "photo.jpg")
    data = _lena()
    pic = data["story"]["scenes"][3]["picture"]
    pic.pop("svg")
    pic["image"] = "photo.jpg"
    html = build_html(worksheet_from_dict(data), RenderOptions(base_dir=tmp_path))
    height = float(re.search(r'<figure class="fig" data-h="([\d.]+)"', html).group(1))
    assert height <= 100.0


def test_balanced_split():
    from langwich.render.html import balanced_split

    assert balanced_split([10, 20, 30, 40, 50, 60, 70], 3) == [(0, 4), (4, 6), (6, 7)]
    assert balanced_split([5], 3) == [(0, 1), (1, 1), (1, 1)]
    runs = balanced_split([4.0] * 22, 3)
    assert [b - a for a, b in runs] == [8, 8, 6]


# ---------------------------------------------------------------------------
# Untrusted pictures: nothing outside is fetched, nothing breaks
# ---------------------------------------------------------------------------


def test_svg_scripts_and_outside_references_are_removed():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           'viewBox="0 0 40 30" onload="alert(1)">'
           '<script>alert(2)</script><foreignObject><p>x</p></foreignObject>'
           '<image href="file:///etc/secret.png" width="5" height="5"/>'
           '<image xlink:href="http://127.0.0.1:9/track.png" width="5" height="5"/>'
           '<style>@import url(http://evil/x.css); rect { fill: url(http://evil/p) }</style>'
           '<defs><linearGradient id="g"/></defs><rect width="10" height="10" fill="url(#g)"/>'
           '<use href="#g"/><image href="data:image/png;base64,iVBORw0KGgo=" width="1" height="1"/>'
           "</svg>")
    warnings: list[str] = []
    prepared = prepare_picture(Picture(svg=svg), None, True, warnings)
    text = base64.b64decode(prepared.data_uri.split(",", 1)[1]).decode()
    for bad in ("script", "foreignObject", "file:", "127.0.0.1", "evil", "onload", "@import"):
        assert bad not in text, bad
    assert 'fill="url(#g)"' in text and 'href="#g"' in text and "data:image/png" in text
    assert warnings and "removed from the SVG" in warnings[0]
    clean: list[str] = []
    prepare_picture(Picture(svg='<svg viewBox="0 0 4 3"><rect width="1" height="1"/></svg>'),
                    None, True, clean)
    assert clean == []


def test_the_renderer_fetches_only_data_and_the_bundled_fonts(weasy):
    from langwich.render import is_allowed_url, make_url_fetcher
    from langwich.render.css import FONTS_DIR

    font = (FONTS_DIR / "Literata-400.ttf").resolve().as_uri()
    assert is_allowed_url(font) and is_allowed_url("data:image/png;base64,AAAA")
    for url in ("file:///etc/passwd", "http://127.0.0.1:9/x.png", "https://example.org/x.css",
                (FONTS_DIR / ".." / "model.py").resolve().as_uri()):
        assert not is_allowed_url(url), url
    blocked: list[str] = []
    fetcher = make_url_fetcher(blocked)
    with pytest.raises(ValueError):
        fetcher("file:///etc/passwd")
    assert blocked == ["file:///etc/passwd"]


def test_an_svg_cannot_pull_a_local_file_into_the_pdf(tmp_path, fitz):
    from PIL import Image

    secret = tmp_path / "secret" / "s.png"
    secret.parent.mkdir()
    Image.new("RGB", (30, 10), (0, 0, 0)).save(secret)
    data = _lena()
    pic = data["story"]["scenes"][3]["picture"]
    pic["svg"] = pic["svg"].replace(
        "</svg>", f'<image href="{secret.as_uri()}" x="0" y="0" width="30" height="10"/></svg>')
    result = render_worksheet(worksheet_from_dict(data), tmp_path / "out" / "x.pdf",
                              RenderOptions(solutions="none"))
    assert any("removed from the SVG" in w for w in result.warnings)
    doc = fitz.open(result.pdf)
    assert all(not page.get_images() for page in doc)


def _heic_bytes() -> bytes:
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64


def test_heic_photos_get_a_warning_a_person_can_act_on(tmp_path):
    from langwich import images

    (tmp_path / "IMG_4711.HEIC").write_bytes(_heic_bytes())
    warnings: list[str] = []
    assert prepare_picture(Picture(image="IMG_4711.HEIC"), tmp_path, True, warnings) is None
    assert len(warnings) == 1 and "IMG_4711.HEIC" in warnings[0]
    assert "BytesIO" not in warnings[0]
    if not images.HEIF_SUPPORT:
        assert "pillow-heif" in warnings[0] and "JPEG" in warnings[0]
    (tmp_path / "notes.png").write_bytes(b"this is text, not a picture")
    warnings.clear()
    prepare_picture(Picture(image="notes.png"), tmp_path, True, warnings)
    assert "notes.png" in warnings[0] and "BytesIO" not in warnings[0]


def test_a_decompression_bomb_is_refused_politely(tmp_path, recwarn):
    from PIL import Image

    Image.new("1", (9000, 9000)).save(tmp_path / "huge.png")  # 81 MP in a small file
    warnings: list[str] = []
    assert prepare_picture(Picture(image="huge.png"), tmp_path, True, warnings) is None
    assert "too large" in warnings[0] and "9000 × 9000" in warnings[0]
    assert not [w for w in recwarn if "DecompressionBomb" in type(w.message).__name__]


def test_a_very_large_jpeg_is_decoded_at_a_reduced_size(tmp_path):
    from PIL import Image

    Image.new("L", (8200, 7400), 128).save(tmp_path / "big.jpg", quality=50)
    warnings: list[str] = []
    prepared = prepare_picture(Picture(image="big.jpg"), tmp_path, True, warnings)
    assert warnings == [] and prepared is not None
    assert max(prepared.width, prepared.height) <= 2400


# ---------------------------------------------------------------------------
# The rendered examples: what a reader sees (PDF, read back with pymupdf)
# ---------------------------------------------------------------------------

#: Page margins in mm: top, right, bottom, left.
MARGINS = {"a4": (18, 12, 15, 20), "epaper": (10, 8, 10, 8)}
LAYOUTS = [(path, page) for path in EXAMPLES for page in ("a4", "epaper")]
LAYOUT_IDS = [f"{path.stem.split('_')[0]}-{path.stem.split('_')[1]}-{page}" for path, page in LAYOUTS]
ARTICLES = {"der", "die", "das", "den", "dem", "des", "le", "la", "les", "l'", "un", "une", "el",
            "los", "las", "il", "lo", "gli", "o", "a", "os", "as", "the"}


@pytest.fixture(scope="session")
def rendered(tmp_path_factory):
    """``rendered(path, page, otp=False) -> (worksheet, RenderResult, pymupdf doc)``, cached."""
    pymupdf = need_pdf(pymupdf=True)
    out = tmp_path_factory.mktemp("examples")
    cache: dict = {}

    def get(path: Path, page: str, otp: bool = False):
        key = (path, page, otp)
        if key not in cache:
            ws = load_worksheet(path)
            pdf = out / f"{path.stem}-{page}{'-otp' if otp else ''}.pdf"
            result = render_worksheet(ws, pdf, RenderOptions(page=page, one_task_per_page=otp,
                                                             base_dir=path.parent))
            cache[key] = (ws, result, pymupdf.open(result.pdf))
        return cache[key]

    return get


def _content_box(page, kind):
    top, right, bottom, left = MARGINS[kind]
    return left * MM, top * MM, page.rect.width - right * MM, page.rect.height - bottom * MM


def _lines(page, box):
    """Text lines inside the content box (running header and footer left out)."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if spans and line["bbox"][1] >= box[1] - 1 and line["bbox"][3] <= box[3] + 1:
                out.append({"bbox": line["bbox"], "text": "".join(s["text"] for s in spans),
                            "spans": spans})
    return out


def _ink(page):
    return [d for d in page.get_drawings()
            if not (d.get("fill") in ((1, 1, 1), (1.0, 1.0, 1.0)) and not d.get("color"))]


def _fill(page, box) -> float:
    """Share of the content height down to the lowest text, rule or picture."""
    bottom = box[1]
    for line in _lines(page, box):
        bottom = max(bottom, line["bbox"][3])
    for d in _ink(page):
        if box[1] - 1 <= d["rect"].y0 and d["rect"].y1 <= box[3] + 1:
            bottom = max(bottom, d["rect"].y1)
    for img in page.get_image_info():
        if img["bbox"][3] <= box[3] + 1:
            bottom = max(bottom, img["bbox"][3])
    return (bottom - box[1]) / (box[3] - box[1])


def _squares(page, filled: bool):
    """Task number squares (solid black, 6.5 mm) or scene number squares (framed)."""
    out = []
    for d in page.get_drawings():
        r = d["rect"]
        if not (16 < r.width < 20 and 16 < r.height < 20):
            continue
        solid = d.get("fill") in ((0, 0, 0), (0.0, 0.0, 0.0))
        if solid == filled:
            out.append(r)
    return sorted(out, key=lambda r: r.y0)


def _starts_answers(page, ws) -> bool:
    from langwich import locale

    title = locale.t("solutions", ws.source_lang, ws.ui)
    return any(line["text"].strip() == title and line["spans"][0]["size"] > 16
               for line in _lines(page, (0, 0, page.rect.width, page.rect.height)))


@pytest.mark.parametrize(("path", "page"), LAYOUTS, ids=LAYOUT_IDS)
def test_no_word_leaves_the_content_box(rendered, path, page):
    ws, result, doc = rendered(path, page)
    assert result.warnings == []
    fonts = {f[3].split("+", 1)[-1] for p in doc for f in p.get_fonts()}
    assert all(f.startswith(("Literata", "Atkinson-Hyperlegible-Next")) for f in fonts), fonts
    for number, p in enumerate(doc, 1):
        x0, _, x1, _ = _content_box(p, page)
        outside = [(w[4], round(w[0] / MM, 1), round(w[2] / MM, 1)) for w in p.get_text("words")
                   if w[4].strip() and (w[0] < x0 - 0.5 * MM or w[2] > x1 + 0.5 * MM)]
        assert not outside, (number, outside[:5])


@pytest.mark.parametrize(("path", "page", "otp"),
                         [(p, pg, False) for p, pg in LAYOUTS] + [(EXAMPLES[-1], "epaper", True)],
                         ids=LAYOUT_IDS + ["kinds-otp-epaper"])
def test_no_page_ends_with_a_task_header(rendered, path, page, otp):
    _, _, doc = rendered(path, page, otp)
    for number, p in enumerate(doc, 1):
        box = _content_box(p, page)
        squares = _squares(p, filled=True)
        squares = [r for r in squares if r.y0 > box[1] and r.x0 < box[0] + 2 * MM]  # task numbers
        if not squares:
            continue
        last = squares[-1]
        below = [ln for ln in _lines(p, box) if ln["bbox"][1] > last.y1 + 0.5]
        header_text = [ln for ln in _lines(p, box) if last.y0 - 2 <= ln["bbox"][1] <= last.y1]
        content = [ln for ln in below
                   if any("Literata" in s["font"] for s in ln["spans"])
                   or ln["bbox"][0] < last.x1 - 1]  # items: serif text or numbers in the gutter
        drawings = [d for d in _ink(p) if d["rect"].y0 > last.y1 + 2 and d["rect"].y1 <= box[3] + 1]
        assert content or drawings, (number, [ln["text"] for ln in header_text + below])


@pytest.mark.parametrize(("path", "page"), LAYOUTS, ids=LAYOUT_IDS)
def test_no_half_empty_page_in_the_middle_of_a_worksheet(rendered, path, page):
    """A page may stay less than 45% full only before a forced break (the
    answer section) or when what comes next could not have fitted on it."""
    ws, _, doc = rendered(path, page)
    pages = list(doc)
    for i in range(len(pages) - 1):
        p, nxt = pages[i], pages[i + 1]
        box = _content_box(p, page)
        fill = _fill(p, box)
        if fill >= 0.45 or _starts_answers(nxt, ws):
            continue
        free = (1 - fill) * (box[3] - box[1])
        nbox = _content_box(nxt, page)
        heads = [r.y0 for r in _squares(nxt, True) + _squares(nxt, False)
                 if r.x0 < nbox[0] + 2 * MM and r.y0 > nbox[1] + 12 * MM]
        # the unit that opens the next page ends where the next task or scene begins
        end = min(heads) - 9 * MM if heads else nbox[1] + _fill(nxt, nbox) * (nbox[3] - nbox[1])
        unit = end - nbox[1]
        assert unit > free - 2 * MM, (
            f"page {i + 1} is {fill:.0%} full, but the {unit / MM:.0f} mm that open page {i + 2} "
            f"would have fitted into its {free / MM:.0f} mm")


def _word_list_tokens(ws) -> set[str]:
    from langwich.render.html import plural_note

    tokens: set[str] = set()
    for v in ws.vocabulary.items:
        for text in (v.term, v.plural or "", v.forms or "", v.note or "",
                     plural_note(v, ws.target_lang) or ""):
            tokens.update(_word_tokens(text))
    return tokens


def _word_tokens(text: str) -> list[str]:
    text = text.replace(" ", " ")
    return [t for t in (w.strip(",;:()·.!?¡¿…\"„“”'’") for w in text.split()) if t]


@pytest.mark.parametrize(("path", "page"), LAYOUTS, ids=LAYOUT_IDS)
def test_word_list_rows_never_break_inside_a_term(rendered, path, page):
    from langwich import locale

    ws, _, doc = rendered(path, page)
    tokens = _word_list_tokens(ws)
    heading = locale.t("word_list", ws.source_lang, ws.ui)
    in_list = False
    for number, p in enumerate(doc, 1):
        if _starts_answers(p, ws):
            break
        box = _content_box(p, page)
        lines = _lines(p, box)
        if not in_list:
            starts = [ln for ln in lines if ln["text"].strip() == heading]
            if not starts:
                continue
            in_list = True
            lines = [ln for ln in lines if ln["bbox"][1] > starts[0]["bbox"][3]]
        ends = [ln["bbox"][1] for ln in lines if ln["spans"][0]["size"] > 16]
        if ends:  # the next section (reference grammar) begins on this page
            lines = [ln for ln in lines if ln["bbox"][1] < min(ends)]
        previous_hyphen = False
        for ln in sorted(lines, key=lambda ln: (ln["bbox"][0] // (40 * MM), ln["bbox"][1])):
            spans = [s for s in ln["spans"] if "Literata" in s["font"] and s["size"] < 12]
            if not spans or len(spans) != len(ln["spans"]):
                continue  # translations (sans) and headings
            text = "".join(s["text"] for s in spans).strip()
            assert text.casefold().rstrip() not in ARTICLES, (number, text)
            assert not text.startswith((")", ",")), (number, text)
            for word in _word_tokens(text):
                ok = (word in tokens
                      or (word.endswith("-") and any(t.startswith(word[:-1]) for t in tokens))
                      or (previous_hyphen and any(t.endswith(word) for t in tokens)))
                assert ok, (number, word, text)
            previous_hyphen = text.endswith("-")
        if ends:
            break


@pytest.mark.parametrize(("path", "page"), LAYOUTS, ids=LAYOUT_IDS)
def test_a_page_that_starts_inside_a_task_names_it(rendered, path, page):
    from langwich import locale

    ws, _, doc = rendered(path, page)
    task_word = locale.t("task", ws.source_lang, ws.ui)
    continued = locale.t("continued", ws.source_lang, ws.ui)
    last_task = None
    for number, p in enumerate(doc, 1):
        header = p.get_text("text", clip=(0, 0, p.rect.width, MARGINS[page][0] * MM)).strip()
        m = re.match(rf"{re.escape(task_word)} (\d+) · .*\({re.escape(continued)}\)", header)
        if m:
            assert int(m.group(1)) == last_task, (number, header)
        box = _content_box(p, page)
        for sq in _squares(p, True):
            if sq.x0 < box[0] + 2 * MM:
                digits = p.get_text("text", clip=sq).strip()
                if digits.isdigit():
                    last_task = int(digits)


def _crossword_cell_number(page, span) -> bool:
    """A clue number in the top left corner of a crossword cell: digits just
    right of and below the top of a vertical cell border (the grid's borders
    are drawn as lines one cell long)."""
    if not span["text"].strip().isdigit():
        return False
    x0, y0 = span["bbox"][0], span["bbox"][1]
    return any(
        d["rect"].width < 0.1 * MM and 5 * MM < d["rect"].height < 10 * MM
        and 0 <= x0 - d["rect"].x0 < 1.5 * MM and 0 <= y0 - d["rect"].y0 < 1.5 * MM
        for d in page.get_drawings()
    )


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem.split("_")[0] for p in EXAMPLES])
def test_epaper_text_is_large_and_dark_enough(rendered, path):
    """E-paper: nothing below 8.5 pt, no text lighter than #444 (white on black is fine).
    One exception: the clue numbers in the corners of crossword cells are
    7 pt (the e-paper CSS sets 'table.cwg .cn'), so that they leave the
    7 mm cell to the letter the learner writes in it."""
    _, _, doc = rendered(path, "epaper")
    for number, p in enumerate(doc, 1):
        for block in p.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if not span["text"].strip():
                        continue
                    if 6.9 <= span["size"] < 8.4 and _crossword_cell_number(p, span):
                        continue
                    assert span["size"] >= 8.4, (number, span["text"], span["size"])
                    color = span["color"]
                    channels = (color >> 16 & 255, color >> 8 & 255, color & 255)
                    assert color == 0xFFFFFF or max(channels) <= 0x44, (number, span["text"], hex(color))
