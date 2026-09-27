"""Tests for the langwich CLI and the profile file.

The renderer and the prompt builder are replaced by small fakes that follow
their interfaces, so these tests exercise the CLI alone. Tests at the end
use the real modules when they are installed.
"""

from __future__ import annotations

import copy
import importlib
import io
import json
import os
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pytest

import langwich.prompt as real_prompt
from langwich import __version__
from langwich.cli import FRAMES, KIND_INFO, STAGE_INFO, main
from langwich.model import STAGES, TASK_KINDS, Worksheet, json_schema
from langwich.profile import find_profile, load_profile, save_profile
from langwich.prompt import MINI_EXAMPLE, PromptOptions, resolve_options

REPO_ROOT = Path(__file__).resolve().parent.parent
LENA = REPO_ROOT / "examples" / "lena_01_en_de.json"
VALENCIA = REPO_ROOT / "examples" / "mercado_valencia_en_es.json"
LEGACY = REPO_ROOT / "tests" / "fixtures" / "legacy_v2_coffee.json"


# ---------------------------------------------------------------------------
# Fakes and fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakeRenderOptions:
    page: Literal["a4", "epaper"] = "a4"
    one_task_per_page: bool = False
    solutions: Literal["append", "separate", "none"] = "append"
    translations: bool = True
    monochrome: bool = True
    seed: int | None = None
    base_dir: Path | None = None
    html_only: bool = False


@dataclass
class FakeRenderResult:
    html: Path
    pdf: Path | None
    solutions_pdf: Path | None
    pages: int | None
    warnings: list[str]
    image_prompts: list[tuple[str, str]]
    weasyprint_error: str | None = None


@dataclass
class Calls:
    items: list[Any] = field(default_factory=list)
    weasyprint_error: str | None = None
    image_prompts: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated project folder (with .git, so no outer profile is read)."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def fake_render(monkeypatch: pytest.MonkeyPatch) -> Calls:
    calls = Calls()
    mod = types.ModuleType("langwich.render")

    def render_worksheet(ws: Worksheet, out_pdf: Path, options: Any = None) -> FakeRenderResult:
        calls.items.append((ws, out_pdf, options))
        html = out_pdf.with_suffix(".html")
        no_pdf = options.html_only or calls.weasyprint_error is not None
        solutions = (
            out_pdf.with_name(out_pdf.stem + "-solutions.pdf")
            if options.solutions == "separate" and not no_pdf else None
        )
        return FakeRenderResult(
            html=html, pdf=None if no_pdf else out_pdf, solutions_pdf=solutions,
            pages=None if no_pdf else 7, warnings=list(calls.warnings),
            image_prompts=list(calls.image_prompts), weasyprint_error=calls.weasyprint_error,
        )

    mod.RenderOptions = FakeRenderOptions  # type: ignore[attr-defined]
    mod.RenderResult = FakeRenderResult  # type: ignore[attr-defined]
    mod.render_worksheet = render_worksheet  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langwich.render", mod)
    return calls


@pytest.fixture
def fake_prompt(monkeypatch: pytest.MonkeyPatch) -> Calls:
    """The prompt builder with a one-line prompt; the real options and the
    real resolution of languages, level and frame."""
    calls = Calls()
    mod = types.ModuleType("langwich.prompt")

    def build_prompt(opts: PromptOptions) -> str:
        calls.items.append(opts)
        r = real_prompt.resolve_options(opts)
        return f"PROMPT {r.source_lang}->{r.target_lang} {r.level}"

    def repair_prompt(report: Any, json_text: str) -> str:
        calls.items.append((report, json_text))
        return f"REPAIR {len(report.issues)} issues"

    mod.PromptOptions = PromptOptions  # type: ignore[attr-defined]
    mod.resolve_options = real_prompt.resolve_options  # type: ignore[attr-defined]
    mod.build_prompt = build_prompt  # type: ignore[attr-defined]
    mod.repair_prompt = repair_prompt  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langwich.prompt", mod)
    return calls


def resolved(opts: PromptOptions) -> tuple[str, str, str, str | None]:
    r = resolve_options(opts)
    return r.source_lang, r.target_lang, r.level, r.frame


def lena_data() -> dict[str, Any]:
    return json.loads(LENA.read_text(encoding="utf-8"))


def clean_data() -> dict[str, Any]:
    """A worksheet that validates without any issue (the prompt's example)."""
    return copy.deepcopy(MINI_EXAMPLE)


def issue_keys(path: Path) -> set[tuple[str, str]]:
    from langwich.validate import check_file

    return {(i.code, i.where) for i in check_file(path).issues}


