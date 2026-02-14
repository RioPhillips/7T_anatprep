"""
sinus-auto command: auto-generate a sagittal sinus exclusion mask.

Strategy:
    1. If FLAIR exists: register FLAIR --> T1w (FLIRT 6-DOF), binarize
       both, take intersection. Voxels in T1w-mask but NOT in
       FLAIR-mask are candidate sinus.
    2. If no FLAIR: create a mask using intensity thresholding
       on the T1w (high-intensity near midline = likely sinus).

In both cases the result is a *starting point* for manual editing
in ITK-Snap via ``anatprep sinus-edit``.
"""

from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np

from anatprep.commands import iter_sessions
from anatprep.core import (
    setup_logging,
    check_outputs_exist,
    run_command,
)


def run_sinus_auto(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    subjects = iter_sessions(studydir, subject, session)

    for sub in subjects:
        log_file = sub.log_dir / "sinus_auto.log"
        logger = setup_logging("sinus_auto", log_file, verbose)
        sub.ensure_deriv_dirs()

        runs = sub.get_mp2rage_runs()
        logger.info(f"Processing {sub} — runs: {runs}")

        for run in runs:
            output = sub.deriv_path("sinusauto", "mask", run=run)

            should_run, _ = check_outputs_exist([output], logger, force)
            if not should_run:
                continue

            # need T1w from pymp2rage (or denoised)
            t1w = (
                sub.find_deriv_file("desc-denoised", run=run)
                or sub.find_deriv_file("desc-pymp2rage", run=run)
            )
            if t1w is None:
                logger.error(f"No T1w found for run-{run}. Run earlier steps first.")
                continue

            # brain mask from SPM
            brain_mask = sub.find_deriv_file("desc-spmmask", run=run)

            if sub.has_flair():
                flair_files = sub.get_flair_files()
                logger.info(f"FLAIR found ({len(flair_files)} files) --> utilizing intersection with T1w")
                _sinus_from_flair(
                    t1w=t1w,
                    flair=flair_files[0],  # use first FLAIR
                    brain_mask=brain_mask,
                    output=output,
                    work_dir=sub.deriv_dir,
                    logger=logger,
                )
            else:
                logger.info("No FLAIR found --> using intensity threshold on T1w only")
                _sinus_from_intensity(
                    t1w=t1w,
                    brain_mask=brain_mask,
                    output=output,
                    logger=logger,
                )

            if output.exists():
                logger.info(f"Auto sinus mask: {output.name}")
                logger.info("Run 'anatprep sinus-edit' to refine manually.")
            else:
                logger.error(f"Sinus mask was not produced for run-{run}")


def _sinus_from_flair(
    t1w: Path,
    flair: Path,
    brain_mask: Optional[Path],
    output: Path,
    work_dir: Path,
    logger,
) -> None:
    """
    Generate sinus mask from FLAIR and T1w intersection.

    The sagittal sinus appears bright in T1w but NOT in FLAIR.
    So: sinus_candidate = T1w_brain - FLAIR_brain
    """
    # register FLAIR to T1w space
    flair_reg = work_dir / f"flair_in_t1w_{flair.stem}.nii.gz"
    mat_file = work_dir / f"flair_to_t1w_{flair.stem}.mat"

    if not flair_reg.exists():
        logger.info(f"Registering FLAIR --> T1w (FLIRT 6-DOF)")
        cmd = [
            "flirt",
            "-in", str(flair),
            "-ref", str(t1w),
            "-out", str(flair_reg),
            "-omat", str(mat_file),
            "-dof", "6",
            "-interp", "trilinear",
        ]
        run_command(cmd, logger)

    # binarize both at a threshold
    t1w_img = nib.load(str(t1w))
    flair_img = nib.load(str(flair_reg))

    t1w_data = t1w_img.get_fdata().astype(np.float32)
    flair_data = flair_img.get_fdata().astype(np.float32)

    # threshold at 90th percentile of non-zero voxels
    t1w_thresh = np.percentile(t1w_data[t1w_data > 0], 90) if np.any(t1w_data > 0) else 1
    flair_thresh = np.percentile(flair_data[flair_data > 0], 90) if np.any(flair_data > 0) else 1

    t1w_bright = t1w_data > t1w_thresh
    flair_bright = flair_data > flair_thresh

    # sinus candidate = bright in T1w but NOT bright in FLAIR
    sinus = (t1w_bright & ~flair_bright).astype(np.uint8)

    # optionally restrict to within brain mask
    if brain_mask is not None and Path(brain_mask).exists():
        mask_data = nib.load(str(brain_mask)).get_fdata() > 0
        sinus = sinus * mask_data.astype(np.uint8)

    output.parent.mkdir(parents=True, exist_ok=True)
    nib.Nifti1Image(sinus, t1w_img.affine, t1w_img.header).to_filename(str(output))


def _sinus_from_intensity(
    t1w: Path,
    brain_mask: Optional[Path],
    output: Path,
    logger,
) -> None:
    """
    Generate a rough sinus mask from T1w intensity alone.
    """
    t1w_img = nib.load(str(t1w))
    data = t1w_img.get_fdata().astype(np.float32)

    # threshold at 95% atm
    thresh = np.percentile(data[data > 0], 95) if np.any(data > 0) else 1
    sinus = (data > thresh).astype(np.uint8)

    if brain_mask is not None and Path(brain_mask).exists():
        mask_data = nib.load(str(brain_mask)).get_fdata() > 0
        sinus = sinus * mask_data.astype(np.uint8)

    output.parent.mkdir(parents=True, exist_ok=True)
    nib.Nifti1Image(sinus, t1w_img.affine, t1w_img.header).to_filename(str(output))
