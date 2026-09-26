"""The renderer: HTML + print CSS + PDF for langwich/3 worksheets."""

from __future__ import annotations

import base64
import copy
import io
import json
import re
import sys
from pathlib import Path

import pytest

from langwich.answers import answer_key
from langwich.images import prepare_picture
from langwich.model import MatchTask, Picture, load_worksheet, worksheet_from_dict
from langwich.plan import plan, strip_article
from langwich.plan import tested_terms as collect_tested_terms
from langwich.render import RenderOptions, build_html, render_worksheet

ROOT = Path(__file__).resolve().parent.parent
LENA = ROOT / "examples" / "lena_01_en_de.json"
CAFE_SVG = ROOT / "examples" / "pictures" / "cafe_lindner.svg"
SHOWCASE = ROOT / "tests" / "fixtures" / "kinds_showcase.json"

MM = 72 / 25.4


def _has_weasyprint() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


requires_pdf = pytest.mark.skipif(not _has_weasyprint(), reason="WeasyPrint is not available")


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


# ---------------------------------------------------------------------------
# The reference example, rendered once to PDF
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lena_pdf(tmp_path_factory):
    if not _has_weasyprint():
        pytest.skip("WeasyPrint is not available")
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


def test_lena_pdf_embeds_only_the_bundled_fonts(lena_pdf):
    pymupdf = pytest.importorskip("pymupdf")
    _, result = lena_pdf
    doc = pymupdf.open(result.pdf)
    fonts = {f[3].split("+", 1)[-1] for page in doc for f in page.get_fonts()}
    assert fonts, "no fonts embedded"
    assert all(f.startswith(("Literata", "Atkinson-Hyperlegible-Next")) for f in fonts), fonts
    assert any(f.startswith("Literata") for f in fonts)
    assert any(f.startswith("Atkinson") for f in fonts)


def test_lena_pdf_text_stays_inside_the_page(lena_pdf):
    pymupdf = pytest.importorskip("pymupdf")
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


def test_lena_image_prompt_is_never_printed(lena_pdf):
    pymupdf = pytest.importorskip("pymupdf")
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


def test_lena_solutions_and_translations_are_appended(lena_pdf):
    pymupdf = pytest.importorskip("pymupdf")
    ws, result = lena_pdf
    html = result.html.read_text(encoding="utf-8")
    p = plan(ws)
    assert html.count('<div class="sb">') == len(p.tasks)
    match = next(pt for pt in p.tasks if isinstance(pt.task, MatchTask))
    key = answer_key(match, ws)
    assert " · ".join(f"{i} {k}" for i, k in enumerate(key, 1)) in _text(html)
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
    markers = re.findall(r'<span class="mk" style="left:([\d.]+)mm;top:([\d.]+)mm">(\d+)</span>', html)
    labels = {lb.n: lb for lb in ws.scene("s4").picture.labels}
    assert [int(n) for _, _, n in markers] == sorted(labels)
    pic = re.search(r'<div class="pic" style="width:([\d.]+)mm;height:([\d.]+)mm">', html)
    width, height = float(pic.group(1)), float(pic.group(2))
    assert width == pytest.approx(178 - 0.71, abs=0.05)
    assert height / width == pytest.approx(92 / 178, rel=0.01)  # the svg viewBox ratio
    for left, top, n in markers:
        lb = labels[int(n)]
        assert float(left) + 3 == pytest.approx(min(max(lb.x * width, 3), width - 3), abs=0.02)
        assert float(top) + 3 == pytest.approx(min(max(lb.y * height, 3), height - 3), abs=0.02)


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def test_same_worksheet_and_seed_give_identical_html():
    ws = load_worksheet(SHOWCASE)
    opts = RenderOptions(base_dir=SHOWCASE.parent)
    assert build_html(ws, opts) == build_html(load_worksheet(SHOWCASE), opts)
    seeded = RenderOptions(seed=7)
    assert build_html(ws, seeded) == build_html(ws, RenderOptions(seed=7))


