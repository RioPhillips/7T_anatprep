"""
brainmask-edit command: launch freeview to inspect / edit a FreeSurfer subject's
brainmask.mgz and wm.mgz, with the canonical surface overlay layout.

Opens:
    mri/brainmask.mgz   (background, editable)
    mri/wm.mgz          (heat overlay, opacity 0.4, editable)
    surf/{l,r}h.white   (edges, blue)
    surf/{l,r}h.pial    (edges, red)
    surf/{l,r}h.inflated (hidden by default)

Before launching freeview, md5 of brainmask.mgz and wm.mgz are snapshotted.
After freeview exits they are recomputed, and a hint is logged indicating
which ``anatprep freesurfer ... --edit <pial|wm>`` invocation to run next:

    brainmask.mgz changed only  ->  --edit pial
    wm.mgz changed (+/- bm)     ->  --edit wm
    nothing changed              ->  no rerun needed

Usage:
  anatprep brainmask-edit FS_SUBJECT_DIR
"""

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import List

from anatprep.core import setup_command_logging



def run_brainmask_edit(
    fs_subject_dir: Path,
    verbose: bool = False,
) -> None:
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

    # setup_command_logging extracts the BIDS 'sub' entity from the path, so
    # the log lands under derivatives/logs/anatprep/sub-<X>/ even when the
    # subject directory name is e.g. sub-S01_ses-MR1.
    logger, _ = setup_command_logging("brainmask-edit", fs_subject_dir, verbose=verbose)
    logger.info(f"FS subject directory: {fs_subject_dir}")

    _refuse_if_running(fs_subject_dir)

    brainmask = mri / "brainmask.mgz"
    wm = mri / "wm.mgz"
    if not brainmask.exists():
        raise FileNotFoundError(f"brainmask.mgz not found: {brainmask}")
    if not wm.exists():
        raise FileNotFoundError(f"wm.mgz not found: {wm}")

    if shutil.which("freeview") is None:
        raise RuntimeError("'freeview' not found in PATH. Is FreeSurfer sourced?")

    # snapshot
    pre_brainmask = _md5(brainmask)
    pre_wm = _md5(wm)
    logger.debug(f"pre-edit md5 brainmask.mgz: {pre_brainmask}")
    logger.debug(f"pre-edit md5 wm.mgz       : {pre_wm}")

    # launch
    cmd = _build_freeview_cmd(fs_subject_dir)
    logger.info("Launching freeview. Edit the masks, save (Ctrl+S), then close.")
    logger.debug("Command: " + " ".join(cmd))
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        raise RuntimeError("'freeview' not found in PATH. Is FreeSurfer sourced?")

    # post-snapshot + hint
    post_brainmask = _md5(brainmask)
    post_wm = _md5(wm)
    bm_changed = post_brainmask != pre_brainmask
    wm_changed = post_wm != pre_wm

    logger.info(f"brainmask.mgz: {'changed' if bm_changed else 'unchanged'}")
    logger.info(f"wm.mgz       : {'changed' if wm_changed else 'unchanged'}")

    if wm_changed:
        logger.info(
            "Next step (wm +/- brainmask edits): "
            "anatprep freesurfer <t1w> --edit wm"
        )
    elif bm_changed:
        logger.info(
            "Next step (brainmask edits only): "
            "anatprep freesurfer <t1w> --edit pial"
        )
    else:
        logger.info("No edits detected. No rerun required.")


# Helpers

def _build_freeview_cmd(fs_subject_dir: Path) -> List[str]:
    mri = fs_subject_dir / "mri"
    surf = fs_subject_dir / "surf"
    return [
        "freeview",
        "-v", str(mri / "brainmask.mgz"),
        f"{mri / 'wm.mgz'}:colormap=heat:opacity=0.4",
        "-f", f"{surf / 'lh.white'}:edgecolor=blue",
        f"{surf / 'lh.pial'}:edgecolor=red",
        f"{surf / 'rh.white'}:edgecolor=blue",
        f"{surf / 'rh.pial'}:edgecolor=red",
        f"{surf / 'rh.inflated'}:visible=0",
        f"{surf / 'lh.inflated'}:visible=0",
    ]


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _refuse_if_running(fs_subject_dir: Path) -> None:
    scripts = fs_subject_dir / "scripts"
    if not scripts.exists():
        return
    for hemi in ("lh", "rh", "lh+rh"):
        flag = scripts / f"IsRunning.{hemi}"
        if flag.exists():
            raise RuntimeError(
                f"recon-all appears to be running ({flag} present). "
                f"Refusing to open freeview. If recon-all is not running, "
                f"delete that flag file manually."
            )