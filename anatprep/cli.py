"""
Main CLI for anatprep.
"""

import click
from pathlib import Path

from anatprep import __version__


class HelpfulGroup(click.Group):
    """Show help when no command is given."""

    def invoke(self, ctx):
        if not ctx.protected_args and not ctx.invoked_subcommand:
            click.echo(ctx.get_help())
            ctx.exit(0)
        return super().invoke(ctx)


@click.group(cls=HelpfulGroup, context_settings=dict(help_option_names=["-h", "--help"]))
@click.version_option(__version__)
def cli():
    """
    anatprep: Anatomical preprocessing for 7T MP2RAGE data.

    \b
    TYPICAL WORKFLOW (run per-subject, per-run):
      1. pymp2rage         - T1w (UNIT1) + T1map from inversions
      2. mask              - Brain mask from INV2 (--bet or --spm)
      3. denoise           - Remove background noise
      4. cat12             - CAT12 tissue segmentation
      5. sinus-auto        - Auto-generate sinus exclusion mask
      6. sinus-edit        - Manual refinement in ITK-Snap
      7. run-freesurfer    - recon-all (initial or post-edit rerun)
      8. brainmask-edit    - Manual brainmask/wm edits in freeview

    \b
    Commands read code/anatprep.yml and code/mp2rage.yaml from the
    study directory when MATLAB or MP2RAGE parameters are needed.

    Each subcommand is also exposed as a standalone console script
    (e.g. `pymp2rage --help`, `run-freesurfer --help`).
    """
    pass


_COMMON = [
    click.option("--force", "-f", is_flag=True, help="Overwrite existing outputs."),
    click.option("--verbose", "-v", is_flag=True, help="Verbose output."),
]


def _common_options(f):
    for opt in reversed(_COMMON):
        f = opt(f)
    return f


# ---------------------------------------------------------------------------
# mask
# ---------------------------------------------------------------------------