def write_json(folder: Path, name: str, data: Any) -> Path:
    path = folder / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def write_profile(folder: Path, data: dict[str, Any]) -> None:
    (folder / ".langwich").mkdir(exist_ok=True)
    (folder / ".langwich" / "profile.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# General
# ---------------------------------------------------------------------------


def test_version_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert __version__ == "3.0.0"
    assert main(["--version"]) == 0
    assert "3.0.0" in capsys.readouterr().out
    assert main([]) == 0
    out = capsys.readouterr().out
    for command in ("render", "validate", "schema", "prompt", "kinds"):
        assert command in out


def test_unknown_command_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["frobnicate"]) == 2
    assert main(["lena.json"]) == 2
    assert "langwich render lena.json" in capsys.readouterr().err


def test_kinds_lists_all_kinds_and_stages(capsys: pytest.CaptureFixture[str]) -> None:
    assert set(KIND_INFO) == set(TASK_KINDS)
    assert list(STAGE_INFO) == list(STAGES)
    assert list(STAGES).index("picture") < list(STAGES).index("form")
    assert main(["kinds"]) == 0
    out = capsys.readouterr().out
    for name in (*TASK_KINDS, *STAGES):
        assert f"  {name} " in out
    stages_part = out.split("Stages (", 1)[1]
    positions = [stages_part.index(f"  {stage} ") for stage in STAGES]
    assert positions == sorted(positions), "stages are listed in lesson order"
    assert "(gist … practice)" in out


def test_schema_prints_the_model_schema(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out) == json_schema()


def test_schema_to_file(workdir: Path) -> None:
    assert main(["schema", "-o", "out/schema.json"]) == 0
    assert json.loads((workdir / "out" / "schema.json").read_text(encoding="utf-8")) == json_schema()


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(LENA)]) == 0
    assert "OK" in capsys.readouterr().out


