"""
Main CLI for anatprep.

Provides subcommands for each step of the anatomical preprocessing pipeline.
"""

import click
from pathlib import Path

from anatprep import __version__
from anatprep.core import resolve_studydir



# click classes

class HelpfulGroup(click.Group):
    """Show help when no command is given."""

    def invoke(self, ctx):
        if not ctx.protected_args and not ctx.invoked_subcommand:
            click.echo(ctx.get_help())
            ctx.exit(0)
        return super().invoke(ctx)


# shared options info

def common_options(f):
    """Common options shared across subject-level commands."""
    f = click.option(
        "--studydir", "-s",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        default=None,
        help="Path to BIDS study directory (default: auto-detect from CWD)",
    )(f)
    f = click.option(
        "--subject", "-sub",
        type=str,
        required=True,
        help="Subject ID (without sub- prefix)",
    )(f)
    f = click.option(
        "--session", "-ses",
        type=str,
        default=None,
        help="Session ID (without ses- prefix). If omitted, process all sessions.",
    )(f)
    f = click.option(
        "--force", "-f",
        is_flag=True,
        default=False,
        help="Force overwrite existing outputs",
    )(f)
    f = click.option(
        "--verbose", "-v",
        is_flag=True,
        default=False,
        help="Enable verbose output",
    )(f)
    return f


# top-level group

@click.group(cls=HelpfulGroup, context_settings=dict(help_option_names=["-h", "--help"]))
@click.version_option(__version__)
def cli():
    """
    anatprep: Anatomical preprocessing for 7T MP2RAGE data.

    Takes BIDS rawdata (from dcm2bids) through SPM masking, pymp2rage
    fitting, denoising, CAT12 segmentation, sinus masking, and iterative
    brainmask refinement with fMRIprep.

    \b
    SETUP:
      1. Run dcm2bids first to produce rawdata/
      2. Create code/anatprep_config.yml (see example in repo)
      3. Ensure code/mp2rage.json exists

    \b
    TYPICAL WORKFLOW:
      1. anatprep pymp2rage     - Compute T1w (UNIT1) + T1map
      2. anatprep mask          - Brain mask from INV2 (--spm or --bet)
      3. anatprep denoise       - Remove background noise
      4. anatprep cat12         - CAT12 segmentation
      5. anatprep sinus-auto    - Auto-generate sinus exclusion mask
      6. anatprep sinus-edit    - Manual edit in ITK-Snap
      7. anatprep fmriprep      - Run fMRIprep + FreeSurfer
      8. anatprep status        - Check iteration status
      9. anatprep brainmask-edit - Refine brainmask (ITK-Snap)
     10. anatprep fmriprep      - Re-run with refined mask
         ... repeat 8-10 until satisfied ...

    \b
    Use 'anatprep COMMAND --help' for command-specific help.
    """
    pass


# mask

@cli.command("mask", context_settings=dict(help_option_names=["-h", "--help"]))
@common_options
@click.option(
    "--bet",
    "method",
    flag_value="bet",
    default=True,
    help="Use FSL BET for masking (default)"
)
@click.option(
    "--spm",
    "method",
    flag_value="spm",
    help="Use SPM segmantation for masking"
)
def mask(studydir, subject, session, force, verbose, method):
    """
    Create brain mask from INV2 image. Two methods are available:

    \b
     --bet  FSL BET brain extraction.
            Requires FSL (bet must be on PATH).
            Uses: bet <INV2> <out> -f 0.3 -g 0.1 -m
            Output: desc-bet_mask.nii.gz

    \b
     --spm  SPM segmentation via MATLAB.
            Requires MATLAB and SPM. Set paths in code/anatprep_config.yml
            Output: desc-spmmask_mask.nii.gz

    Requires MATLAB and SPM. Set spm_path and matlab_cmd in
    code/anatprep_config.yml.
    """
    studydir = resolve_studydir(studydir)
    from anatprep.commands.mask import run_mask
    run_mask(studydir=studydir, subject=subject, session=session,
                 force=force, verbose=verbose, method=method)


# pymp2rage

@cli.command("pymp2rage", context_settings=dict(help_option_names=["-h", "--help"]))
@common_options
def pymp2rage(studydir, subject, session, force, verbose):
    """
    Compute clean T1w (UNIT1) and T1map from MP2RAGE inversions.

    Uses pymp2rage with parameters from code/mp2rage.json.
    """
    studydir = resolve_studydir(studydir)
    from anatprep.commands.pymp2rage import run_pymp2rage
    run_pymp2rage(studydir=studydir, subject=subject, session=session,
                  force=force, verbose=verbose)


