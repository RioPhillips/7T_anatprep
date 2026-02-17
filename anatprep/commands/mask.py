"""
mask command: creates brain mask from INV2 image.

Supports two ways of masking:
  - spm:  SPM segmentation via MATLAB (robust, slow)
  - bet:  FSL BET extraction (fast, practical)

Wraps spm_mask.sh / spmBrainMask.m for SPM, or calls FSL BET directly.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from anatprep.commands import iter_sessions
from anatprep.core import (
    Subject,
    setup_logging,
    load_anatprep_config,
    config_get,
    run_command,
    check_outputs_exist,
)

# desc label used in BIDS output filename per method
_DESC_LABELS = {
    "spm": "spmmask",
    "bet": "bet",
}


def run_mask(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
    method: str = "spm",
) -> None:
    """Create brain mask from INV2 image.

    Parameters
    ----------
    studydir : Path
        Root of the BIDS study directory.
    subject : str
        Subject ID (without sub- prefix).
    session : str, optional
        Session ID (without ses- prefix). Processes all if omitted.
    force : bool
        Overwrite existing outputs.
    verbose : bool
        Enable verbose logging.
    method : str
        Masking: ``"spm"`` or ``"bet"``.
    """
    method = method.lower()
    if method not in ("spm", "bet"):
        raise ValueError(f"Unknown masking method '{method}'. Choose 'spm' or 'bet'.")

    desc = _DESC_LABELS[method]
    subjects = iter_sessions(studydir, subject, session)
    config = load_anatprep_config(studydir)

    # method-specific setup
    if method == "spm":
        spm_path = config_get(config, "tools.spm_path")
        matlab_cmd = config_get(config, "tools.matlab_cmd", "matlab")

        if not spm_path:
            raise RuntimeError(
                "spm_path not set in code/anatprep_config.yml.\n"
                "Add:\n  tools:\n    spm_path: /path/to/spm"
            )

    elif method == "bet":
        if shutil.which("bet") is None:
            raise RuntimeError(
                "FSL BET not found in PATH.\n"
                "Install FSL or ensure 'bet' is on your PATH."
            )

    # per-subject / per-session loop
    for sub in subjects:
        log_file = sub.log_dir / "mask.log"
        logger = setup_logging("mask", log_file, verbose)
        sub.ensure_deriv_dirs()

        method_label = "SPM" if method == "spm" else "FSL BET"
        logger.info(f"Using brain mask method: {method_label}")

        runs = sub.get_mp2rage_runs()
        logger.info(f"Processing {sub}, runs: {runs}")

        for run in runs:
            output = sub.deriv_path(desc, "mask", run=run)

            should_run, _ = check_outputs_exist([output], logger, force)
            if not should_run:
                continue

            # locate INV2 in rawdata
            inv2 = _find_inv2(sub, run, logger)
            if inv2 is None:
                continue

            logger.info(f"INV2: {inv2.name}")
            logger.info(f"Output: {output}")

            if method == "spm":
                _run_spm(sub, inv2, output, spm_path, matlab_cmd, logger)
            else:
                _run_bet(sub, inv2, output, logger)


# INV2 lookup (shared by both methods)

def _find_inv2(sub: Subject, run: int, logger) -> Optional[Path]:
    """Locate the INV2 image, trying multiple naming conventions."""
    try:
        return sub.get_raw_inv2(run)
    except FileNotFoundError:
        pass

    try:
        logger.warning(f"INV2 not found for run-{run}, trying inv-2_part-mag")
        return sub.get_rawdata_file("inv-2_part-mag_MP2RAGE", run)
    except FileNotFoundError:
        logger.error(f"No INV2 image found for run-{run}. Skipping.")
        return None


# SPM

def _run_spm(
    sub: Subject,
    inv2: Path,
    output: Path,
    spm_path: str,
    matlab_cmd: str,
    logger,
) -> None:
    """Run SPM-based brain masking (MATLAB + spmBrainMask.m)."""
    script = _find_script("spm_mask.sh")

    cmd = [
        "bash", str(script),
        "-s", str(spm_path),
        "-m", str(matlab_cmd),
        str(inv2),
        str(output),
    ]

    env = {"LOG_DIR": str(sub.log_dir)}
    run_command(cmd, logger, env=env)

    if output.exists():
        logger.info(f"Mask created: {output.name}")
    else:
        logger.error(f"SPM mask was not produced for run")


# BET backend

_BET_FRAC = "0.3"
_BET_GRAD = "-0.1"


def _run_bet(
    sub: Subject,
    inv2: Path,
    output: Path,
    logger,
) -> None:
    """Run FSL BET-based brain masking."""
    logger.info(f"BET parameters: -f {_BET_FRAC} -g {_BET_GRAD}")

    # BET writes <prefix>_mask.nii.gz when given -m
    tmp_prefix = sub.deriv_dir / "_bet_tmp"

    cmd = [
        "bet",
        str(inv2),
        str(tmp_prefix),
        "-f", _BET_FRAC,
        "-g", _BET_GRAD,
        "-m",
    ]

    logger.info(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout:
            logger.debug(result.stdout.strip())
    except subprocess.CalledProcessError as exc:
        logger.error(f"BET failed (exit {exc.returncode})")
        if exc.stderr:
            logger.error(exc.stderr.strip())
        return

    # BET produces: <prefix>_mask.nii.gz  and  <prefix>.nii.gz (brain)
    bet_mask = Path(f"{tmp_prefix}_mask.nii.gz")
    bet_brain = Path(f"{tmp_prefix}.nii.gz")

    if not bet_mask.exists():
        logger.error("BET did not produce expected mask file.")
        return

    # move mask to final output path
    shutil.move(str(bet_mask), str(output))
    logger.info(f"Mask created: {output.name}")

    # clean up temporary brain-extracted image
    if bet_brain.exists():
        bet_brain.unlink()
        logger.debug("Removed temporary BET brain image.")


# script locator (for SPM)

def _find_script(name: str) -> Path:
    """Locate a script from the anatprep/scripts/ directory."""
    # when anatprep is installed as a package
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    candidate = scripts_dir / name
    if candidate.exists():
        return candidate

    raise FileNotFoundError(
        f"Script '{name}' not found in {scripts_dir}.\n"
        "Make sure the anatprep package is installed correctly."
    )