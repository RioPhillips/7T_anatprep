"""
view-surfaces command: open freeview to inspect a FreeSurfer subject's
reconstructed white/pial surfaces over the brainmask.

Loads (read-only QC):
    mri/brainmask.mgz        greyscale background
    surf/{l,r}h.white        blue edges
    surf/{l,r}h.pial         red edges
    surf/{l,r}h.inflated     hidden by default

This is the surface-inspection counterpart to `brainmask-edit` (which does
the voxel editing in ITK-Snap). Inspect here to decide whether the surfaces
need correcting, then make the brainmask/wm edits with `brainmask-edit`.

Usage:
  anatprep view-surfaces FS_SUBJECT_DIR
"""

import shutil
import subprocess
from pathlib import Path
from typing import List

from anatprep.core import setup_command_logging


def run_view_surfaces(fs_subject_dir: Path, verbose: bool = False) -> None:
    fs_subject_dir = Path(fs_subject_dir).resolve()

    if not fs_subject_dir.is_dir():
        raise FileNotFoundError(f"FS subject directory not found: {fs_subject_dir}")

    mri = fs_subject_dir / "mri"
    surf = fs_subject_dir / "surf"
    if not mri.is_dir() or not surf.is_dir():
        raise RuntimeError(
            f"{fs_subject_dir} does not look like a FreeSurfer subject directory "
            f"(missing mri/ and/or surf/)."
        )

    logger, _ = setup_command_logging("view-surfaces", fs_subject_dir, verbose=verbose)
    logger.info(f"FS subject directory: {fs_subject_dir}")

    brainmask = mri / "brainmask.mgz"
    if not brainmask.exists():
        raise FileNotFoundError(f"brainmask.mgz not found: {brainmask}")

    if shutil.which("freeview") is None:
        raise RuntimeError("'freeview' not found in PATH. Is FreeSurfer sourced?")

    cmd = _build_freeview_cmd(fs_subject_dir)
    logger.info("Launching freeview for surface inspection.")
    logger.debug("Command: " + " ".join(cmd))
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        raise RuntimeError("'freeview' not found in PATH. Is FreeSurfer sourced?")


def _build_freeview_cmd(fs_subject_dir: Path) -> List[str]:
    mri = fs_subject_dir / "mri"
    surf = fs_subject_dir / "surf"
    return [
        "freeview",
        "-v", str(mri / "brainmask.mgz"),
        "-f",
        f"{surf / 'lh.white'}:edgecolor=blue",
        f"{surf / 'lh.pial'}:edgecolor=red",
        f"{surf / 'rh.white'}:edgecolor=blue",
        f"{surf / 'rh.pial'}:edgecolor=red",
        f"{surf / 'lh.inflated'}:visible=0",
        f"{surf / 'rh.inflated'}:visible=0",
    ]