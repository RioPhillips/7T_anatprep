"""
mask command: creates a brain mask from an INV2 image.

Two backends:
  --bet  FSL BET (default)
  --spm  SPM segmentation via MATLAB

Usage:
  anatprep mask INPUT [OUTPUT] [--bet | --spm]

If OUTPUT is omitted, the mask is written to the current working directory
as ``<input_stem>_<desc>.nii.gz`` where desc is ``bet`` or ``spmmask``.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional
from uuid import uuid4


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
            "spm_path not set in code/anatprep_config.yml.\n"
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