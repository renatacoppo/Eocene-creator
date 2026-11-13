"""Unit tests for the step runner, the run context and the stage step."""

import logging
from pathlib import Path

import pytest

from ecefast.core.config import ConfigError
from ecefast.core.steps import ComponentStep, PipelineError, run_pipeline
from ecefast.core import workspace
from ecefast.core.workspace import Context, Stage
from synthetic import make_config

pytestmark = pytest.mark.unit


@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    for name in ("input", "herold"):
        (tmp_path / name).mkdir()
    (tmp_path / "input" / "a.txt").write_text("a")
    (tmp_path / "out").mkdir()
    return Context(make_config(tmp_path), "eocene")


def make_step(name: str, needs=(), reads=(), writes=(), ran=None) -> type[ComponentStep]:
    """A dummy step that writes a tiny file for each of its ``writes``."""

    class Dummy(ComponentStep):
        """Dummy step."""

        def __init__(self, ctx):
            self.ctx = ctx

        @classmethod
        def from_context(cls, ctx):
            return cls(ctx)

        def run(self):
            if ran is not None:
                ran.append(self.name)
            for template in self.writes:
                Path(self.ctx.expand(template)).write_text(self.name)

    Dummy.name, Dummy.needs, Dummy.reads, Dummy.writes = name, list(needs), list(reads), list(writes)
    return Dummy


def outputs(ctx: Context) -> list[str]:
    return sorted(p.name for p in Path(ctx.section.output).iterdir())


# --- runner --------------------------------------------------------------------------------------------------------


def test_runs_steps_in_order_and_checks_writes(ctx: Context) -> None:
    ran = []
    a = make_step("a", reads=["{input}/a.txt"], writes=["{output}/a.txt"], ran=ran)
    b = make_step("b", needs=["a"], reads=["{output}/a.txt"], writes=["{output}/b.txt"], ran=ran)
    assert run_pipeline([a, b], ctx) == ["a", "b"]
    assert ran == ["a", "b"]
    assert outputs(ctx) == ["a.txt", "b.txt"]


def test_need_after_step_is_an_error(ctx: Context) -> None:
    a = make_step("a", writes=["{output}/a.txt"])
    b = make_step("b", needs=["a"])
    with pytest.raises(PipelineError, match="'b' needs 'a', which must come before it"):
        run_pipeline([b, a], ctx)


def test_unknown_need_is_an_error(ctx: Context) -> None:
    with pytest.raises(PipelineError, match="'b' needs 'x', which is not in the pipeline"):
        run_pipeline([make_step("b", needs=["x"])], ctx)


def test_missing_reads_are_all_listed_and_nothing_is_written(ctx: Context) -> None:
    ran = []
    a = make_step("a", reads=["{input}/missing1.nc"], writes=["{output}/a.txt"], ran=ran)
    b = make_step(
        "bb",
        reads=["{input}/a.txt", "{herold}/missing2.nc"],
        writes=["{output}/b.txt"],
        ran=ran,
    )
    with pytest.raises(PipelineError) as err:
        run_pipeline([a, b], ctx)
    message = str(err.value)
    assert message.splitlines()[0] == "Cannot start: 2 input files are missing. Nothing was written."
    assert f"  a   needs  {ctx.section.input}/missing1.nc" in message
    assert f"  bb  needs  {ctx.section.herold}/missing2.nc" in message
    assert ran == []
    assert outputs(ctx) == []


def test_one_missing_read_is_singular(ctx: Context) -> None:
    with pytest.raises(PipelineError, match="1 input file is missing"):
        run_pipeline([make_step("a", reads=["{input}/nope"])], ctx)


def test_missing_read_shows_its_source(ctx: Context) -> None:
    """A missing read listed in ``sources`` gets a line saying where to get it; the others do not."""
    a = make_step("a", reads=["{herold}/age.xyadb", "{input}/other.nc"])
    a.sources = {"{herold}/age.xyadb": "https://example.org/age.xyadb.bz2"}
    with pytest.raises(PipelineError) as err:
        run_pipeline([a], ctx)
    assert str(err.value).splitlines()[1:] == [
        f"  a  needs  {ctx.section.herold}/age.xyadb",
        "     get it from https://example.org/age.xyadb.bz2",
        f"  a  needs  {ctx.section.input}/other.nc",
    ]


