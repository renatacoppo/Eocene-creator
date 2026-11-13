"""Unit tests for the step runner, the run context and the stage step."""

import logging
from pathlib import Path

import pytest

from ecefast.core.config import ConfigError
from ecefast.core.steps import ComponentStep, PipelineError, run_pipeline
from ecefast.core.workspace import Context, Stage
from synthetic import make_config

pytestmark = pytest.mark.unit


@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    for name in ("input", "herold"):
        (tmp_path / name).mkdir()
    (tmp_path / "input" / "a.txt").write_text("a")
    (tmp_path / "out").mkdir()
    return Context(make_config(tmp_path, tmpdir=str(tmp_path / "tmp")))


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
    return sorted(p.name for p in Path(ctx.config.eocene.output_dir).iterdir())


# --- runner --------------------------------------------------------------------------------------------------------


def test_runs_steps_in_order_and_checks_writes(ctx: Context) -> None:
    ran = []
    a = make_step("a", reads=["{inputs.ece4_data}/a.txt"], writes=["{eocene.output_dir}/a.txt"], ran=ran)
    b = make_step("b", needs=["a"], reads=["{eocene.output_dir}/a.txt"], writes=["{eocene.output_dir}/b.txt"], ran=ran)
    assert run_pipeline([a, b], ctx) == ["a", "b"]
    assert ran == ["a", "b"]
    assert outputs(ctx) == ["a.txt", "b.txt"]


def test_need_after_step_is_an_error(ctx: Context) -> None:
    a = make_step("a", writes=["{eocene.output_dir}/a.txt"])
    b = make_step("b", needs=["a"])
    with pytest.raises(PipelineError, match="'b' needs 'a', which must come before it"):
        run_pipeline([b, a], ctx)


def test_unknown_need_is_an_error(ctx: Context) -> None:
    with pytest.raises(PipelineError, match="'b' needs 'x', which is not in the pipeline"):
        run_pipeline([make_step("b", needs=["x"])], ctx)


def test_missing_reads_are_all_listed_and_nothing_is_written(ctx: Context) -> None:
    ran = []
    a = make_step("a", reads=["{inputs.ece4_data}/missing1.nc"], writes=["{eocene.output_dir}/a.txt"], ran=ran)
    b = make_step(
        "bb",
        reads=["{inputs.ece4_data}/a.txt", "{inputs.herold}/missing2.nc"],
        writes=["{eocene.output_dir}/b.txt"],
        ran=ran,
    )
    with pytest.raises(PipelineError) as err:
        run_pipeline([a, b], ctx)
    message = str(err.value)
    assert message.splitlines()[0] == "Cannot start: 2 input files are missing. Nothing was written."
    assert f"  a   needs  {ctx.config.inputs.ece4_data}/missing1.nc" in message
    assert f"  bb  needs  {ctx.config.inputs.herold}/missing2.nc" in message
    assert ran == []
    assert outputs(ctx) == []


def test_one_missing_read_is_singular(ctx: Context) -> None:
    with pytest.raises(PipelineError, match="1 input file is missing"):
        run_pipeline([make_step("a", reads=["{inputs.ece4_data}/nope"])], ctx)


def test_missing_read_shows_its_source(ctx: Context) -> None:
    """A missing read listed in ``sources`` gets a line saying where to get it; the others do not."""
    a = make_step("a", reads=["{inputs.herold}/age.xyadb", "{inputs.ece4_data}/other.nc"])
    a.sources = {"{inputs.herold}/age.xyadb": "https://example.org/age.xyadb.bz2"}
    with pytest.raises(PipelineError) as err:
        run_pipeline([a], ctx)
    assert str(err.value).splitlines()[1:] == [
        f"  a  needs  {ctx.config.inputs.herold}/age.xyadb",
        "     get it from https://example.org/age.xyadb.bz2",
        f"  a  needs  {ctx.config.inputs.ece4_data}/other.nc",
    ]


def test_read_written_by_earlier_step_is_not_missing(ctx: Context) -> None:
    a = make_step("a", writes=["{eocene.output_dir}/a.txt"])
    b = make_step("b", needs=["a"], reads=["{eocene.output_dir}/a.txt"])
    run_pipeline([a, b], ctx)


