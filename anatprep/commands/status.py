"""
status command: shows pipeline configuration and per-subject progress.
"""

import click
from pathlib import Path
from typing import Optional

from anatprep.core import (
    Subject,
    IterationState,
    setup_logging,
    load_anatprep_config,
    load_mp2rage_params,
    find_config_from_cwd,
)


def run_status(
    studydir: Path,
    subject: Optional[str] = None,
    session: Optional[str] = None,
    verbose: bool = False,
) -> None:
    logger = setup_logging("status", verbose=verbose)

    click.echo("anatprep status")
    click.echo("=" * 70)
    click.echo(f"Study directory : {studydir}")
    click.echo()

    # config 
    config = load_anatprep_config(studydir)
    config_path = studydir / "code" / "anatprep_config.yml"

    mp2rage = load_mp2rage_params(studydir)

    checks = [
        ("code/anatprep_config.yml", config_path.exists()),
        ("code/mp2rage.json", mp2rage is not None),
        ("rawdata/", (studydir / "rawdata").exists()),
        ("derivatives/", (studydir / "derivatives").exists()),
    ]

    click.echo("Study structure:")
    click.echo("-" * 50)
    for name, exists in checks:
        mark = "OK" if exists else "MISSING"
        click.echo(f"  [{mark:>7s}]  {name}")
    click.echo()

    if not config and not config_path.exists():
        click.echo("No anatprep_config.yml found. Create code/anatprep_config.yml")
        click.echo("with at least spm_path and matlab_cmd settings.")
        return

    if verbose and config:
        click.echo("Configuration:")
        click.echo("-" * 50)
        _print_config(config, indent=2)
        click.echo()

    # subjects
    rawdata = studydir / "rawdata"
    if not rawdata.exists():
        click.echo("No rawdata/ directory found. Run dcm2bids first.")
        return

    if subject is None:
        # overview of all subjects
        sub_dirs = sorted(rawdata.glob("sub-*"))
        click.echo(f"Subjects found: {len(sub_dirs)}")
        click.echo("-" * 50)
        for sd in sub_dirs:
            sub_id = sd.name.removeprefix("sub-")
            sessions = Subject(studydir, sub_id).get_sessions()
            click.echo(f"  {sd.name}  sessions: {sessions}")
        return

    # --- per-subject status ---
    sub = Subject(studydir, subject, session)

    if session:
        _show_session_status(sub, verbose)
    else:
        sessions = sub.get_sessions()
        if not sessions:
            click.echo(f"No sessions found for sub-{subject}")
            return
        for ses in sessions:
            ses_sub = sub.for_session(ses)
            click.echo(f"\n--- ses-{ses} ---")
            _show_session_status(ses_sub, verbose)


def _show_session_status(sub: Subject, verbose: bool) -> None:
    """Show step-by-step completion for a single session."""
    runs = sub.get_mp2rage_runs()
    click.echo(f"  MP2RAGE runs: {runs or 'none found'}")

    if not runs:
        return

    for run in runs:
        click.echo(f"\n  Run {run}:")

        steps = [
            ("SPM mask",   "spmmask",    "mask"),
            ("pymp2rage",  "pymp2rage",  "T1w"),
            ("Denoised",   "denoised",   "T1w"),
            ("CAT12",      "cat12",      "T1w"),
            ("Sinus auto", "sinusauto",  "mask"),
            ("Sinus final","sinusfinal", "mask"),
        ]

        for label, desc, suffix in steps:
            f = sub.find_deriv_file(f"desc-{desc}", run=run)
            mark = "done" if f else "    "
            click.echo(f"    [{mark:>4s}]  {label}")

    # iteration state
    if sub.deriv_dir and sub.deriv_dir.exists():
        state = IterationState(sub.deriv_dir)
        click.echo(f"\n  Brainmask loop: {state.summary()}")
    else:
        click.echo(f"\n  Brainmask loop: not started")


def _print_config(d: dict, indent: int = 0) -> None:
    """Recursively print a dict."""
    prefix = " " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            click.echo(f"{prefix}{k}:")
            _print_config(v, indent + 2)
        else:
            click.echo(f"{prefix}{k}: {v}")