@cli.command("mask", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("input_image", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_image", type=click.Path(dir_okay=False, path_type=Path), required=False)
@click.option("--bet", "method", flag_value="bet", default=True,
              help="FSL BET brain extraction (default).")
@click.option("--spm", "method", flag_value="spm",
              help="SPM segmentation via MATLAB.")
@_common_options
def mask_cmd(input_image, output_image, method, force, verbose):
    """
    Create a brain mask from an INV2 image.

    \b
    INPUT_IMAGE   Source image (typically the INV2 magnitude).
    OUTPUT_IMAGE  Destination mask. If omitted, written to CWD as
                  <input_stem>_bet.nii.gz or <input_stem>_spmmask.nii.gz.
    """
    from anatprep.commands.mask import run_mask
    run_mask(input_image, output_image, method=method, force=force, verbose=verbose)


# ---------------------------------------------------------------------------
# nighres dura
# ---------------------------------------------------------------------------
@cli.command("nighres-dura", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("inv2", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("brain_mask", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_image", type=click.Path(dir_okay=False, path_type=Path), required=False)
@click.option(
    "--threshold",
    type=float,
    default=None,
    help="Threshold applied to the dura probability map. Defaults to config value or 0.8.",
)
@_common_options
def nighres_dura_cmd(inv2, brain_mask, output_image, threshold, force, verbose):
    """
    Estimate dura probability with Nighres and write a binary dura mask.

    \b
    INV2         Second inversion image.
    BRAIN_MASK   Brain mask for the INV2 image.
    OUTPUT_IMAGE Final binary dura mask. If omitted, defaults to <INV2>_dura_mask.nii.gz.
    """
    from anatprep.commands.nighres_dura import run_nighres_dura
    run_nighres_dura(
        inv2,
        brain_mask,
        output_image=output_image,
        threshold=threshold,
        force=force,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# nighres skullstrip
# ---------------------------------------------------------------------------
@cli.command("nighres-skullstrip", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("inv2", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("t1w", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("t1map", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_prefix", type=click.Path(dir_okay=False, path_type=Path), required=False)
@_common_options
def nighres_skullstrip_cmd(inv2, t1w, t1map, output_prefix, force, verbose):
    """
    Run Nighres MP2RAGE skullstripping.

    \b
    INV2          Second inversion image.
    T1W           T1-weighted image.
    T1MAP         T1 map image.
    OUTPUT_PREFIX Prefix for outputs. If omitted, defaults to <INV2>_strip.
    """
    from anatprep.commands.nighres_skullstrip import run_nighres_skullstrip
    run_nighres_skullstrip(
        inv2,
        t1w,
        t1map,
        output_prefix=output_prefix,
        force=force,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# pymp2rage
# ---------------------------------------------------------------------------
@cli.command("pymp2rage", context_settings=dict(help_option_names=["-h", "--help"]))
@click.option("--inv1-mag", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="First inversion, magnitude.")
@click.option("--inv1-phase", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="First inversion, phase.")
@click.option("--inv2-mag", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Second inversion, magnitude.")
@click.option("--inv2-phase", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Second inversion, phase.")
@click.option("--b1map",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None,
              help="Optional DREAM TB1map for B1 correction. If --b1mag is "
                   "not also given, the map is assumed to be pre-registered "
                   "to the MP2RAGE space.")
@click.option("--b1mag",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None,
              help="Magnitude/FID companion of the B1 acquisition (e.g. "
                   "_magnitude.nii.gz from a DREAM sequence). When provided "
                   "alongside --b1map, used to register the B1 map to INV1 "
                   "space via FLIRT (6-DOF, mutual info). Requires FSL.")
@click.option("--out-dir",
              type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help="Output directory (default: CWD).")
@_common_options
def pymp2rage_cmd(inv1_mag, inv1_phase, inv2_mag, inv2_phase, b1map, b1mag,
                  out_dir, force, verbose):
    """
    Compute T1w (UNIT1), T1map, and a brain mask from MP2RAGE inversions.
    All four inversion inputs must share the same sub/ses/run BIDS
    entities; output filenames are derived from those. Reads acquisition
    parameters from code/mp2rage.yaml.
    """
    from anatprep.commands.pymp2rage import run_pymp2rage
    run_pymp2rage(
        inv1_mag=inv1_mag, inv1_phase=inv1_phase,
        inv2_mag=inv2_mag, inv2_phase=inv2_phase,
        out_dir=out_dir, b1map=b1map, b1mag=b1mag,
        force=force, verbose=verbose,
    )


# ---------------------------------------------------------------------------
# denoise
# ---------------------------------------------------------------------------

@cli.command("denoise", context_settings=dict(help_option_names=["-h", "--help"]))
@click.option("--t1w", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="T1w image to denoise.")
@click.option("--mask", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Brain mask.")
@click.option("--inv2", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="INV2 magnitude image.")
@click.option("--out",
              type=click.Path(dir_okay=False, path_type=Path),
              default=None,
              help="Output path (default: <t1w_stem>_denoised.nii.gz in CWD).")
@click.option("--sanlm/--no-sanlm", default=True,
              help="Run CAT12 SANLM denoising (default: True).")
@click.option("--bias/--no-bias", default=True,
              help="Run SPM bias field correction (default: True).")
@_common_options
def denoise_cmd(t1w, mask, inv2, out, sanlm, bias, force, verbose):
    """
    Remove MP2RAGE background noise (Heij formula) and
    apply SANLM/SPM bias correction for 7T stability.
    """
    from anatprep.commands.denoise import run_denoise
    run_denoise(
        t1w=t1w,
        mask=mask,
        inv2=inv2,
        out=out,
        run_sanlm=sanlm,
        run_bias=bias,
        force=force,
        verbose=verbose
    )


# ---------------------------------------------------------------------------
# cat12
# ---------------------------------------------------------------------------

@cli.command("cat12", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("input_image", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_dir", type=click.Path(file_okay=False, path_type=Path), required=False)
@_common_options
def cat12_cmd(input_image, output_dir, force, verbose):
    """
    Run CAT12 tissue segmentation via SPM/MATLAB.

    \b
    INPUT_IMAGE   T1w image (typically denoised).
    OUTPUT_DIR    Output directory (default: <cwd>/<input_stem>_cat12).
    """
    from anatprep.commands.cat12 import run_cat12
    run_cat12(input_image=input_image, output_dir=output_dir,
              force=force, verbose=verbose)


# ---------------------------------------------------------------------------
# sinus-auto
# ---------------------------------------------------------------------------

@cli.command("sinus-auto", context_settings=dict(help_option_names=["-h", "--help"]))
@click.option("--t1w", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="T1-weighted image.")
@click.option("--flair", required=False, default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="FLAIR image (optional). If provided, a sinus-excluding mask is estimated.")
@click.option("--mask", required=False, default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Brain mask (from `anatprep mask`). Required when --flair is used.")
@click.option("--out",
              type=click.Path(dir_okay=False, path_type=Path),
              default=None,
              help="Output path (default: <t1w_stem>_sinusauto.nii.gz in CWD). "
                   "The dilated version is written alongside as "
                   "<out_stem>_dilated.nii.gz.")
@_common_options
def sinus_auto_cmd(t1w, flair, mask, out, force, verbose):
    """
    Generate a sagittal sinus exclusion mask.

    If FLAIR is provided:
        Uses FLAIR + brain mask to exclude the sinus automatically.

    If FLAIR is NOT provided:
        Falls back to BET on T1w (intended for manual editing).
    """
    from anatprep.commands.sinus_auto import run_sinus_auto

    if flair is not None and mask is None:
        raise click.UsageError("--mask is required when --flair is provided.")

    run_sinus_auto(
        t1w=t1w,
        flair=flair,
        mask=mask,
        out=out,
        force=force,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# sinus-edit
# ---------------------------------------------------------------------------

@cli.command("sinus-edit", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("t1w", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("mask", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--verbose", "-v", is_flag=True)
def sinus_edit_cmd(t1w, mask, verbose):
    """
    Open FreeView or ITK-Snap to edit a sinus mask manually.

    \b
    T1W   Background image.
    MASK  Mask to edit. Created as an empty mask if it does not exist.
    """
    from anatprep.commands.sinus_edit import run_sinus_edit
    run_sinus_edit(t1w=t1w, mask=mask, verbose=verbose)


# ---------------------------------------------------------------------------
# brainmask-edit
# ---------------------------------------------------------------------------

@cli.command("brainmask-edit", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("fs_subject_dir",
                type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--verbose", "-v", is_flag=True)
def brainmask_edit_cmd(fs_subject_dir, verbose):
    """
    Open freeview to inspect/edit a FreeSurfer subject's brainmask and wm.

    \b
    FS_SUBJECT_DIR  Path to the FS subject directory, e.g.
                    derivatives/freesurfer/sub-S01_ses-MR1
    """
    from anatprep.commands.brainmask_edit import run_brainmask_edit
    run_brainmask_edit(fs_subject_dir=fs_subject_dir, verbose=verbose)


# ---------------------------------------------------------------------------
# freesurfer (run-freesurfer)
# ---------------------------------------------------------------------------

@cli.command("freesurfer", context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("t1w", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--flair",
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None,
              help="Optional FLAIR image for pial-surface refinement "
                   "(passed as -FLAIR ... -FLAIRpial to recon-all).")
@click.option("--subjects-dir",
              type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help="FreeSurfer SUBJECTS_DIR. Defaults to the configured "
                   "value or <studydir>/derivatives/freesurfer.")
@click.option("--subject-id", type=str, default=None,
              help="Override FS subject ID. Default: derived from BIDS "
                   "entities in the T1w filename "
                   "(sub-X_ses-Y or sub-X).")
@click.option("--edit", type=click.Choice(["pial", "wm"]), default=None,
              help="Rerun mode after manual edits in freeview. "
                   "pial -> -autorecon-pial, "
                   "wm   -> -autorecon2-wm -autorecon3.")
@click.option("--cpus", type=int, default=None,
              help="Threads for -openmp N (default: config value or 1).")
@click.option("--parallel", is_flag=True, default=False,
              help="Pass -parallel to recon-all (hemisphere-level parallelism). "
                   "Doubles peak thread usage at lh/rh stages.")
@click.option("--highres", is_flag=True, default=False,
              help="Pass -hires to recon-all for sub-mm input.")
@_common_options
def freesurfer_cmd(t1w, flair, subjects_dir, subject_id, edit, cpus,
                   parallel, highres, force, verbose):
    """
    Wrap FreeSurfer's recon-all for anatomical segmentation.

    \b
    Two modes:
      Initial run (no --edit):
        Full `recon-all -all` on the given T1w. Optionally use --flair
        for pial refinement (passed as -FLAIR / -FLAIRpial) and/or
        --highres for sub-mm input.
      Rerun mode (--edit pial|wm):
        Re-run recon-all on an existing FS subject after manual edits
        in freeview (via `brainmask-edit`):
          --edit pial : brainmask.mgz edited      -> -autorecon-pial
          --edit wm   : wm.mgz (and possibly bm)  -> -autorecon2-wm -autorecon3
        The FS subject directory is copied to
        <subjects-dir>/.backups/<subject-id>_<timestamp>/ before
        recon-all is invoked, in case the rerun goes sideways.

    \b
    Parallelism:
      --cpus N    threads for -openmp N (within-binary OpenMP threads).
                  Diminishing returns past ~8 per FreeSurfer's guidance.
      --parallel  appends -parallel so lh/rh stages run concurrently.
                  Combines with --cpus, so peak load ~= 2 * N threads.

    \b
    Subject ID is derived from BIDS entities in the T1w filename:
      sub-S01_ses-MR1_..._T1w.nii.gz  -> "sub-S01_ses-MR1"
      sub-S01_..._T1w.nii.gz          -> "sub-S01"
    Override with --subject-id

    \b
    Usage:
      run-freesurfer T1W [--flair FILE] [--subjects-dir DIR] \\
                         [--edit pial|wm] [--cpus N] [--parallel] \\
                         [--highres] [--force] [--verbose]
    """
    from anatprep.commands.freesurfer import run_freesurfer
    run_freesurfer(
        t1w=t1w,
        flair=flair,
        subjects_dir=subjects_dir,
        subject_id=subject_id,
        edit=edit,
        cpus=cpus,
        parallel=parallel,
        highres=highres,
        force=force,
        verbose=verbose,
    )


def main():
    cli()


if __name__ == "__main__":
    main()