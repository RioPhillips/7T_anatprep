"""
denoise command: remove background noise from a T1w image.

Applies the Heij / de Hollander background removal formula using a
brain mask and the INV2 image:

    new_t1w = t1w * mask * mean(inv2[mask==1] / max(inv2))
            + t1w * (inv2 / max(inv2)) * (1 - mask)

Usage:
  anatprep denoise --t1w <T1W> --mask <MASK> --inv2 <INV2> [--out <OUTPUT>]

If --out is omitted, the output is written to CWD as
``<t1w_stem>_denoised.nii.gz``.
"""

from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np

from anatprep.core import (
    setup_logging,
    default_output,
    check_output,
)


def run_denoise(
    t1w: Path,
    mask: Path,
    inv2: Path,
    out: Optional[Path] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    t1w = Path(t1w).resolve()
    mask = Path(mask).resolve()
    inv2 = Path(inv2).resolve()

    if out is None:
        out = default_output(t1w, "denoised")
    else:
        out = Path(out).resolve()

    out.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("denoise", verbose=verbose)
    logger.info(f"T1w : {t1w}")
    logger.info(f"Mask: {mask}")
    logger.info(f"INV2: {inv2}")
    logger.info(f"Out : {out}")

    if not check_output(out, logger, force):
        return

    t1w_img = nib.load(str(t1w))
    mask_img = nib.load(str(mask))
    inv2_img = nib.load(str(inv2))

    t1w_data = t1w_img.get_fdata().astype(np.float64)
    mask_data = (mask_img.get_fdata() > 0).astype(np.float64)
    inv2_data = inv2_img.get_fdata().astype(np.float64)

    inv2_max = float(np.max(inv2_data))
    if inv2_max == 0:
        raise ValueError("INV2 image has max intensity 0, cannot denoise.")

    inv2_norm = inv2_data / inv2_max
    mean_inside = (
        float(np.mean(inv2_norm[mask_data == 1])) if np.any(mask_data == 1) else 1.0
    )

    new_t1w = (
        t1w_data * mask_data * mean_inside
        + t1w_data * inv2_norm * (1 - mask_data)
    )

    nib.Nifti1Image(new_t1w, t1w_img.affine, t1w_img.header).to_filename(str(out))
    logger.info(f"Denoised T1w written: {out.name}")