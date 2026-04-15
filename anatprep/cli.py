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
      1. anatprep pymp2rage    - T1w (UNIT1) + T1map from inversions
      2. anatprep mask         - Brain mask from INV2 (--bet or --spm)
      3. anatprep denoise      - Remove background noise
      4. anatprep cat12        - CAT12 tissue segmentation
      5. anatprep sinus-auto   - Auto-generate sinus exclusion mask
      6. anatprep sinus-edit   - Manual refinement in ITK-Snap

    \b
    Commands read code/anatprep_config.yml and code/mp2rage.yaml from the
    study directory when MATLAB or MP2RAGE
    parameters are needed.

    Use 'anatprep COMMAND --help' for details on each command.
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
              help="Optional DREAM TB1map for B1 correction.")
@click.option("--out-dir",
              type=click.Path(file_okay=False, path_type=Path),
              default=None,
              help="Output directory (default: CWD).")
@_common_options
def pymp2rage_cmd(inv1_mag, inv1_phase, inv2_mag, inv2_phase, b1map, out_dir,
                  force, verbose):
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
        out_dir=out_dir, b1map=b1map,
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
@_common_options
def denoise_cmd(t1w, mask, inv2, out, force, verbose):
    """
    Remove MP2RAGE background noise using the Heij/de Hollander formula.
    """
    from anatprep.commands.denoise import run_denoise
    run_denoise(t1w=t1w, mask=mask, inv2=inv2, out=out,
                force=force, verbose=verbose)


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

    # Enforce argument logic
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
    Open ITK-Snap to edit a sinus mask manually.

    \b
    T1W   Background image.
    MASK  Mask to edit. Created as an empty mask if it does not exist.
    """
    from anatprep.commands.sinus_edit import run_sinus_edit
    run_sinus_edit(t1w=t1w, mask=mask, verbose=verbose)


def main():
    cli()


if __name__ == "__main__":
    main()