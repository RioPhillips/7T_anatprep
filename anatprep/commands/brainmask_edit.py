"""
brainmask-edit command: refine the brainmask in ITK-Snap.

After inspecting fMRIprep output, run this command to
manually edit the brainmask. The edited mask is saved into the
next iteration directory. Then ``anatprep fmriprep`` is re-run.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from anatprep.commands import iter_sessions
from anatprep.core import (
    IterationState,
    setup_logging,
)


def run_brainmask_edit(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Opens ITK-Snap to refine the brainmask, then advance the iteration."""
    subjects = iter_sessions(studydir, subject, session)

    for sub in subjects:
        log_file = sub.log_dir / "brainmask_edit.log"
        logger = setup_logging("brainmask_edit", log_file, verbose)
        sub.ensure_deriv_dirs()

        state = IterationState(sub.deriv_dir)

        if state.is_finalized:
            logger.info(f"Iteration already finalized for {sub}. Nothing to do.")
            continue

        if not state.can_advance:
            logger.warning(
                f"Cannot advance: already at max iterations. "
                f"Current: {state.current_iteration}"
            )
            continue

        current_iter = state.current_iteration
        logger.info(f"{sub} - iteration {current_iter}, status: {state.status}")

        # find the brainmask to edit
        # TODO: locate the fMRIprep/FreeSurfer brainmask from the current
        # iteration. For now, look in the iteration directory.
        iter_dir = sub.iter_dir(current_iter)
        brainmask = _find_brainmask(sub, iter_dir, logger)

        if brainmask is None:
            logger.error("No brainmask found to edit. Run fMRIprep first.")
            continue

        # background image
        t1w = (
            sub.find_deriv_file("desc-denoised", run=sub.get_mp2rage_runs()[0])
            or sub.find_deriv_file("desc-pymp2rage", run=sub.get_mp2rage_runs()[0])
        )
        if t1w is None:
            logger.error("No T1w found for background image.")
            continue

        logger.info(f"Launching ITK-Snap")
        logger.info(f"  Background: {t1w.name}")
        logger.info(f"  Brainmask:  {brainmask.name}")
        logger.info("  Edit the mask, save (Ctrl+S), and close ITK-Snap.")

        cmd = ["itksnap", "-g", str(t1w), "-s", str(brainmask)]

        try:
            subprocess.run(cmd, check=False)
        except FileNotFoundError:
            logger.error("ITK-Snap not found. Install it or add it to PATH.")
            return

        # advance to next iteration
        state.set_status("awaiting_edit", "User edited brainmask")
        new_iter = state.advance()
        logger.info(
            f"Advanced to iteration {new_iter}. "
            f"Run 'anatprep fmriprep' to re-run with the refined mask."
        )

        # copy the edited mask to the new iteration dir
        new_iter_dir = sub.iter_dir(new_iter)
        dst = new_iter_dir / brainmask.name
        shutil.copy2(brainmask, dst)
        logger.info(f"Copied edited mask to iter-{new_iter}/")


def _find_brainmask(sub, iter_dir: Path, logger) -> Optional[Path]:
    """
    Locate the brainmask for the current iteration.

    First checks the iteration directory, then falls back to
    the FreeSurfer output.
    """
    # check iteration dir
    masks = list(iter_dir.glob("*mask*"))
    if masks:
        return masks[0]

    # check FreeSurfer output (common location)
    fs_dir = sub.studydir / "derivatives" / "freesurfer" / sub.sub_prefix
    if fs_dir.exists():
        # FreeSurfer brainmask.mgz would need conversion
        brainmask_mgz = fs_dir / "mri" / "brainmask.mgz"
        if brainmask_mgz.exists():
            logger.info("Found FreeSurfer brainmask.mgz --> converting to NIfTI")
            brainmask_nii = iter_dir / "brainmask_fs.nii.gz"
            try:
                subprocess.run(
                    ["mri_convert", str(brainmask_mgz), str(brainmask_nii)],
                    check=True, capture_output=True,
                )
                return brainmask_nii
            except (subprocess.CalledProcessError, FileNotFoundError):
                logger.warning("mri_convert failed. Is FreeSurfer on PATH?")

    return None