# denoise

@cli.command("denoise", context_settings=dict(help_option_names=["-h", "--help"]))
@common_options
def denoise(studydir, subject, session, force, verbose):
    """
    Remove background noise from T1w using SPM mask + INV2.

    Applies the Heij/de Hollander background removal formula.
    """
    studydir = resolve_studydir(studydir)
    from anatprep.commands.denoise import run_denoise
    run_denoise(studydir=studydir, subject=subject, session=session,
                force=force, verbose=verbose)


# cat12

@cli.command("cat12", context_settings=dict(help_option_names=["-h", "--help"]))
@common_options
def cat12(studydir, subject, session, force, verbose):
    """
    Run CAT12 tissue segmentation via SPM/MATLAB.

    Requires MATLAB, SPM, and CAT12 toolbox.
    """
    studydir = resolve_studydir(studydir)
    from anatprep.commands.cat12 import run_cat12
    run_cat12(studydir=studydir, subject=subject, session=session,
              force=force, verbose=verbose)


# sinus-auto

@cli.command("sinus-auto", context_settings=dict(help_option_names=["-h", "--help"]))
@common_options
def sinus_auto(studydir, subject, session, force, verbose):
    """
    Auto-generate sinus exclusion mask.

    If FLAIR exists: uses FLAIR ∩ T1w intersection.
    Otherwise: intensity-based seed mask for manual editing.
    """
    studydir = resolve_studydir(studydir)
    from anatprep.commands.sinus_auto import run_sinus_auto
    run_sinus_auto(studydir=studydir, subject=subject, session=session,
                   force=force, verbose=verbose)


# sinus-edit

@cli.command("sinus-edit", context_settings=dict(help_option_names=["-h", "--help"]))
@common_options
def sinus_edit(studydir, subject, session, force, verbose):
    """
    Open ITK-Snap for manual sinus mask editing.

    Launches ITK-Snap with T1w as background and the auto sinus mask
    as a segmentation overlay.
    """
    studydir = resolve_studydir(studydir)
    from anatprep.commands.sinus_edit import run_sinus_edit
    run_sinus_edit(studydir=studydir, subject=subject, session=session,
                   force=force, verbose=verbose)


# fmriprep

@cli.command("fmriprep", context_settings=dict(help_option_names=["-h", "--help"]))
@common_options
def fmriprep(studydir, subject, session, force, verbose):
    """
    Run fMRIprep + FreeSurfer via Docker.

    Injects the current brainmask and sinus mask.
    Increments the iteration counter.
    """
    studydir = resolve_studydir(studydir)
    from anatprep.commands.fmriprep import run_fmriprep
    run_fmriprep(studydir=studydir, subject=subject, session=session,
                 force=force, verbose=verbose)


# brainmask-edit

@cli.command("brainmask-edit", context_settings=dict(help_option_names=["-h", "--help"]))
@common_options
def brainmask_edit(studydir, subject, session, force, verbose):
    """
    Open ITK-Snap to refine the brainmask.

    Loads the fMRIprep/FreeSurfer brainmask for manual editing.
    Advances the iteration counter after saving.
    """
    studydir = resolve_studydir(studydir)
    from anatprep.commands.brainmask_edit import run_brainmask_edit
    run_brainmask_edit(studydir=studydir, subject=subject, session=session,
                       force=force, verbose=verbose)


# status

@cli.command("status", context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "--studydir", "-s",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Path to BIDS study directory (default: auto-detect from CWD)",
)
@click.option(
    "--subject", "-sub",
    type=str,
    default=None,
    help="Subject ID (without sub- prefix). Omit for overview of all subjects.",
)
@click.option(
    "--session", "-ses",
    type=str,
    default=None,
    help="Session ID (without ses- prefix).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Show detailed status",
)
def status(studydir, subject, session, verbose):
    """
    Show pipeline status and configuration.

    Without --subject: shows detected config and list of subjects.
    With --subject: shows per-step completion and iteration state.
    """
    studydir = resolve_studydir(studydir)
    from anatprep.commands.status import run_status
    run_status(studydir=studydir, subject=subject, session=session,
               verbose=verbose)


# entry point

def main():
    cli()


if __name__ == "__main__":
    main()
