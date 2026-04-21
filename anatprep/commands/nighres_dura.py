"""
nighres-dura command: estimate dura mater probability with Nighres and
write a binary dura mask.

Usage:
  anatprep nighres-dura INV2 BRAIN_MASK [OUTPUT_IMAGE] [--threshold T]

Requires the ``nighres`` Python package (plus its dependencies: psutil,
antspyx, dipy).  Install with::

    pip install nighres
    pip install psutil antspyx dipy

Or via the anatprep extras::

    pip install "anatprep[nighres]"

Make sure the nighres package is importable in your current environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import shutil

import nibabel as nib
import numpy as np

from anatprep.core import (
    setup_command_logging,
    default_output,
    check_output,
    load_anatprep_config,
    config_get,
    resolve_studydir,
)


def _check_nighres() -> None:
    """Raise with a helpful message if nighres is not importable."""
    try:
        import nighres  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "The 'nighres' Python package is not installed or not on your "
            "PYTHONPATH.\n\n"
            "To install nighres and its dependencies:\n"
            "  pip install nighres psutil antspyx dipy\n\n"
            "Or install via the anatprep extras:\n"
            "  pip install 'anatprep[nighres]'\n\n"
            "If you installed nighres manually, make sure your PYTHONPATH "
            "includes the directory containing the nighres package."
        )


def run_nighres_dura(
    inv2: Path,
    brain_mask: Path,
    output_image: Optional[Path] = None,
    threshold: Optional[float] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """
    Run Nighres MP2RAGE dura estimation and binarize the result.

    Parameters
    ----------
    inv2
        Second inversion magnitude image.
    brain_mask
        Brain mask for the INV2 image.
    output_image
        Final binary dura mask. If omitted, defaults to
        ``<inv2_stem>_dura_mask.nii.gz`` in the current directory.
    threshold
        Threshold applied to the dura probability map.  If omitted,
        read from config (``tools.nighres.dura_threshold``) or default
        to 0.8.
    force
        Overwrite existing output.
    verbose
        Verbose logging.
    """
    _check_nighres()

    inv2 = Path(inv2).resolve()
    brain_mask = Path(brain_mask).resolve()

    if output_image is None:
        output_image = default_output(inv2, "dura_mask")
    else:
        output_image = Path(output_image).resolve()

    output_image.parent.mkdir(parents=True, exist_ok=True)

    logger, log_dir = setup_command_logging("nighres-dura", inv2, verbose=verbose)

    if not inv2.exists():
        raise FileNotFoundError(f"INV2 image not found: {inv2}")
    if not brain_mask.exists():
        raise FileNotFoundError(f"Brain mask not found: {brain_mask}")

    # config 
    studydir = resolve_studydir()
    config = load_anatprep_config(studydir)

    if threshold is None:
        threshold = float(config_get(config, "tools.nighres.dura_threshold", 0.8))

    proba_image = _paired_proba_path(output_image)

    logger.info(f"Input INV2     : {inv2}")
    logger.info(f"Input mask     : {brain_mask}")
    logger.info(f"Output mask    : {output_image}")
    logger.info(f"Output proba   : {proba_image}")
    logger.info(f"Threshold      : {threshold}")

    if not check_output(output_image, logger, force):
        return

    if force:
        for p in (output_image, proba_image):
            if p.exists():
                p.unlink()

    # run nighres 
    from nighres.brain import mp2rage_dura_estimation

    logger.info("Running Nighres MP2RAGE dura estimation...")
    result = mp2rage_dura_estimation(
        str(inv2),
        str(brain_mask),
        save_data=True,
        output_dir=str(output_image.parent),
        file_name=_nighres_base_name(output_image),
    )

    # locate probability output 
    prob_file = _find_nighres_probability_file(
        output_image.parent, _nighres_base_name(output_image)
    )
    if prob_file is None or not prob_file.exists():
        raise RuntimeError("Nighres did not produce a dura probability file.")

    # threshold -> binary mask 
    logger.info(f"Thresholding probability map at {threshold}")
    prob_img = nib.load(str(prob_file))
    prob_data = prob_img.get_fdata()

    dura_mask_data = (prob_data >= threshold).astype(np.uint8)
    dura_img = nib.Nifti1Image(dura_mask_data, prob_img.affine, prob_img.header.copy())
    dura_img.set_data_dtype(np.uint8)
    dura_img.to_filename(str(output_image))

    # Keep the probability image under a predictable name
    if proba_image.resolve() != prob_file.resolve():
        shutil.move(str(prob_file), str(proba_image))

    logger.info(f"Wrote dura mask : {output_image.name}")
    logger.info(f"Wrote proba map : {proba_image.name}")


# Helpers

def _nighres_base_name(path: Path) -> str:
    # strip .nii.gz / .nii to get a base name for nighres ``file_name
    name = path.name
    if name.endswith(".nii.gz"):
        return name[:-7]
    if name.endswith(".nii"):
        return name[:-4]
    return path.stem


def _paired_proba_path(output_mask: Path) -> Path:
    """
    Derive the probability-map path from the mask path.

    ``..._mask.nii.gz`` → ``..._proba.nii.gz``, otherwise
    ``<stem>_proba.nii.gz``.
    """
    name = output_mask.name
    if name.endswith("_mask.nii.gz"):
        return output_mask.with_name(name.replace("_mask.nii.gz", "_proba.nii.gz"))
    if name.endswith("_mask.nii"):
        return output_mask.with_name(name.replace("_mask.nii", "_proba.nii"))
    stem = _nighres_base_name(output_mask)
    return output_mask.with_name(f"{stem}_proba.nii.gz")


def _find_nighres_probability_file(root: Path, base: str) -> Optional[Path]:
    # find the Nighres dura probability output by glob pattern
    patterns = [
        f"{base}*dura*proba*.nii.gz",
        f"{base}*dura*prob*.nii.gz",
        f"{base}*dura-proba*.nii.gz",
        f"{base}*dura_proba*.nii.gz",
        f"{base}*proba*.nii.gz",
        f"{base}*prob*.nii.gz",
    ]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend([p for p in root.glob(pattern) if p.is_file()])

    if not candidates:
        return None

    return sorted(set(candidates))[0]