def test_read_written_by_earlier_step_is_not_missing(ctx: Context) -> None:
    a = make_step("a", writes=["{output}/a.txt"])
    b = make_step("b", needs=["a"], reads=["{output}/a.txt"])
    run_pipeline([a, b], ctx)


def test_read_inside_directory_written_by_earlier_step_is_not_missing(ctx: Context) -> None:
    class MakeDir(ComponentStep):
        """Make a directory."""

        name, writes = "dir", ["{output}/d"]

        @classmethod
        def from_context(cls, ctx):
            step = cls()
            step.path = ctx.expand("{output}/d/x.txt")
            return step

        def run(self):
            Path(self.path).parent.mkdir()
            Path(self.path).write_text("x")

    b = make_step("b", needs=["dir"], reads=["{output}/d/x.txt"])
    run_pipeline([MakeDir, b], ctx)


def test_dry_run_writes_nothing(ctx: Context, caplog: pytest.LogCaptureFixture) -> None:
    ran = []
    a = make_step("a", reads=["{input}/a.txt"], writes=["{output}/a.txt"], ran=ran)
    with caplog.at_level(logging.DEBUG, logger="ecefast"):
        assert run_pipeline([a], ctx, dry_run=True) == ["a"]
    assert ran == []
    assert outputs(ctx) == []
    plan = {r.getMessage().strip(): r.levelno for r in caplog.records}
    assert plan["a  Dummy step."] == logging.INFO  # the step at INFO
    assert plan[f"→ {ctx.section.output}/a.txt"] == logging.DEBUG  # its files at DEBUG


def test_dry_run_recaps_files_by_place(ctx: Context, caplog: pytest.LogCaptureFixture) -> None:
    a = make_step("a", writes=["{output}/a.txt"])
    tmpfile = f"{ctx.config.machine.tmpdir}/present/nemo/b.nc"
    elsewhere = "/somewhere/else/namelist_cfg"
    a.planned_writes = lambda self: [tmpfile, elsewhere, f"{ctx.section.output}/a.txt"]  # a.txt only once
    Path(tmpfile).parent.mkdir(parents=True)
    Path(tmpfile).write_text("x")
    with caplog.at_level(logging.INFO, logger="ecefast"):
        run_pipeline([a], ctx, dry_run=True)
    recap = caplog.text[caplog.text.index("Files that would be written") :]
    assert "Files that would be written (3):" in recap
    assert f"in {ctx.period}.output ({ctx.section.output}):\n    a.txt\n" in recap
    assert f"in machine.tmpdir ({ctx.config.machine.tmpdir}):\n    present/nemo/b.nc  (exists)\n" in recap
    assert f"elsewhere:\n    {elsewhere}" in recap


def test_run_recaps_written_files(ctx: Context, caplog: pytest.LogCaptureFixture) -> None:
    a = make_step("a", writes=["{output}/a.txt"])
    a.planned_writes = lambda self: [f"{ctx.section.output}/never.txt"]
    with caplog.at_level(logging.INFO, logger="ecefast"):
        run_pipeline([a], ctx)
    assert "Files written (2):" in caplog.text
    assert "    a.txt\n" in caplog.text
    assert "    never.txt  (not found)" in caplog.text


def test_dry_run_still_checks_reads(ctx: Context) -> None:
    with pytest.raises(PipelineError, match="Cannot start"):
        run_pipeline([make_step("a", reads=["{input}/nope"])], ctx, dry_run=True)


def test_select_runs_only_selected(ctx: Context) -> None:
    ran = []
    a = make_step("a", writes=["{output}/a.txt"], ran=ran)
    b = make_step("b", writes=["{output}/b.txt"], ran=ran)
    c = make_step("c", writes=["{output}/c.txt"], ran=ran)
    assert run_pipeline([a, b, c], ctx, select=["c", "a"]) == ["a", "c"]
    assert ran == ["a", "c"]


def test_select_unknown_step_is_an_error(ctx: Context) -> None:
    with pytest.raises(PipelineError, match="Unknown step"):
        run_pipeline([make_step("a")], ctx, select=["x"])


def test_unselected_need_without_outputs_is_an_error(ctx: Context) -> None:
    a = make_step("a", writes=["{output}/a.txt"])
    b = make_step("b", needs=["a"], writes=["{output}/b.txt"])
    with pytest.raises(PipelineError, match="'b' needs 'a', which is not selected and has not run before"):
        run_pipeline([a, b], ctx, select=["b"])
    assert outputs(ctx) == []


