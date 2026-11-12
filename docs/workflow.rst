Workflow
========

Today the Eocene workflow has one part per component (``oasis``, ``oifs``, ``nemo``, ``rnfm``),
selected with ``--run`` (see :doc:`quickstart`). The refactor turns each part into a *step*,
and a workflow into an ordered list of steps (a *pipeline*) run by one runner. The runner and
the ``stage`` step exist already; the Eocene steps follow.

Steps
-----

A step is a class that subclasses :class:`ecefast.core.steps.ComponentStep`. It declares:

``name``
   Short name, used to select it and in ``needs`` (``stage``, ``oifs``, ``nemo``, ...).
``needs``
   Names of the steps that must run before it.
``reads``
   Paths it reads (files or directories).
``writes``
   Paths it writes.

and implements ``from_context(ctx)``, which builds the step from the run context, and
``run()``, which does the work by calling the ``create_*`` methods. ``reads`` and ``writes``
are the truth: a step touches no other file. The first line of the class docstring describes
the step in the dry run.

.. code-block:: python

   from ecefast.core.steps import ComponentStep


   class EoceneNEMO(ComponentStep):
       """Tides, geothermal flux, ocean initial state, runoff."""

       name = "nemo"
       needs = ["stage"]  # run after the base files are copied
       reads = ["{input}/nemo/initial/woa13-levitus-L31.nc"]
       writes = ["{output}/nemo/initial/woa13-levitus-L31_woa-pi.nc"]

       # __init__ and the create_* methods are unchanged

       @classmethod
       def from_context(cls, ctx):
           return cls(herold_folder=ctx.paths.herold, input_folder=ctx.paths.input, output_folder=ctx.paths.output)

       def run(self):
           self.create_tidal_mixing()
           self.create_geothermal_flux()
           self.create_ocean_init()
           self.create_runoff()

Path templates use these placeholders, filled from the configuration (:doc:`configuration`):

=================  ==============================================
Placeholder        Value
=================  ==============================================
``{input}``        ``paths.input`` (ECE4-DATA-V3, read-only)
``{output}``       ``paths.output``
``{herold}``       ``paths.herold`` (Herold et al. 2014, read-only)
``{tmpdir}``       ``paths.tmpdir`` (error if not set)
``{oifs_grid}``    ``grids.oifs``, e.g. ``TL63L31``
``{nemo_grid}``    ``grids.nemo``, e.g. ``PALEORCA2``
=================  ==============================================

An unknown placeholder is an error.

Running a pipeline
------------------

.. code-block:: python

   from ecefast.core import load_config
   from ecefast.core.steps import run_pipeline
   from ecefast.core.workspace import Context, Stage

   ctx = Context(load_config("configs/laptop.yml"))
   run_pipeline([Stage, EoceneNEMO], ctx)                    # all steps
   run_pipeline([Stage, EoceneNEMO], ctx, select=["nemo"])  # only some
   run_pipeline([Stage, EoceneNEMO], ctx, dry_run=True)      # check and show the plan

Before anything runs, :func:`~ecefast.core.steps.run_pipeline` checks (*preflight*):

- every step comes after the steps it ``needs``;
- a needed step that is not selected has run before: all its ``writes`` exist;
- no ``writes`` path lies inside ``input`` or ``herold``;
- every ``reads`` path exists, or is written by an earlier selected step.

All missing inputs are reported in one error, and nothing is written:

.. code-block:: text

   Cannot start: 2 input files are missing. Nothing was written.
     nemo   needs  /path/to/ECE4-DATA-V3/nemo/initial/woa13-levitus-L31.nc
     oasis  needs  /path/to/ECE4-DATA-V3/oasis/PALEORCA2/rstos.nc

A **dry run** does the same checks, logs each selected step with its description and what it
writes, and touches nothing. Otherwise the steps run in order, and after each one the runner
checks that all its ``writes`` exist.

The ``stage`` step
------------------

:class:`ecefast.core.workspace.Stage` copies the base files from the input tree to the output
tree, so the later steps modify copies, never the input. It removes the output directory if it
exists, then copies ``oifs/`` (``composition``, ``ifsdata``, ``vtables``, ``rtables`` and the
OIFS grid), ``nemo/`` (``cfc``, ``climatology``, ``initial``, ``weights``) and
``oasis/<nemo grid>``, and symlinks ``cmip6-data``. It refuses an output directory that is or
contains the input directory. Today it runs with ``eocene --copy``.

Atomic writes
-------------

Every output file is written through :func:`ecefast.core.io.atomic_write`: the writer gets a
temporary file in the same directory (same suffix, so ``.nc`` and GRIB writers work), which
replaces the final file only when the write completes. A failed step leaves no half-written
file.

.. code-block:: python

   from ecefast.core.io import atomic_write

   with atomic_write(path) as tmp:
       ds.to_netcdf(tmp)
