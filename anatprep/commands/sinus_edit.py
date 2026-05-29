"""
sinus-edit command: open a manual mask editor (freeview or ITK-Snap) on a
sinus mask.

Usage:
  anatprep sinus-edit T1W MASK

Loads T1W as the background image and MASK as an editable overlay.
If MASK does not exist, an empty mask matching T1W is created first.

The editor is selected by ``tools.editing_software`` in code/anatprep.yml.
Supported values: ``freeview`` (default) and ``itksnap``.
"""

import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

import nibabel as nib
import numpy as np

from anatprep.core import (
    config_get,
    load_anatprep_config,
    resolve_studydir,
    setup_command_logging,
)


SUPPORTED_EDITORS = ("freeview", "itksnap")


def _build_editor_cmd(editor: str, t1w: Path, mask: Path) -> Tuple[str, List[str]]:
    # return (executable, full command) for the requested editor
    if editor == "freeview":
        cmd = [
            "freeview",
            "-v",
            str(t1w),
            f"{mask}:colormap=lut:opacity=0.5",
        ]
        return "freeview", cmd

    if editor == "itksnap":
        cmd = ["itksnap", "-g", str(t1w), "-s", str(mask)]
        return "itksnap", cmd

    raise ValueError(
        f"Unsupported editing_software '{editor}'. "
        f"Supported: {', '.join(SUPPORTED_EDITORS)}."
    )


def _resolve_editor() -> str:
    # read tools.editing_software from anatprep.yml. default to freeview
    try:
        studydir = resolve_studydir()
        config = load_anatprep_config(studydir)
    except Exception:
        config = {}

    editor = str(config_get(config, "tools.editing_software", "freeview")).lower()
    if editor not in SUPPORTED_EDITORS:
        raise RuntimeError(
            f"Unsupported editing_software '{editor}' in anatprep.yml. "
            f"Supported: {', '.join(SUPPORTED_EDITORS)}."
        )
    return editor


def run_sinus_edit(
    t1w: Path,
    mask: Path,
    verbose: bool = False,
    **_,  # accept force/etc from CLI without using them
) -> None:
    t1w = Path(t1w).resolve()
    mask = Path(mask).resolve()

    logger, _ = setup_command_logging("sinus-edit", t1w, verbose=verbose)
    logger.info(f"T1w : {t1w}")
    logger.info(f"Mask: {mask}")

    if not t1w.exists():
        raise FileNotFoundError(f"T1w image not found: {t1w}")

    editor = _resolve_editor()
    logger.info(f"Editing software: {editor}")

    if not mask.exists():
        logger.info(f"Mask does not exist; creating empty mask at {mask}")
        mask.parent.mkdir(parents=True, exist_ok=True)
        ref = nib.load(str(t1w))
        empty = np.zeros(ref.shape, dtype=np.uint8)
        nib.Nifti1Image(empty, ref.affine, ref.header).to_filename(str(mask))

    exe, cmd = _build_editor_cmd(editor, t1w, mask)

    if shutil.which(exe) is None:
        raise RuntimeError(
            f"Failed to launch {exe}. Please make sure it is on PATH."
        )

    logger.info(f"Launching {exe}; edit the mask, save, then close.")
    logger.debug("Command: " + " ".join(cmd))
    try:
        subprocess.run(cmd, check=False)
    except FileNotFoundError:
        raise RuntimeError(
            f"Failed to launch {exe}. Please make sure it is on PATH."
        )

    logger.info(f"Mask saved at: {mask}")