def test_validate_errors_exit_1(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = lena_data()
    data["tasks"][1]["id"] = "t1"
    assert main(["validate", str(write_json(workdir, "dup.json", data))]) == 1
    out = capsys.readouterr().out
    assert "[duplicate-id]" in out and "/tasks/1/id" in out


def test_validate_json_shape(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = clean_data()
    data["facts"] = []
    data["tasks"][2]["scene"] = "s9"
    assert main(["validate", "--json", str(write_json(workdir, "x.json", data))]) == 1
    report = json.loads(capsys.readouterr().out)
    assert set(report) == {"ok", "error_count", "warning_count", "issues"}
    assert report["ok"] is False
    assert report["error_count"] == 1 and report["warning_count"] == 1
    for issue in report["issues"]:
        assert set(issue) == {"level", "code", "where", "message"}
    assert {(i["code"], i["where"]) for i in report["issues"]} == {
        ("unknown-scene", "/tasks/2/scene"), ("no-facts", "/facts"),
    }


def test_validate_strict(workdir: Path) -> None:
    data = lena_data()
    data["facts"] = []
    path = write_json(workdir, "w.json", data)
    assert main(["validate", str(path)]) == 0
    assert main(["validate", "--strict", str(path)]) == 1


def test_validate_missing_file_and_bad_json(
    workdir: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["validate", "nope.json"]) == 1
    assert "not found" in capsys.readouterr().out
    bad = workdir / "bad.json"
    bad.write_text('{"schema": "langwich/3",', encoding="utf-8")
    assert main(["validate", str(bad)]) == 1
    captured = capsys.readouterr()
    assert "invalid JSON" in captured.out and "Traceback" not in captured.err


def test_validate_legacy_file_points_to_prompt(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(LEGACY)]) == 1
    out = capsys.readouterr().out
    assert "[legacy-format]" in out and "langwich prompt --from-json" in out


def test_validate_prompt_uses_repair_prompt(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    data = clean_data()
    data["tasks"][1]["id"] = "t1"
    path = write_json(workdir, "dup.json", data)
    assert main(["validate", "--prompt", str(path)]) == 1
    assert capsys.readouterr().out.strip() == "REPAIR 1 issues"
    report, text = fake_prompt.items[0]
    assert report.issues[0].code == "duplicate-id"
    assert text == path.read_text(encoding="utf-8")


def test_validate_prompt_when_clean(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    path = write_json(workdir, "clean.json", clean_data())
    assert main(["validate", "--prompt", str(path)]) == 0
    assert fake_prompt.items == []
    assert "nothing to repair" in capsys.readouterr().err


def test_validate_prompt_on_legacy_file_points_to_upgrade(
    fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["validate", "--prompt", str(LEGACY)]) == 1
    assert fake_prompt.items == []
    assert f"langwich prompt --from-json {LEGACY}" in capsys.readouterr().err


def test_validate_json_and_prompt_are_exclusive() -> None:
    assert main(["validate", "--json", "--prompt", str(LENA)]) == 2


def _missing_photo_data(**extra: Any) -> dict[str, Any]:
    """The clean example with its drawing replaced by a photo that is not there."""
    data = clean_data()
    picture = data["story"]["scenes"][1]["picture"]
    picture.pop("svg")
    picture["image"] = "pictures/missing.jpg"
    data.update(extra)
    return data


def test_validate_prompt_with_only_environment_issues(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    path = write_json(workdir, "photo.json", _missing_photo_data())
    codes = {code for code, _ in issue_keys(path)}
    assert codes == {"image-not-found"}, codes
    assert main(["validate", "--prompt", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""                      # no prompt for the LLM
    assert fake_prompt.items == []
    assert "for you to fix (not for the LLM)" in captured.err
    assert "[image-not-found]" in captured.err
    assert "Nothing for the LLM to repair" in captured.err


def test_validate_prompt_leaves_environment_issues_to_the_user(
    workdir: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    data = _missing_photo_data(facts=[])
    path = write_json(workdir, "photo.json", data)
    assert main(["validate", "--prompt", str(path)]) == 1  # image-not-found is an error
    captured = capsys.readouterr()
    assert "[no-facts]" in captured.out and "# Fix this langwich/3 worksheet" in captured.out
    assert "image-not-found" not in captured.out
    assert "[image-not-found]" in captured.err and "leaves out the picture problems" in captured.err


@pytest.mark.parametrize("reply", ["NO PICTURE ATTACHED\n", "NO PICTURE ATTACHED."])
def test_validate_prompt_refuses_the_no_picture_reply(
    workdir: Path, capsys: pytest.CaptureFixture[str], reply: str,
) -> None:
    path = workdir / "nopic.json"
    path.write_text(reply, encoding="utf-8")
    assert main(["validate", "--prompt", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no repair prompt" in captured.err and "NO PICTURE ATTACHED" in captured.err
    assert "picture" in captured.err and "trailing comma" not in captured.err


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def test_render_defaults(workdir: Path, fake_render: Calls, capsys: pytest.CaptureFixture[str]) -> None:
    src = write_json(workdir, "lena.json", lena_data())
    fake_render.image_prompts = [("s2", "A line drawing of a jute sack")]
    fake_render.warnings = ["picture of s3 could not be read"]
    assert main(["render", str(src)]) == 0
    ws, out_pdf, options = fake_render.items[0]
    assert isinstance(ws, Worksheet) and ws.title == "Fünf Tage im Café Lindner"
    assert out_pdf == Path("data") / "lena.pdf"
    assert options == FakeRenderOptions(base_dir=workdir.resolve())
    captured = capsys.readouterr()
    assert "14 tasks, 7 pages -> data/lena.pdf" in captured.out
    assert "Image prompt for scene s2: A line drawing of a jute sack" in captured.out
    assert "warning: picture of s3 could not be read" in captured.err


def test_render_options(workdir: Path, fake_render: Calls, capsys: pytest.CaptureFixture[str]) -> None:
    src = write_json(workdir, "lena.json", lena_data())
    argv = ["render", str(src), "-o", "out/sheet.pdf", "--page", "epaper", "--one-task-per-page",
            "--solutions", "separate", "--no-translations", "--allow-color", "--seed", "42"]
    assert main(argv) == 0
    _, out_pdf, options = fake_render.items[0]
    assert out_pdf == Path("out/sheet.pdf")
    assert options == FakeRenderOptions(
        page="epaper", one_task_per_page=True, solutions="separate", translations=False,
        monochrome=False, seed=42, base_dir=workdir.resolve(), html_only=False,
    )
    assert "solutions: out/sheet-solutions.pdf" in capsys.readouterr().out


def test_render_html_only_and_html_output(workdir: Path, fake_render: Calls) -> None:
    src = write_json(workdir, "lena.json", lena_data())
    assert main(["render", str(src), "--html-only"]) == 0
    assert fake_render.items[-1][2].html_only is True
    assert main(["render", str(src), "-o", "web/lena.html"]) == 0
    _, out_pdf, options = fake_render.items[-1]
    assert out_pdf == Path("web/lena.pdf") and options.html_only is True
    (workdir / "folder").mkdir()
    assert main(["render", str(src), "-o", "folder"]) == 0
    assert fake_render.items[-1][1] == Path("folder") / "lena.pdf"


def test_render_blocks_on_errors(
    workdir: Path, fake_render: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    data = lena_data()
    data["tasks"][4]["items"][0] = "Zuerst werden die Kaffeekirschen von Hand geerntet."
    assert main(["render", str(write_json(workdir, "bad.json", data))]) == 1
    assert fake_render.items == []
    err = capsys.readouterr().err
    assert "[cloze-without-gaps]" in err and "Not rendered" in err


def test_render_warnings_and_strict(
    workdir: Path, fake_render: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    data = lena_data()
    data["facts"] = []
    path = write_json(workdir, "w.json", data)
    assert main(["render", "--strict", str(path)]) == 1
    assert fake_render.items == []
    assert "--strict" in capsys.readouterr().err
    assert main(["render", str(path)]) == 0
    assert len(fake_render.items) == 1
    assert "[no-facts]" in capsys.readouterr().err


def test_render_strict_fails_on_render_warnings(
    workdir: Path, fake_render: Calls, monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = write_json(workdir, "mini.json", clean_data())
    fake_render.warnings = ["scene 's2' picture: the SVG is not valid XML; the picture is left out."]
    both = io.StringIO()  # one stream, as in a terminal: the order is visible
    monkeypatch.setattr(sys, "stdout", both)
    monkeypatch.setattr(sys, "stderr", both)
    assert main(["render", "--strict", str(src)]) == 1
    text = both.getvalue()
    assert len(fake_render.items) == 1  # validation passed, the files were written
    warning = text.index("warning: scene 's2' picture")
    assert warning < text.index("Rendered 'Zu Fuß zur Insel'") < text.index("--strict:")
    # without --strict the same warnings do not fail the command
    assert main(["render", str(src)]) == 0


def test_render_reports_a_broken_picture_apart_from_missing_ones(
    workdir: Path, fake_render: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    src = write_json(workdir, "lena.json", lena_data())
    fake_render.image_prompts = [("s2", "a jute sack"), ("s4", "the café counter")]
    fake_render.warnings = ["scene 's4' picture: the SVG is not valid XML"]
    assert main(["render", str(src)]) == 0
    captured = capsys.readouterr()
    assert "Image prompt for scene s2: a jute sack" in captured.out
    assert "scene s4" not in captured.out  # it has an svg: fix it, do not make a new one
    assert "The picture of scene s4 was given but could not be used" in captured.err


def test_render_missing_file_and_bad_json(
    workdir: Path, fake_render: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["render", "missing.json"]) == 1
    assert "error: file not found: missing.json" in capsys.readouterr().err
    bad = workdir / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert main(["render", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "invalid JSON" in err and "Traceback" not in err
    assert fake_render.items == []


def test_render_weasyprint_missing(
    workdir: Path, fake_render: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    src = write_json(workdir, "lena.json", lena_data())
    fake_render.weasyprint_error = "cannot load library 'libpango-1.0-0'"
    assert main(["render", str(src)]) == 1
    captured = capsys.readouterr()
    assert "-> data/lena.html" in captured.out
    assert "libpango-1.0-0" in captured.err and "brew install pango" in captured.err
    assert "print it to PDF" in captured.err


def test_render_profile_defaults(workdir: Path, fake_render: Calls) -> None:
    write_profile(workdir, {"device": "reMarkable 2", "color": True})
    src = write_json(workdir, "lena.json", lena_data())
    assert main(["render", str(src)]) == 0
    options = fake_render.items[0][2]
    assert options.page == "epaper" and options.monochrome is False
    assert main(["render", str(src), "--page", "a4"]) == 0
    assert fake_render.items[1][2].page == "a4"


def test_render_accepts_bom(workdir: Path, fake_render: Calls) -> None:
    src = workdir / "bom.json"
    src.write_text(LENA.read_text(encoding="utf-8"), encoding="utf-8-sig")
    assert main(["render", str(src)]) == 0


def test_render_crash_is_reported_without_traceback(
    workdir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    mod = types.ModuleType("langwich.render")
    mod.RenderOptions = FakeRenderOptions  # type: ignore[attr-defined]

    def boom(ws: Worksheet, out_pdf: Path, options: Any = None) -> None:
        raise RuntimeError("kaputt")

    mod.render_worksheet = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langwich.render", mod)
    monkeypatch.delenv("LANGWICH_DEBUG", raising=False)
    src = write_json(workdir, "lena.json", lena_data())
    assert main(["render", str(src)]) == 1
    assert "rendering failed (RuntimeError: kaputt)" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Legacy flags
# ---------------------------------------------------------------------------


def test_legacy_from_json_renders(
    workdir: Path, fake_render: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    src = write_json(workdir, "lena.json", lena_data())
    assert main(["--from-json", str(src), "-o", "old.pdf", "--allow-color",
                 "--exercises", "fib_word_bank"]) == 0
    _, out_pdf, options = fake_render.items[0]
    assert out_pdf == Path("old.pdf") and options.monochrome is False
    err = capsys.readouterr().err
    assert "deprecated" in err and f"langwich render {src}" in err
    assert "--exercises is ignored" in err


def test_legacy_v2_file_explains_the_upgrade(
    fake_render: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--from-json", str(LEGACY)]) == 1
    assert fake_render.items == []
    assert f"Upgrade the file with 'langwich prompt --from-json {LEGACY}'" in capsys.readouterr().err


def test_legacy_list_exercises(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list-exercises"]) == 0
    captured = capsys.readouterr()
    assert "cloze" in captured.out and "langwich kinds" in captured.err


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------


def test_prompt_builtin_defaults(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["prompt", "--topic", "coffee"]) == 0
    opts = fake_prompt.items[0]
    # nothing given: None, resolved once by the prompt builder
    assert (opts.source_lang, opts.target_lang, opts.level, opts.frame) == (None,) * 4
    assert resolved(opts) == ("en", "de", "B1", None)
    assert opts.topic == "coffee" and opts.color is False
    captured = capsys.readouterr()
    assert captured.out == "PROMPT en->de B1\n"
    assert "langwich validate data/coffee_en_de.json" in captured.err


def test_prompt_defaults_from_profile(workdir: Path, fake_prompt: Calls) -> None:
    write_profile(workdir, {"source_lang": "FR", "target_lang": "es", "level": "a2",
                            "frame": "diary", "color": True, "device": "epaper"})
    assert main(["prompt"]) == 0
    opts = fake_prompt.items[0]
    assert resolved(opts) == ("fr", "es", "A2", "diary")
    assert opts.color is True


def test_prompt_flags_override_profile(workdir: Path, fake_prompt: Calls) -> None:
    write_profile(workdir, {"source_lang": "fr", "target_lang": "es", "level": "A2",
                            "color": True})
    argv = ["prompt", "--source", "EN", "--target", "it", "--level", "c1", "--frame", "mystery",
            "--no-color", "--scenes", "5", "--compact", "--notes", "no violence",
            "--image", "https://example.org/photo.jpg"]
    assert main(argv) == 0
    opts = fake_prompt.items[0]
    assert (opts.source_lang, opts.target_lang, opts.level, opts.frame) == (
        "en", "it", "C1", "mystery")
    assert resolved(opts) == ("en", "it", "C1", "mystery")
    assert opts.color is False and opts.scenes == 5 and opts.compact is True
    assert opts.notes == "no violence" and opts.image == "https://example.org/photo.jpg"


def test_prompt_invalid_profile_values_are_ignored(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    write_profile(workdir, {"level": "Z9", "target_lang": "German", "frame": "saga"})
    assert main(["prompt"]) == 0
    opts = fake_prompt.items[0]
    assert resolved(opts)[1:] == ("de", "B1", None)
    assert "ignoring profile value" in capsys.readouterr().err


def test_prompt_rejects_bad_arguments(workdir: Path, fake_prompt: Calls) -> None:
    assert main(["prompt", "--level", "B3"]) == 2
    assert main(["prompt", "--source", "de", "--target", "de"]) == 1
    assert main(["prompt", "--target", "en"]) == 1  # the default source is en too
    assert main(["prompt", "--scenes", "0"]) == 2
    assert fake_prompt.items == []


@pytest.mark.parametrize(("scenes", "status"), [("1", 2), ("2", 0), ("7", 0), ("8", 2), ("12", 2)])
def test_prompt_scene_range_matches_the_validator(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str], scenes: str, status: int,
) -> None:
    assert main(["prompt", "--scenes", scenes]) == status
    if status:
        assert "between 2 and 7 scenes" in capsys.readouterr().err
        assert fake_prompt.items == []
    else:
        assert fake_prompt.items[0].scenes == int(scenes)


def test_prompt_continue_uses_previous_episode(workdir: Path, fake_prompt: Calls) -> None:
    write_profile(workdir, {"source_lang": "fr", "target_lang": "es", "level": "A1"})
    assert main(["prompt", "--continue", str(LENA)]) == 0
    opts = fake_prompt.items[0]
    assert isinstance(opts.continue_from, Worksheet)
    assert opts.continue_from.series is not None
    assert opts.continue_from.series.id == "lena-in-wien"
    assert resolved(opts) == ("en", "de", "B1", "episode")


def test_prompt_continue_with_an_explicit_level(
    workdir: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """Levelling a series up: the A2 Valencia episode continued at B1 gives a
    B1 brief, although B1 is also the built-in default."""
    assert main(["prompt", "--continue", str(VALENCIA), "--level", "B1"]) == 0
    out = capsys.readouterr().out
    assert "- Level: B1 (intermediate)" in out and "Use the **B1** row" in out
    assert "Level: A2" not in out
    assert main(["prompt", "--continue", str(VALENCIA)]) == 0
    assert "- Level: A2 (elementary)" in capsys.readouterr().out


def test_prompt_from_json_with_an_explicit_level(
    workdir: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    legacy = json.loads(LEGACY.read_text(encoding="utf-8"))
    legacy["cefr_level"] = "A2"
    path = write_json(workdir, "old_en_de.json", legacy)
    assert main(["prompt", "--from-json", str(path)]) == 0
    assert "- Level: A2" in capsys.readouterr().out
    assert main(["prompt", "--from-json", str(path), "--level", "B1"]) == 0
    out = capsys.readouterr().out
    assert "- Level: B1" in out and "- Level: A2" not in out


def test_prompt_continue_with_invalid_file(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["prompt", "--continue", str(LEGACY)]) == 1
    assert main(["prompt", "--continue", "missing.json"]) == 1
    err = capsys.readouterr().err
    assert "cannot continue from" in err and "Traceback" not in err
    assert fake_prompt.items == []


def test_prompt_from_json_and_from_text(workdir: Path, fake_prompt: Calls) -> None:
    text = workdir / "article.txt"
    text.write_text("Kaffee wächst in den Tropen.", encoding="utf-8")
    assert main(["prompt", "--from-json", str(LEGACY), "--from-text", str(text)]) == 0
    opts = fake_prompt.items[0]
    assert isinstance(opts.from_legacy, dict) and "content" in opts.from_legacy
    assert opts.from_text == "Kaffee wächst in den Tropen."


def test_prompt_from_json_errors(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    bad = workdir / "bad.json"
    bad.write_text("[1, 2", encoding="utf-8")
    assert main(["prompt", "--from-json", str(bad)]) == 1
    listing = write_json(workdir, "list.json", [1, 2])
    assert main(["prompt", "--from-json", str(listing)]) == 1
    assert main(["prompt", "--from-text", "nope.txt"]) == 1
    err = capsys.readouterr().err
    assert "not valid JSON" in err and "JSON object" in err and "not found" in err
    assert fake_prompt.items == []


def _picture(path: Path, fmt: str = "PNG", size: tuple[int, int] = (64, 48)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 120, 40)).save(path, fmt)
    return path


def test_prompt_missing_local_image_is_an_error(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["prompt", "--image", "holiday.jpg"]) == 1
    assert "picture not found: holiday.jpg" in capsys.readouterr().err
    (workdir / "folder.jpg").mkdir()
    assert main(["prompt", "--image", "folder.jpg"]) == 1
    assert "is a folder" in capsys.readouterr().err
    assert fake_prompt.items == []


def test_prompt_image_is_copied_into_data_pictures(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    """A path with spaces becomes a short relative path: the copy in
    data/pictures/ under an ASCII slug, named "pictures/<file>" in the prompt."""
    photo = _picture(workdir / "My Photos" / "Holiday 2026 Valencia market"
                     / "stall at the Mercado Central.png")
    assert main(["prompt", "--image", str(photo)]) == 0
    copy_ = workdir / "data" / "pictures" / "stall-at-the-mercado-central.png"
    assert copy_.read_bytes() == photo.read_bytes()  # PNG is copied as it is
    assert fake_prompt.items[-1].image == "pictures/stall-at-the-mercado-central.png"
    err = capsys.readouterr().err
    assert "with the picture data/pictures/stall-at-the-mercado-central.png attached" in err
    assert "save the JSON it writes in data/" in err
    # the same picture again: the copy is reused, not duplicated
    assert main(["prompt", "--image", str(photo)]) == 0
    assert sorted(p.name for p in copy_.parent.iterdir()) == [copy_.name]
    # another picture with the same name gets its own file
    other = _picture(workdir / "other" / "stall at the Mercado Central.png", size=(10, 10))
    assert main(["prompt", "--image", str(other)]) == 0
    assert fake_prompt.items[-1].image == "pictures/stall-at-the-mercado-central-2.png"


def test_prompt_image_with_a_windows_style_path(
    workdir: Path, fake_prompt: Calls,
) -> None:
    # On Windows this is a folder and a file; elsewhere one file name with
    # backslashes. Either way the prompt gets a clean relative path.
    name = "Urlaub 2025\\IMG_2034.JPG"
    _picture(workdir / name, "JPEG")
    assert main(["prompt", "--image", name]) == 0
    assert fake_prompt.items[-1].image == "pictures/img-2034.jpg"
    assert (workdir / "data" / "pictures" / "img-2034.jpg").is_file()


def test_prompt_image_in_another_format_is_converted_to_jpeg(
    workdir: Path, fake_prompt: Calls,
) -> None:
    from PIL import Image

    _picture(workdir / "scan.tiff", "TIFF")
    assert main(["prompt", "--image", "scan.tiff", "--data-dir", "sheets"]) == 0
    assert fake_prompt.items[-1].image == "pictures/scan.jpg"
    with Image.open(workdir / "sheets" / "pictures" / "scan.jpg") as img:
        assert img.format == "JPEG" and img.size == (64, 48)


def test_prompt_image_that_cannot_be_read(
    workdir: Path, fake_prompt: Calls, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import langwich.cli

    monkeypatch.setattr(langwich.cli, "_register_heif", lambda: None)  # as without pillow-heif
    heic = workdir / "IMG_4711.HEIC"
    heic.write_bytes(b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64)
    assert main(["prompt", "--image", str(heic)]) == 1
    err = capsys.readouterr().err
    assert "HEIC" in err and "JPEG" in err and "pip install pillow-heif" in err
    (workdir / "notes.jpg").write_text("not a picture", encoding="utf-8")
    assert main(["prompt", "--image", "notes.jpg"]) == 1
    assert "not an image format langwich can read" in capsys.readouterr().err
    broken = workdir / "broken.png"
    broken.write_bytes(_picture(workdir / "ok.png").read_bytes()[:60])
    assert main(["prompt", "--image", str(broken)]) == 1
    assert "damaged or incomplete" in capsys.readouterr().err
    assert fake_prompt.items == []
    assert not (workdir / "data" / "pictures" / "img-4711.jpg").exists()


def test_prompt_image_url_is_passed_through(workdir: Path, fake_prompt: Calls) -> None:
    url = "https://example.org/photos/market%20stall.jpg"
    assert main(["prompt", "--image", url]) == 0
    assert fake_prompt.items[-1].image == url
    assert not (workdir / "data").exists()


def test_real_prompt_names_the_copied_picture_relatively(
    workdir: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    photo = _picture(workdir / "Mein Urlaub" / "Wien Café 2025.jpg", "JPEG")
    assert main(["prompt", "--image", str(photo), "--topic", "a café in Vienna"]) == 0
    out = capsys.readouterr().out
    assert '"image": "pictures/wien-cafe-2025.jpg"' in out.splitlines()
    assert str(workdir) not in out and "Mein Urlaub" not in out


def test_prompt_output_file_and_save_profile(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    write_profile(workdir, {"device": "epaper", "name": "Jörn"})
    argv = ["prompt", "--target", "fr", "--level", "A2", "--frame", "letters", "--color",
            "-o", "prompts/p.txt", "--save-profile"]
    assert main(argv) == 0
    assert (workdir / "prompts" / "p.txt").read_text(encoding="utf-8") == "PROMPT en->fr A2\n"
    assert capsys.readouterr().out == ""
    profile = json.loads((workdir / ".langwich" / "profile.json").read_text(encoding="utf-8"))
    # never the frame: it is a choice per story
    assert profile == {"device": "epaper", "name": "Jörn", "source_lang": "en",
                       "target_lang": "fr", "level": "A2", "color": True}


@pytest.mark.parametrize("argv", [
    ["--frame", "episode", "--topic", "a bakery"],
    ["--continue", str(LENA)],        # the frame of the previous episode is not saved either
])
def test_save_profile_never_writes_the_frame(
    workdir: Path, fake_prompt: Calls, argv: list[str],
) -> None:
    assert main(["prompt", *argv, "--save-profile"]) == 0
    profile = load_profile(workdir)
    assert "frame" not in profile
    assert profile["level"] == "B1" and profile["target_lang"] == "de"
    # so a later plain brief is not a series opener
    assert main(["prompt", "--topic", "volcanoes"]) == 0
    assert resolved(fake_prompt.items[-1])[3] is None


def test_save_profile_keeps_a_frame_added_by_hand(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    write_profile(workdir, {"frame": "episode"})
    assert main(["prompt", "--target", "fr", "--save-profile"]) == 0
    assert load_profile(workdir)["frame"] == "episode"
    assert resolved(fake_prompt.items[-1])[3] == "episode"
    err = capsys.readouterr().err
    assert "the frame 'episode' comes from .langwich/profile.json" in err


def test_frames_match_the_model() -> None:
    assert "episode" in FRAMES and "mystery" in FRAMES and len(FRAMES) == 8


# ---------------------------------------------------------------------------
# profile.py
# ---------------------------------------------------------------------------


def test_profile_roundtrip(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert load_profile(tmp_path) == {}
    path = save_profile({"target_lang": "de", "level": "B1"}, tmp_path)
    assert path == tmp_path / ".langwich" / "profile.json"
    assert load_profile(tmp_path) == {"target_lang": "de", "level": "B1"}


def test_profile_is_found_upwards_until_git(tmp_path: Path) -> None:
    project = tmp_path / "project"
    deep = project / "a" / "b"
    deep.mkdir(parents=True)
    (project / ".git").mkdir()
    write_profile(tmp_path, {"level": "C2"})  # outside the project: never read
    assert load_profile(deep) == {}
    write_profile(project, {"level": "A2"})
    assert find_profile(deep) == (project / ".langwich" / "profile.json").resolve()
    assert load_profile(deep) == {"level": "A2"}


def test_profile_invalid_content_is_empty(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".langwich").mkdir()
    target = tmp_path / ".langwich" / "profile.json"
    target.write_text("{broken", encoding="utf-8")
    assert load_profile(tmp_path) == {}
    target.write_text("[1, 2]", encoding="utf-8")
    assert load_profile(tmp_path) == {}


def test_profile_saves_no_frame_but_reads_one() -> None:
    from langwich.profile import KNOWN_KEYS, SAVED_KEYS

    assert "frame" in KNOWN_KEYS and "frame" not in SAVED_KEYS
    assert set(SAVED_KEYS) == {"source_lang", "target_lang", "level", "color", "device"}


def test_profile_uses_cwd_by_default(workdir: Path) -> None:
    save_profile({"frame": "diary"})
    assert load_profile() == {"frame": "diary"}
    assert (workdir / ".langwich" / "profile.json").is_file()


# ---------------------------------------------------------------------------
# With the real renderer / prompt builder
# ---------------------------------------------------------------------------


def _real(module: str, attr: str) -> Any:
    """The real module; skipped when it cannot be imported (e.g. WeasyPrint's
    libraries are missing) — a failure when LANGWICH_REQUIRE_PDF is set (CI)."""
    try:
        mod = importlib.import_module(module)
    except ImportError as exc:
        if os.environ.get("LANGWICH_REQUIRE_PDF"):
            pytest.fail(f"{module} cannot be imported ({exc}) but LANGWICH_REQUIRE_PDF is set")
        pytest.skip(f"{module} cannot be imported: {exc}")
    assert hasattr(mod, attr), f"{module} does not provide {attr}"
    return mod


def test_real_render_html_only(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _real("langwich.render", "RenderOptions")
    out = workdir / "out" / "lena.pdf"
    assert main(["render", str(LENA), "-o", str(out), "--html-only"]) == 0
    html = out.with_suffix(".html")
    assert html.is_file()
    assert "Fünf Tage im Café Lindner" in html.read_text(encoding="utf-8")
    assert "Rendered 'Fünf Tage im Café Lindner'" in capsys.readouterr().out


def test_real_prompt(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _real("langwich.prompt", "build_prompt")
    assert main(["prompt", "--target", "de", "--topic", "coffee"]) == 0
    assert "langwich/3" in capsys.readouterr().out


def test_real_repair_prompt(workdir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _real("langwich.prompt", "repair_prompt")
    data = copy.deepcopy(lena_data())
    data["tasks"][1]["id"] = "t1"
    path = write_json(workdir, "dup.json", data)
    assert main(["validate", "--prompt", str(path)]) == 1
    assert capsys.readouterr().out.strip()  # the wording belongs to prompt.py


def test_prompt_series_and_device_flags(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["prompt", "--frame", "mystery", "--series", "--device", "color",
                 "--save-profile"]) == 0
    opts = fake_prompt.items[-1]
    assert opts.series is True and opts.color is True
    saved = json.loads((workdir / ".langwich" / "profile.json").read_text(encoding="utf-8"))
    assert saved["device"] == "color"
    assert main(["prompt", "--frame", "episode", "--no-series"]) == 0
    assert fake_prompt.items[-1].series is False


def test_prompt_continue_suggests_next_episode_file(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    prev = workdir / "lena_01_en_de.json"
    prev.write_text((REPO_ROOT / "examples" / "lena_01_en_de.json").read_text(encoding="utf-8"),
                    encoding="utf-8")
    assert main(["prompt", "--continue", str(prev)]) == 0
    err = capsys.readouterr().err
    assert "e.g. as data/lena_02_en_de.json" in err
    assert "langwich validate data/lena_02_en_de.json" in err


def test_prompt_continue_file_name_follows_series_episode(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    data = lena_data()
    data["series"]["episode"] = 5
    prev = write_json(workdir, "lena_01_en_de.json", data)
    assert main(["prompt", "--continue", str(prev)]) == 0
    assert "e.g. as data/lena_06_en_de.json" in capsys.readouterr().err
    # a one-off continued as a series: <series>_<nn>_<src>_<tgt>.json
    oneoff = write_json(workdir, "mercado_valencia_en_es.json",
                        json.loads(VALENCIA.read_text(encoding="utf-8")))
    assert main(["prompt", "--continue", str(oneoff)]) == 0
    assert "data/mercado_valencia_02_en_es.json" in capsys.readouterr().err
    # an existing next episode is not overwritten silently
    (workdir / "data").mkdir()
    (workdir / "data" / "lena_06_en_de.json").write_text("{}", encoding="utf-8")
    assert main(["prompt", "--continue", str(prev)]) == 0
    assert "data/lena_06_en_de.json already exists" in capsys.readouterr().err


def test_prompt_suggests_documented_file_names(
    workdir: Path, fake_prompt: Calls, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["prompt", "--topic", "Sourdough bread", "--target", "fr"]) == 0
    assert "e.g. as data/sourdough_bread_en_fr.json" in capsys.readouterr().err
    assert main(["prompt", "--topic", "Sourdough bread", "--frame", "episode"]) == 0
    assert "e.g. as data/sourdough_bread_01_en_de.json" in capsys.readouterr().err
    assert main(["prompt", "--from-json", str(LEGACY)]) == 0
    assert "e.g. as data/coffee_en_de.json" in capsys.readouterr().err
    # never an existing worksheet
    (workdir / "data").mkdir()
    (workdir / "data" / "sourdough_bread_en_de.json").write_text("{}", encoding="utf-8")
    assert main(["prompt", "--topic", "Sourdough bread"]) == 0
    assert "e.g. as data/sourdough_bread-2_en_de.json" in capsys.readouterr().err
