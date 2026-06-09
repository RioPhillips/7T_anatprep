"""
mask command(s) for anatprep.

Two operations live here:

  run_mask        Create a brain mask from an INV2 image.
                    --bet  FSL BET (default)
                    --spm  SPM segmentation via MATLAB
                  -> outputs a MASK.

  run_apply_mask  Apply a mask to an image: keep voxels where mask > 0,
                  zero the rest. This is the "pial edit before recon-all"
                  step that produces the masked T1w fed to FreeSurfer.
                  -> outputs a MASKED IMAGE.

Usage:
  anatprep mask INPUT [OUTPUT] [--bet | --spm]
  anatprep apply-mask --input IMG --mask MASK [--out OUT] [--winsorize]
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional
from uuid import uuid4

import numpy as np
import nibabel as nib

from anatprep.core import (
    default_output,
    check_output,
    setup_command_logging,
    load_anatprep_config,
    config_get,
    resolve_studydir,
    run_command,
)


_DESC_LABELS = {"spm": "spmmask", "bet": "bet"}


def run_mask(
    input_image: Path,
    output_image: Optional[Path],
    method: str = "bet",
    force: bool = False,
    verbose: bool = False,
) -> None:
    method = method.lower()
    if method not in _DESC_LABELS:
        raise ValueError(f"Unknown masking method '{method}'. Choose 'spm' or 'bet'.")

    desc = _DESC_LABELS[method]
    input_image = Path(input_image).resolve()

    if output_image is None:
        output_image = default_output(input_image, desc)
    else:
        output_image = Path(output_image).resolve()

    output_image.parent.mkdir(parents=True, exist_ok=True)

    logger, log_dir = setup_command_logging("mask", input_image, verbose=verbose)
    logger.info(f"Method: {'FSL BET' if method == 'bet' else 'SPM'}")
    logger.info(f"Input : {input_image}")
    logger.info(f"Output: {output_image}")

    if not check_output(output_image, logger, force):
        return

    if method == "bet":
        _run_bet(input_image, output_image, logger)
    else:
        _run_spm(input_image, output_image, logger, log_dir)


# ---------------------------------------------------------------------------
# apply-mask: bake a mask into an image (pial edit before FreeSurfer)
# ---------------------------------------------------------------------------

def run_apply_mask(
    input_image: Path,
    mask: Path,
    output_image: Optional[Path] = None,
    winsorize: bool = False,
    lower: float = 0.01,
    upper: float = 0.95,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """
    Apply a mask to an image by KEEPING voxels where mask > 0 and zeroing
    the rest, then (optionally) winsorize/rescale/recast.

    The mask FOREGROUND is kept. For the sinus/dura-excluding brain mask
    produced by sinus-auto / sinus-edit, this zeros the sinus, dura, and
    everything outside the brain, leaving a clean T1w for recon-all. (Note
    this also strips the skull; recon-all tolerates skull-stripped input.)

    `winsorize` is off by default because `denoise` already runs WSD;
    enabling it here would truncate intensities a second time.
    """
    input_image = Path(input_image).resolve()
    mask = Path(mask).resolve()

    if output_image is None:
        output_image = default_output(input_image, "masked")
    else:
        output_image = Path(output_image).resolve()

    output_image.parent.mkdir(parents=True, exist_ok=True)

    logger, log_dir = setup_command_logging("apply-mask", input_image, verbose=verbose)
    logger.info(f"Input    : {input_image}")
    logger.info(f"Mask     : {mask}")
    logger.info(f"Output   : {output_image}")
    logger.info(f"Winsorize: {winsorize}")

    if not check_output(output_image, logger, force):
        return

    img = nib.load(str(input_image))
    mask_img = nib.load(str(mask))

    if img.shape != mask_img.shape:
        raise ValueError(
            f"Image/mask shape mismatch: {img.shape} vs {mask_img.shape}.\n"
            f"The mask must be on the same grid as the image. Sinus masks are "
            f"produced in T1w space, so pass the matching T1w."
        )

    data = img.get_fdata()
    keep = mask_img.get_fdata() > 0
    masked = data * keep

    n_kept = int(np.sum(keep))
    n_total = int(keep.size)
    logger.info(f"Voxels kept (mask>0): {n_kept} / {n_total}")
    if n_kept == 0:
        raise RuntimeError(
            "Mask is empty (no voxels > 0); refusing to write an all-zero image. "
            "Check the mask polarity (foreground must be the region to KEEP)."
        )

    nib.Nifti1Image(masked, img.affine, img.header).to_filename(str(output_image))
    logger.info(f"Masked image written: {output_image.name}")

    if winsorize:
        from anatprep.utils import winsorize_rescale_dtype
        winsorize_rescale_dtype(
            output_image, output_image, logger, lower=lower, upper=upper
        )
        logger.info("Applied WSD (winsorize -> rescale -> uint16)")


# ---------------------------------------------------------------------------
# BET backend
# ---------------------------------------------------------------------------

_BET_FRAC = "0.3"
_BET_GRAD = "-0.1"


def _run_bet(input_image: Path, output_image: Path, logger) -> None:
    if shutil.which("bet") is None:
        raise RuntimeError("FSL 'bet' not found in PATH.")

    logger.info(f"BET parameters: -f {_BET_FRAC} -g {_BET_GRAD}")

    tmp_prefix = output_image.parent / f".bet_tmp_{uuid4().hex}"

    cmd = [
        "bet",
        str(input_image),
        str(tmp_prefix),
        "-f", _BET_FRAC,
        "-g", _BET_GRAD,
        "-m",
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.error(f"BET failed (exit {exc.returncode}): {exc.stderr.strip()}")
        raise RuntimeError("BET failed") from exc

    bet_mask = Path(f"{tmp_prefix}_mask.nii.gz")
    bet_brain = Path(f"{tmp_prefix}.nii.gz")

    if not bet_mask.exists():
        raise RuntimeError("BET did not produce expected mask file.")

    shutil.move(str(bet_mask), str(output_image))
    if bet_brain.exists():
        bet_brain.unlink()

    logger.info(f"Mask written: {output_image.name}")


# ---------------------------------------------------------------------------
# SPM backend
# ---------------------------------------------------------------------------

def _run_spm(input_image: Path, output_image: Path, logger, log_dir: Optional[Path] = None) -> None:
    studydir = resolve_studydir()
    config = load_anatprep_config(studydir)
    spm_path = config_get(config, "tools.spm_path")
    matlab_cmd = config_get(config, "tools.matlab_cmd", "matlab")

    if not spm_path:
        raise RuntimeError(
            "spm_path not set in code/anatprep.yml.\n"
            "Add:\n  tools:\n    spm_path: /path/to/spm"
        )

    script = _find_script("spm_mask.sh")

    # Use central log dir if available, otherwise fall back to output dir
    matlab_log_dir = str(log_dir) if log_dir else str(output_image.parent)

    cmd = [
        "bash", str(script),
        "-s", str(spm_path),
        "-m", str(matlab_cmd),
        str(input_image),
        str(output_image),
    ]

    env = {"LOG_DIR": matlab_log_dir}
    run_command(cmd, logger, env=env)

    if not output_image.exists():
        raise RuntimeError("SPM mask script did not produce the expected output.")

    logger.info(f"Mask written: {output_image.name}")


def _find_script(name: str) -> Path:
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    candidate = scripts_dir / name
    if not candidate.exists():
        raise FileNotFoundError(
            f"Script '{name}' not found in {scripts_dir}. "
            "Is anatprep installed correctly?"
        )
    return candidate