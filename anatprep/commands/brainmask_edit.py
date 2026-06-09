"""
brainmask-edit command: manually edit a FreeSurfer subject's brainmask.mgz
or wm.mgz in ITK-Snap.

ITK-Snap reads NIfTI (not FreeSurfer .mgz) and edits a single segmentation
layer per session, so this command:

  1. Converts the target volume (.mgz) and an anatomical reference to NIfTI
     via FreeSurfer's mri_convert.
  2. Opens ITK-Snap with the reference as the greyscale image and the target
     as the editable segmentation.
  3. After ITK-Snap closes, if the target changed, converts it back to .mgz
     (overwriting the original) and logs which run-freesurfer rerun to do next.

Because ITK-Snap edits one layer per session, pick the volume with --target:
    --target brainmask   edit mri/brainmask.mgz   (-> rerun --edit pial)
    --target wm          edit mri/wm.mgz          (-> rerun --edit wm)

To inspect the reconstructed surfaces (which ITK-Snap cannot render), use
`anatprep view-surfaces` (freeview).

Usage:
  anatprep brainmask-edit FS_SUBJECT_DIR [--target brainmask|wm]
"""

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from anatprep.core import setup_command_logging, run_command


_VALID_TARGETS = ("brainmask", "wm")


def run_brainmask_edit(
    fs_subject_dir: Path,
    target: str = "brainmask",
    verbose: bool = False,
) -> None:
    fs_subject_dir = Path(fs_subject_dir).resolve()

    if target not in _VALID_TARGETS:
        raise ValueError(f"--target must be one of {_VALID_TARGETS}, got {target!r}")

    if not fs_subject_dir.is_dir():
        raise FileNotFoundError(f"FS subject directory not found: {fs_subject_dir}")

    mri = fs_subject_dir / "mri"
    if not mri.is_dir():
        raise RuntimeError(
            f"{fs_subject_dir} does not look like a FreeSurfer subject directory "
            f"(missing mri/)."
        )

    logger, _ = setup_command_logging("brainmask-edit", fs_subject_dir, verbose=verbose)
    logger.info(f"FS subject directory: {fs_subject_dir}")
    logger.info(f"Editing target      : {target}")

    _refuse_if_running(fs_subject_dir)

    target_mgz = mri / f"{target}.mgz"
    if not target_mgz.exists():
        raise FileNotFoundError(f"{target}.mgz not found: {target_mgz}")

    ref_mgz = _reference_volume(mri, target)
    logger.info(f"Greyscale reference : {ref_mgz.name}")

    if shutil.which("mri_convert") is None:
        raise RuntimeError(
            "Failed to launch mri_convert. Please make sure it is on PATH "
            "(is FreeSurfer sourced?)."
        )
    if shutil.which("itksnap") is None:
        raise RuntimeError("Failed to launch itksnap. Please make sure it is on PATH.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ref_nii = tmp / "reference.nii.gz"
        target_nii = tmp / f"{target}.nii.gz"

        logger.info("Converting .mgz -> NIfTI for ITK-Snap")
        _mri_convert(ref_mgz, ref_nii, logger)
        _mri_convert(target_mgz, target_nii, logger)

        pre = _md5(target_nii)

        cmd = ["itksnap", "-g", str(ref_nii), "-s", str(target_nii)]
        logger.info("Launching ITK-Snap. Edit the segmentation, save (Ctrl+S), then close.")
        logger.debug("Command: " + " ".join(cmd))
        try:
            subprocess.run(cmd, check=False)
        except FileNotFoundError:
            raise RuntimeError(
                "Failed to launch itksnap. Please make sure it is on PATH."
            )

        post = _md5(target_nii)
        if post == pre:
            logger.info(f"{target}.mgz: unchanged (no save detected). No rerun required.")
            return

        logger.info(f"{target}.mgz: changed. Converting NIfTI -> .mgz")
        _preserve_original(target_mgz, logger)
        # brainmask.mgz / wm.mgz are uchar; keep them uchar on the way back.
        _mri_convert(target_nii, target_mgz, logger, out_dtype="uchar")

    if target == "brainmask":
        logger.info(
            "Next step (brainmask edit): anatprep run-freesurfer <t1w> --edit pial"
        )
    else:  # wm
        logger.info(
            "Next step (wm edit): anatprep run-freesurfer <t1w> --edit wm"
        )


# Helpers

def _preserve_original(target_mgz: Path, logger) -> None:
    """Copy the original .mgz to <name>.mgz.bak before it is overwritten.

    Only writes the backup if it doesn't already exist.
    """
    backup = target_mgz.with_name(f"{target_mgz.name}.bak")
    if backup.exists():
        logger.info(f"Original already preserved: {backup.name}")
        return
    shutil.copy2(str(target_mgz), str(backup))
    logger.info(f"Preserved original -> {backup.name}")

def _reference_volume(mri: Path, target: str) -> Path:
    """Pick a greyscale background that isn't the volume being edited."""
    if target == "wm":
        # show the brain anatomy under the WM labels
        candidates = ("brainmask.mgz", "norm.mgz", "T1.mgz")
    else:  # brainmask -> need an anatomical that isn't brainmask itself
        candidates = ("norm.mgz", "T1.mgz", "orig.mgz")
    for name in candidates:
        p = mri / name
        if p.exists():
            return p
    # last resort: the target itself (still works, just less useful)
    return mri / f"{target}.mgz"


def _mri_convert(src: Path, dst: Path, logger, out_dtype: Optional[str] = None) -> None:
    """Convert between .mgz and NIfTI with mri_convert (geometry preserved)."""
    cmd = ["mri_convert", str(src), str(dst)]
    if out_dtype:
        cmd += ["-odt", out_dtype]
    run_command(cmd, logger)
    if not dst.exists():
        raise RuntimeError(f"mri_convert did not produce {dst}")


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
                f"Refusing to open the editor. If recon-all is not running, "
                f"delete that flag file manually."
            )