"""
denoise command: removes background noise from T1w.

Applies the Heij / de Hollander formula using the SPM brain mask and
the INV2 image to suppress the MP2RAGE background noise:

    new_t1w = t1w * mask * mean(inv2[mask==1] / max(inv2))
            + t1w * inv2/max(inv2) * (1 - mask)
"""

from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np
from nilearn import image

from anatprep.commands import iter_sessions
from anatprep.core import (
    setup_logging,
    check_outputs_exist,
)


def run_denoise(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Remove background noise from T1w using mask + INV2."""
    subjects = iter_sessions(studydir, subject, session)

    for sub in subjects:
        log_file = sub.log_dir / "denoise.log"
        logger = setup_logging("denoise", log_file, verbose)
        sub.ensure_deriv_dirs()

        runs = sub.get_mp2rage_runs()
        logger.info(f"Processing {sub} - runs: {runs}")

        for run in runs:
            output = sub.deriv_path("denoised", "T1w", run=run)

            should_run, _ = check_outputs_exist([output], logger, force)
            if not should_run:
                continue

            # the T1w from pymp2rage step
            t1w_file = sub.find_deriv_file("desc-pymp2rage", run=run)
            if t1w_file is None:
                logger.error(
                    f"pymp2rage T1w not found for run-{run}. "
                    "Run 'anatprep pymp2rage' first."
                )
                continue

            # the SPM brain mask
            mask_file = sub.find_deriv_file("desc-spmmask", run=run)
            if mask_file is None:
                logger.error(
                    f"SPM mask not found for run-{run}. "
                    "Run 'anatprep spm-mask' first."
                )
                continue

            # raw INV2
            try:
                inv2_file = sub.get_raw_inv2(run)
            except FileNotFoundError:
                try:
                    inv2_file = sub.get_rawdata_file("inv-2_part-mag_MP2RAGE", run)
                except FileNotFoundError:
                    logger.error(f"INV2 not found for run-{run}. Skipping.")
                    continue

            logger.info(f"Denoising run-{run}")
            logger.info(f"  T1w:  {t1w_file.name}")
            logger.info(f"  Mask: {mask_file.name}")
            logger.info(f"  INV2: {inv2_file.name}")

            _rm_background(t1w_file, mask_file, inv2_file, output)

            if output.exists():
                logger.info(f"  Output: {output.name}")
            else:
                logger.error(f"Denoised output was not produced for run-{run}")


def _rm_background(
    t1w_path: Path,
    mask_path: Path,
    inv2_path: Path,
    output_path: Path,
) -> None:
    """
    Apply the Heij/de Hollander background removal formula.

    new_t1w = t1w * mask * mean(inv2[mask==1] / max(inv2))
            + t1w * (inv2 / max(inv2)) * (1 - mask)
    """
    t1w_img = nib.load(str(t1w_path))
    mask_img = nib.load(str(mask_path))
    inv2_img = nib.load(str(inv2_path))

    t1w = t1w_img.get_fdata().astype(np.float64)
    mask = (mask_img.get_fdata() > 0).astype(np.float64)
    inv2 = inv2_img.get_fdata().astype(np.float64)

    inv2_max = np.max(inv2)
    if inv2_max == 0:
        raise ValueError("INV2 image has max intensity 0 - cannot denoise.")

    inv2_norm = inv2 / inv2_max
    mean_inside = np.mean(inv2_norm[mask == 1]) if np.any(mask == 1) else 1.0

    new_t1w = t1w * mask * mean_inside + t1w * inv2_norm * (1 - mask)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_img = nib.Nifti1Image(new_t1w, t1w_img.affine, t1w_img.header)
    out_img.to_filename(str(output_path))