def test_read_inside_directory_written_by_earlier_step_is_not_missing(ctx: Context) -> None:
    class MakeDir(ComponentStep):
        """Make a directory."""

        name, writes = "dir", ["{eocene.output_dir}/d"]

        @classmethod
        def from_context(cls, ctx):
            step = cls()
            step.path = ctx.expand("{eocene.output_dir}/d/x.txt")
            return step

        def run(self):
            Path(self.path).parent.mkdir()
            Path(self.path).write_text("x")

    b = make_step("b", needs=["dir"], reads=["{eocene.output_dir}/d/x.txt"])
    run_pipeline([MakeDir, b], ctx)


def test_dry_run_writes_nothing(ctx: Context, caplog: pytest.LogCaptureFixture) -> None:
    ran = []
    a = make_step("a", reads=["{inputs.ece4_data}/a.txt"], writes=["{eocene.output_dir}/a.txt"], ran=ran)
    with caplog.at_level(logging.INFO, logger="ecefast"):
        assert run_pipeline([a], ctx, dry_run=True) == ["a"]
    assert ran == []
    assert outputs(ctx) == []
    assert f"Dummy step.  → {ctx.config.eocene.output_dir}/a.txt" in caplog.text


def test_dry_run_still_checks_reads(ctx: Context) -> None:
    with pytest.raises(PipelineError, match="Cannot start"):
        run_pipeline([make_step("a", reads=["{inputs.ece4_data}/nope"])], ctx, dry_run=True)


def test_select_runs_only_selected(ctx: Context) -> None:
    ran = []
    a = make_step("a", writes=["{eocene.output_dir}/a.txt"], ran=ran)
    b = make_step("b", writes=["{eocene.output_dir}/b.txt"], ran=ran)
    c = make_step("c", writes=["{eocene.output_dir}/c.txt"], ran=ran)
    assert run_pipeline([a, b, c], ctx, select=["c", "a"]) == ["a", "c"]
    assert ran == ["a", "c"]


def test_select_unknown_step_is_an_error(ctx: Context) -> None:
    with pytest.raises(PipelineError, match="Unknown step"):
        run_pipeline([make_step("a")], ctx, select=["x"])


def test_unselected_need_without_outputs_is_an_error(ctx: Context) -> None:
    a = make_step("a", writes=["{eocene.output_dir}/a.txt"])
    b = make_step("b", needs=["a"], writes=["{eocene.output_dir}/b.txt"])
    with pytest.raises(PipelineError, match="'b' needs 'a', which is not selected and has not run before"):
        run_pipeline([a, b], ctx, select=["b"])
    assert outputs(ctx) == []


def test_unselected_need_with_outputs_is_allowed(ctx: Context) -> None:
    ran = []
    a = make_step("a", writes=["{eocene.output_dir}/a.txt"], ran=ran)
    b = make_step("b", needs=["a"], reads=["{eocene.output_dir}/a.txt"], writes=["{eocene.output_dir}/b.txt"], ran=ran)
    (Path(ctx.config.eocene.output_dir) / "a.txt").write_text("from an earlier run")
    run_pipeline([a, b], ctx, select=["b"])
    assert ran == ["b"]


def test_missing_write_after_run_is_an_error(ctx: Context) -> None:
    class Lazy(ComponentStep):
        """Writes nothing."""

        name, writes = "lazy", ["{eocene.output_dir}/never.txt"]

        @classmethod
        def from_context(cls, ctx):
            return cls()

        def run(self):
            pass

    with pytest.raises(PipelineError, match=r"Step 'lazy' did not write: .*never\.txt"):
        run_pipeline([Lazy], ctx)


def test_write_into_input_is_refused_before_start(ctx: Context) -> None:
    ran = []
    a = make_step("a", writes=["{inputs.ece4_data}/a.txt"], ran=ran)
    with pytest.raises(PipelineError, match="Step 'a' would write .* read-only 'inputs.ece4_data'"):
        run_pipeline([a], ctx)
    assert ran == []


def test_base_class_must_be_overridden() -> None:
    with pytest.raises(NotImplementedError):
        ComponentStep.from_context(None)
    with pytest.raises(NotImplementedError):
        ComponentStep().run()


# --- context -------------------------------------------------------------------------------------------------------