@requires_pdf
def test_separate_solutions_write_a_second_pdf(tmp_path):
    ws = load_worksheet(LENA)
    result = render_worksheet(ws, tmp_path / "lena.pdf", RenderOptions(solutions="separate"))
    assert result.pdf.exists()
    assert result.solutions_pdf == tmp_path / "lena-solutions.pdf"
    assert result.solutions_pdf.exists()
    assert (tmp_path / "lena-solutions.html").exists()
    main_html = result.html.read_text(encoding="utf-8")
    sol_html = (tmp_path / "lena-solutions.html").read_text(encoding="utf-8")
    assert 'class="solutions"' not in main_html
    assert 'class="solutions"' in sol_html and 'class="cover"' not in sol_html


def test_no_solutions_leaves_out_the_answer_section(tmp_path):
    ws = load_worksheet(LENA)
    result = render_worksheet(ws, tmp_path / "lena.pdf",
                              RenderOptions(solutions="none", html_only=True))
    html = result.html.read_text(encoding="utf-8")
    assert result.pdf is None and result.solutions_pdf is None
    assert 'class="solutions"' not in html
    assert "trans-sec" not in html
    assert not (tmp_path / "lena-solutions.pdf").exists()
    assert "Word list" in html  # the back matter stays


def test_translations_can_be_left_out():
    ws = load_worksheet(LENA)
    assert "trans-sec" in build_html(ws)
    assert "trans-sec" not in build_html(ws, RenderOptions(translations=False))


@requires_pdf
def test_epaper_page_size(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    ws = load_worksheet(SHOWCASE)
    result = render_worksheet(ws, tmp_path / "ep.pdf",
                              RenderOptions(page="epaper", base_dir=SHOWCASE.parent))
    doc = pymupdf.open(result.pdf)
    for page in doc:
        assert page.rect.width == pytest.approx(157.8 * MM, abs=0.5)
        assert page.rect.height == pytest.approx(210.4 * MM, abs=0.5)
    assert result.pages == len(doc)


@requires_pdf
def test_one_task_per_page_adds_pages(tmp_path):
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
    section = re.search(r'<section class="task unit k-label keep" id="task-8">(.*?)</section>', html,
                        flags=re.S).group(1)
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
    assert html.count('<figure class="fig">') == 1


def test_picture_sits_in_its_label_task():
    html = build_html(load_worksheet(LENA))
    label = re.search(r'<section class="task unit k-label keep" id="task-10">(.*?)</section>', html,
                      flags=re.S).group(1)
    assert '<figure class="fig">' in label and 'class="name-grid"' in label
    assert html.count('<figure class="fig">') == 1


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


def test_every_kind_is_rendered():
    ws = load_worksheet(SHOWCASE)
    html = build_html(ws, RenderOptions(base_dir=SHOWCASE.parent))
    kinds = {t.kind for t in ws.tasks}
    assert len(kinds) == 13
    for kind in kinds:
        assert f"k-{kind}" in html
    assert 'class="dlg"' in html and 'class="search"' in html and 'class="wbi"' in html
    assert html.count('class="blank"') == 4 + 4 + 4  # passage, first-letter items, dialogue


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
    section = re.search(r'<section class="task unit k-writing".*?</section>', html, flags=re.S).group(0)
    assert "Schreibe 40–60 Wörter." in section
    assert 'class="starter tl"' in section
    assert section.count("<div></div>") + 1 == 6 + 1  # 60 words ≈ 6 lines, plus the starter line
    assert "le chemin" in section and "Verwende diese Wörter:" in section


def test_blanks_share_the_width_of_the_longest_answer():
    html = build_html(load_worksheet(LENA))
    section = re.search(r'<section class="task unit k-cloze keep" id="task-6">.*?</section>', html,
                        flags=re.S).group(0)
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
    for open_task in ("t13", "t14", "t15"):
        assert answer_key(by_id[open_task], ws) == []


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
    solutions = html.split('class="solutions"', 1)[1]
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
