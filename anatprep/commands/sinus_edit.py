"""
sinus-edit command: launches ITK-Snap for manual sagittal sinus mask editing.

Opens ITK-Snap with the T1w as the main image and the auto-generated
sinus mask as a segmentation overlay. The user edits the mask, saves,
and closes ITK-Snap. The script then copies the result as the final
sinus mask.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

import click

from anatprep.commands import iter_sessions
from anatprep.core import setup_logging


def run_sinus_edit(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    subjects = iter_sessions(studydir, subject, session)

    for sub in subjects:
        log_file = sub.log_dir / "sinus_edit.log"
        logger = setup_logging("sinus_edit", log_file, verbose)
        sub.ensure_deriv_dirs()

        runs = sub.get_mp2rage_runs()

        for run in runs:
            # background image: denoised T1w or pymp2rage T1w
            t1w = (
                sub.find_deriv_file("desc-denoised", run=run)
                or sub.find_deriv_file("desc-pymp2rage", run=run)
            )
            if t1w is None:
                logger.error(f"No T1w found for run-{run}. Skipping.")
                continue

            # auto sinus mask
            auto_mask = sub.find_deriv_file("desc-sinusauto", run=run)
            if auto_mask is None:
                logger.warning(
                    f"No auto sinus mask for run-{run}. "
                    "Run 'anatprep sinus-auto' first, or editing from scratch."
                )

            # final sinus mask path 
            final_mask = sub.deriv_path("sinusfinal", "mask", run=run)

            # if final already exists and not force, use it as the overlay
            if final_mask.exists() and not force:
                logger.info(f"Final sinus mask exists for run-{run}. Using it as overlay.")
                overlay = final_mask
            elif auto_mask is not None:
                # copy auto --> final as starting point
                shutil.copy2(auto_mask, final_mask)
                overlay = final_mask
            else:
                # create empty mask
                import nibabel as nib
                import numpy as np
                ref = nib.load(str(t1w))
                empty = np.zeros(ref.shape, dtype=np.uint8)
                nib.Nifti1Image(empty, ref.affine, ref.header).to_filename(str(final_mask))
                overlay = final_mask

            logger.info(f"Launching ITK-Snap for run-{run}")
            logger.info(f"  Background: {t1w.name}")
            logger.info(f"  Overlay:    {overlay.name}")
            logger.info("  Edit the sinus mask, save (Ctrl+S), and close ITK-Snap.")

            # launch ITK-Snap (until user closes it
            cmd = ["itksnap", "-g", str(t1w), "-s", str(overlay)]

            try:
                subprocess.run(cmd, check=False)
            except FileNotFoundError:
                logger.error(
                    "ITK-Snap not found. Install it or add it to PATH.\n"
                    "  Ubuntu: sudo apt install itksnap\n"
                    "  Or download from: http://www.itksnap.org"
                )
                return

            if final_mask.exists():
                logger.info(f"Sinus mask saved: {final_mask.name}")
            else:
                logger.warning("No sinus mask file found after editing.")
