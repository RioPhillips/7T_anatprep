"""
sinus-edit command: open ITK-Snap to edit a sinus mask manually.

Usage:
  anatprep sinus-edit T1W MASK

Loads T1W as the background image and MASK as a segmentation overlay.
If MASK does not exist, an empty mask matching T1W is created first.
Editing happens inside ITK-Snap; save (Ctrl+S) before closing.
"""

import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np

from anatprep.core import setup_logging


def run_sinus_edit(
    t1w: Path,
    mask: Path,
    verbose: bool = False,
    **_,  # accept force/etc from CLI without using them
) -> None:
    t1w = Path(t1w).resolve()
    mask = Path(mask).resolve()

    logger = setup_logging("sinus_edit", verbose=verbose)
    logger.info(f"T1w : {t1w}")
    logger.info(f"Mask: {mask}")

    if not t1w.exists():
        raise FileNotFoundError(f"T1w image not found: {t1w}")

    if not mask.exists():
        logger.info(f"Mask does not exist; creating empty mask at {mask}")
        mask.parent.mkdir(parents=True, exist_ok=True)
        ref = nib.load(str(t1w))
        empty = np.zeros(ref.shape, dtype=np.uint8)
        nib.Nifti1Image(empty, ref.affine, ref.header).to_filename(str(mask))

    logger.info("Launching ITK-Snap, edit the mask, save (Ctrl+S), then close.")
    try:
        subprocess.run(
            ["itksnap", "-g", str(t1w), "-s", str(mask)],
            check=False,
        )
    except FileNotFoundError:
        raise RuntimeError("ITK-Snap not found. Install it or add it to PATH.")

    logger.info(f"Mask saved at: {mask}")