def test_expand_placeholders(ctx: Context) -> None:
    c = ctx.config
    assert ctx.expand("{inputs.ece4_data}/oifs/{oifs.grid}/x") == f"{c.inputs.ece4_data}/oifs/TL63L31/x"
    out = c.eocene.output_dir
    assert ctx.expand("{eocene.output_dir}/oasis/{nemo.grid}/rstos.nc") == f"{out}/oasis/PALEORCA2/rstos.nc"
    assert ctx.expand("{inputs.herold}/h.nc") == f"{c.inputs.herold}/h.nc"
    assert ctx.expand("{tmpdir}/t.nc") == f"{c.tmpdir}/t.nc"
    assert ctx.expand("{eocene.domain.from}/x") == f"{c.eocene.domain.from_}/x"
    assert ctx.expand("/plain/path") == "/plain/path"


def test_expand_unknown_placeholder(ctx: Context) -> None:
    with pytest.raises(ConfigError, match=r"unknown key 'inputs.ece4' in placeholder \{inputs.ece4\}"):
        ctx.expand("{inputs.ece4}/x")
    with pytest.raises(ConfigError, match="unknown key 'input'"):
        ctx.expand("{input}/x")


def test_expand_tmpdir_unset(ctx: Context) -> None:
    ctx.config.tmpdir = None
    with pytest.raises(ConfigError, match="'tmpdir', which is not set"):
        ctx.expand("{tmpdir}/x")


@pytest.mark.parametrize("template", ["{inputs.ece4_data}", "{inputs.ece4_data}/a.txt", "{inputs.herold}/sub/x.nc"])
def test_check_writable_refuses_read_only_roots(ctx: Context, template: str) -> None:
    with pytest.raises(PipelineError, match="read-only"):
        ctx.check_writable(ctx.expand(template), "s")


def test_check_writable_allows_output_and_tmpdir(ctx: Context) -> None:
    ctx.check_writable(ctx.expand("{eocene.output_dir}/x.nc"))
    ctx.check_writable(ctx.expand("{tmpdir}/x.nc"))
    # a sibling whose name starts with the root name is not inside it
    ctx.check_writable(ctx.config.inputs.ece4_data + "-copy/x.nc")


def test_check_writable_follows_symlinks(ctx: Context, tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(ctx.config.inputs.ece4_data)
    with pytest.raises(PipelineError, match="read-only 'inputs.ece4_data'"):
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


def test_stage_copies_the_subset(ctx: Context) -> None:
    input_tree(Path(ctx.config.inputs.ece4_data))
    out = Path(ctx.config.eocene.output_dir)
    (out / "old.txt").write_text("overwritten")
    ctx.overwrite = True
    run_pipeline([Stage], ctx)
    copied = sorted(str(p.relative_to(out)) for p in out.rglob("f.txt"))
    assert copied == [
        "nemo/initial/f.txt",
        "oasis/PALEORCA2/f.txt",
        "oifs/TL63L31/f.txt",
        "oifs/ifsdata/f.txt",
    ]
    assert (out / "cmip6-data").is_symlink()
    assert (out / "cmip6-data" / "f.txt").read_text() == "cmip6-data"
    assert not (out / "old.txt").exists()


def test_stage_refuses_non_empty_output_without_overwrite(ctx: Context) -> None:
    input_tree(Path(ctx.config.inputs.ece4_data))
    out = Path(ctx.config.eocene.output_dir)
    (out / "old.txt").write_text("kept")
    with pytest.raises(PipelineError, match="is not empty"):
        run_pipeline([Stage], ctx)
    assert outputs(ctx) == ["old.txt"]


def test_stage_refuses_output_containing_input(tmp_path: Path) -> None:
    (tmp_path / "out" / "input").mkdir(parents=True)
    stage = Stage(str(tmp_path / "out" / "input"), str(tmp_path / "out"), "TL63L31", "PALEORCA2")
    with pytest.raises(ValueError, match="is or contains the input directory"):
        stage.run()
    assert (tmp_path / "out" / "input").is_dir()


def test_stage_preflight_reports_missing_input(ctx: Context) -> None:
    with pytest.raises(PipelineError, match="3 input files are missing"):
        run_pipeline([Stage], ctx)