def test_unselected_need_with_outputs_is_allowed(ctx: Context) -> None:
    ran = []
    a = make_step("a", writes=["{output}/a.txt"], ran=ran)
    b = make_step("b", needs=["a"], reads=["{output}/a.txt"], writes=["{output}/b.txt"], ran=ran)
    (Path(ctx.section.output) / "a.txt").write_text("from an earlier run")
    run_pipeline([a, b], ctx, select=["b"])
    assert ran == ["b"]


def test_missing_write_after_run_is_an_error(ctx: Context) -> None:
    class Lazy(ComponentStep):
        """Writes nothing."""

        name, writes = "lazy", ["{output}/never.txt"]

        @classmethod
        def from_context(cls, ctx):
            return cls()

        def run(self):
            pass

    with pytest.raises(PipelineError, match=r"Step 'lazy' did not write: .*never\.txt"):
        run_pipeline([Lazy], ctx)


def test_write_into_input_is_refused_before_start(ctx: Context) -> None:
    ran = []
    a = make_step("a", writes=["{input}/a.txt"], ran=ran)
    with pytest.raises(PipelineError, match="Step 'a' would write .* read-only '(present|eocene).input'"):
        run_pipeline([a], ctx)
    assert ran == []


def test_eocene_starting_from_present_output(tmp_path: Path) -> None:
    """With ``eocene.input: "{present.output}"`` the present day still writes its own output, and the Eocene may
    not write into it."""
    config = make_config(tmp_path)
    config.eocene.input = config.present.output
    present = Context(config, "present")
    present.check_writable(present.expand("{output}/a.txt"))
    eocene = Context(config, "eocene")
    with pytest.raises(PipelineError, match="read-only 'eocene.input'"):
        eocene.check_writable(present.expand("{output}/a.txt"))


def test_base_class_must_be_overridden() -> None:
    with pytest.raises(NotImplementedError):
        ComponentStep.from_context(None)
    with pytest.raises(NotImplementedError):
        ComponentStep().run()


# --- context -------------------------------------------------------------------------------------------------------


def test_expand_placeholders(ctx: Context) -> None:
    """Keys of the running period without its name, then keys of the whole file."""
    eocene = ctx.config.eocene
    assert ctx.expand("{input}/oifs/{grids.oifs.name}/x") == f"{eocene.input}/oifs/TL63L31/x"
    assert ctx.expand("{output}/oasis/{grids.nemo.name}/rstos.nc") == f"{eocene.output}/oasis/PALEORCA2/rstos.nc"
    assert ctx.expand("{herold}/h.nc") == f"{eocene.herold}/h.nc"
    assert ctx.expand("{nemo.domain}/x") == f"{eocene.nemo.domain}/x"
    assert ctx.expand("{present.output}/x") == f"{ctx.config.present.output}/x"
    assert ctx.expand("{machine.tmpdir}/t.nc") == f"{ctx.config.machine.tmpdir}/t.nc"
    assert ctx.expand("/plain/path") == "/plain/path"


def test_expand_in_another_period(ctx: Context) -> None:
    present = Context(ctx.config, "present")
    assert present.expand("{input}/x") == f"{ctx.config.present.input}/x"
    assert present.expand("{output}/x") == f"{ctx.config.present.output}/x"
    with pytest.raises(ConfigError, match="unknown key 'herold'"):
        present.expand("{herold}/x")


def test_expand_unknown_placeholder(ctx: Context) -> None:
    with pytest.raises(ConfigError, match=r"unknown key 'inputs.ece4' in placeholder \{inputs.ece4\}"):
        ctx.expand("{inputs.ece4}/x")


def test_tmpdir_per_period_and_component(ctx: Context) -> None:
    assert ctx.tmpdir("oifs") == f"{ctx.config.machine.tmpdir}/eocene/oifs"


@pytest.mark.parametrize("template", ["{input}", "{input}/a.txt", "{herold}/sub/x.nc"])
def test_check_writable_refuses_read_only_roots(ctx: Context, template: str) -> None:
    with pytest.raises(PipelineError, match="read-only"):
        ctx.check_writable(ctx.expand(template), "s")


