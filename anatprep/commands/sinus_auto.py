"""
sinus-auto command: auto-generate a sagittal sinus exclusion mask.

Pipeline:
  1. Register FLAIR --> T1w (FLIRT, 6-DOF, mutual info)
  2. Multiply registered FLAIR by the brain mask (kills skull signal)
  3. Run BET on the masked FLAIR, the resulting mask naturally excludes the sinus
  4. Dilate with MRtrix `maskfilter`

Usage:
  anatprep sinus-auto --t1w <T1W> --flair <FLAIR> --mask <BRAINMASK> \\
                      [--out <OUT>]

If --out is omitted, the output is written to CWD as
``<t1w_stem>_sinusauto.nii.gz``. The dilated version is written alongside
as ``<out_stem>_dilated.nii.gz``.

Other files (stored one step above --out):
  <flair_stem>_space-t1w.nii.gz    - registered FLAIR
  xfm/<flair_stem>_space-t1w.mat   - FLIRT transform
"""

import shutil
import tempfile
from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np

from anatprep.core import (
    setup_command_logging,
    default_output,
    check_output,
    run_command,
    input_stem,
)


def run_sinus_auto(
    t1w: Path,
    flair: Optional[Path] = None,
    mask: Optional[Path] = None,
    out: Optional[Path] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    t1w = Path(t1w).resolve()
    flair = Path(flair).resolve() if flair is not None else None
    mask = Path(mask).resolve() if mask is not None else None

    if out is None:
        out = default_output(t1w, "sinusauto")
    else:
        out = Path(out).resolve()

    out.parent.mkdir(parents=True, exist_ok=True)
    out_dilated = out.parent / f"{input_stem(out)}_dilated.nii.gz"

    logger, log_dir = setup_command_logging("sinus-auto", t1w, verbose=verbose)
    logger.info(f"T1w        : {t1w}")
    logger.info(f"FLAIR      : {flair if flair is not None else 'None (fallback to T1w BET)'}")
    logger.info(f"Brain mask : {mask if mask is not None else 'None'}")
    logger.info(f"Out        : {out}")
    logger.info(f"Dilated out: {out_dilated}")

    if not check_output(out, logger, force):
        return

    _check_external("bet", "FSL")
    _check_external("maskfilter", "MRtrix3")
    if flair is not None:
        _check_external("flirt", "FSL")

    work_dir = out.parent

    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        tmp = Path(tmp)

        if flair is not None:
            if mask is None:
                raise ValueError("mask is required when flair is provided")

            flair_stem = input_stem(flair)
            flair_reg = work_dir / f"{flair_stem}_space-t1w.nii.gz"
            xfm_dir = work_dir.parent / "xfm"
            xfm_mat = xfm_dir / f"{flair_stem}_space-t1w.mat"

            have_cached_registration = flair_reg.exists() and xfm_mat.exists()
            if have_cached_registration and not force:
                logger.info(f"Reusing existing registered FLAIR: {flair_reg.name}")
            else:
                xfm_dir.mkdir(parents=True, exist_ok=True)
                logger.info("Registering FLAIR --> T1w (FLIRT 6-DOF, mutual info)")
                run_command([
                    "flirt",
                    "-in", str(flair),
                    "-ref", str(t1w),
                    "-out", str(flair_reg),
                    "-omat", str(xfm_mat),
                    "-dof", "6",
                    "-cost", "mutualinfo",
                    "-searchrx", "-90", "90",
                    "-searchry", "-90", "90",
                    "-searchrz", "-90", "90",
                    "-interp", "trilinear",
                ], logger)

            logger.info("Multiplying registered FLAIR by brain mask")
            flair_img = nib.load(str(flair_reg))
            flair_data = flair_img.get_fdata().astype(np.float32)
            brain = nib.load(str(mask)).get_fdata() > 0
            masked = flair_data * brain.astype(np.float32)

            masked_path = tmp / "flair_masked.nii.gz"
            nib.Nifti1Image(masked, flair_img.affine, flair_img.header).to_filename(
                str(masked_path)
            )

            logger.info("Running BET on masked FLAIR (f=0.3, g=-0.1)")
            bet_prefix = tmp / "bet_flair"
            bet_mask = tmp / "bet_flair_mask.nii.gz"
            bet_input = masked_path

        else:
            logger.info("No FLAIR provided; running BET directly on T1w")
            bet_prefix = tmp / "bet_t1w"
            bet_mask = tmp / "bet_t1w_mask.nii.gz"
            bet_input = t1w

        run_command([
            "bet",
            str(bet_input),
            str(bet_prefix),
            "-f", "0.3",
            "-g", "-0.1",
            "-m",
        ], logger)

        if not bet_mask.exists():
            raise RuntimeError("BET did not produce expected mask.")

        n_vox = int(np.sum(nib.load(str(bet_mask)).get_fdata() > 0))
        logger.info(f"BET mask voxels: {n_vox}")

        shutil.copy2(str(bet_mask), str(out))
        logger.info(f"Undilated mask written: {out.name}")

    logger.info("Dilating mask with maskfilter (npass=1)")
    run_command([
        "maskfilter",
        str(out),
        "dilate",
        str(out_dilated),
        "-npass", "1",
        "-force",
    ], logger)

    if out_dilated.exists():
        n = int(np.sum(nib.load(str(out_dilated)).get_fdata() > 0))
        logger.info(f"Dilated mask voxels: {n}")
    else:
        raise RuntimeError("maskfilter did not produce dilated mask.")


def _check_external(binary: str, package: str) -> None:
    if shutil.which(binary) is None:
        raise RuntimeError(f"'{binary}' not found in PATH. Install {package}.")