def test_check_writable_allows_output_and_tmpdir(ctx: Context) -> None:
    ctx.check_writable(ctx.expand("{output}/x.nc"))
    ctx.check_writable(ctx.tmpdir("nemo") + "/x.nc")
    # a sibling whose name starts with the root name is not inside it
    ctx.check_writable(ctx.section.input + "-copy/x.nc")


def test_check_writable_follows_symlinks(ctx: Context, tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(ctx.section.input)
    with pytest.raises(PipelineError, match="read-only '(eocene|present).input'"):
        ctx.check_writable(str(link / "x.nc"))


# --- stage ---------------------------------------------------------------------------------------------------------


def input_tree(root: Path) -> None:
    """A tiny input tree with the kept and the skipped subdirectories."""
    for sub in [
        "oifs/TL63L31",
        "oifs/TL255L91",
        "oifs/ifsdata",
        "nemo/initial",
        "nemo/domain",
        "oasis/PALEORCA2",
        "oasis/ORCA1",
        "runoff-mapper",
        "cmip6-data",
    ]:
        (root / sub).mkdir(parents=True, exist_ok=True)
        (root / sub / "f.txt").write_text(sub)


def test_stage_copies_the_subset(ctx: Context, caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    """With --overwrite a tree holding files is replaced, after a warning and a pause (no pause in tests)."""
    monkeypatch.setattr(workspace, "OVERWRITE_PAUSE", 0)
    input_tree(Path(ctx.section.input))
    out = Path(ctx.section.output)
    (out / "old.txt").write_text("overwritten")
    ctx.overwrite = True
    with caplog.at_level(logging.WARNING, logger="ecefast"):
        run_pipeline([Stage], ctx)
    assert f"Step 'stage' (--overwrite) replaces {out}" in caplog.text
    copied = sorted(str(p.relative_to(out)) for p in out.rglob("f.txt"))
    assert copied == [
        "nemo/initial/f.txt",
        "oasis/PALEORCA2/f.txt",
        "oifs/TL63L31/f.txt",
        "oifs/ifsdata/f.txt",
        "runoff-mapper/f.txt",
    ]
    assert (out / "cmip6-data").is_symlink()
    assert (out / "cmip6-data" / "f.txt").read_text() == "cmip6-data"
    assert not (out / "old.txt").exists()


def test_stage_refuses_non_empty_output_without_overwrite(ctx: Context) -> None:
    input_tree(Path(ctx.section.input))
    out = Path(ctx.section.output)
    (out / "old.txt").write_text("kept")
    with pytest.raises(PipelineError, match="is not empty"):
        run_pipeline([Stage], ctx)
    assert outputs(ctx) == ["old.txt"]


def test_stage_accepts_output_with_empty_folders(ctx: Context) -> None:
    """Empty folders (made by the preflight of later steps) do not count as an earlier output."""
    input_tree(Path(ctx.section.input))
    (Path(ctx.section.output) / "oifs" / "TL63L31").mkdir(parents=True)
    run_pipeline([Stage], ctx)
    assert (Path(ctx.section.output) / "oifs" / "TL63L31" / "f.txt").exists()


def test_stage_refuses_output_containing_input(tmp_path: Path) -> None:
    (tmp_path / "out" / "input").mkdir(parents=True)
    stage = Stage(str(tmp_path / "out" / "input"), str(tmp_path / "out"), "TL63L31", "PALEORCA2")
    with pytest.raises(ValueError, match="is or contains the input directory"):
        stage.run()
    assert (tmp_path / "out" / "input").is_dir()


def test_stage_preflight_reports_missing_input(ctx: Context) -> None:
    with pytest.raises(PipelineError, match="4 input files are missing"):
        run_pipeline([Stage], ctx)


def test_stage_follows_symlinks(ctx: Context) -> None:
    """A link to a file outside the copied folders (oasis/<grid>/rstos.nc -> initial_state/ in ECE4-DATA 4.1.10)
    becomes a real file in the output."""
    root = Path(ctx.section.input)
    input_tree(root)
    (root / "initial_state").mkdir()
    (root / "initial_state" / "rstos.nc").write_text("rstos")
    (root / "oasis" / "PALEORCA2" / "rstos.nc").symlink_to("../../initial_state/rstos.nc")
    run_pipeline([Stage], ctx)
    copied = Path(ctx.section.output) / "oasis" / "PALEORCA2" / "rstos.nc"
    assert not copied.is_symlink() and copied.read_text() == "rstos"
