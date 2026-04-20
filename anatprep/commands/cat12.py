"""
cat12 command: run CAT12 tissue segmentation via SPM/MATLAB.

Usage:
  anatprep cat12 INPUT [OUTPUT_DIR]

INPUT is typically a denoised (optionally B1-corrected) T1w image.
OUTPUT_DIR defaults to ``<cwd>/cat12``.

Requires MATLAB + SPM + CAT12. Paths come from code/anatprep_config.yml.
Expected outputs (in OUTPUT_DIR/mri/):
    p0*.nii  - tissue label image
    p1*.nii  - native GM probability
    p2*.nii  - native WM probability
    p3*.nii  - native CSF probability
"""

from pathlib import Path
from typing import Optional, Tuple

from anatprep.core import (
    setup_command_logging,
    load_anatprep_config,
    config_get,
    resolve_studydir,
    run_command,
    copy_logs_to_central,
)
from anatprep.commands.mask import _find_script


def _check_cat12_outputs(cat12_dir: Path) -> Tuple[bool, str]:
    """Return (success, message). Success == True iff p1/p2/p3 tissue maps exist."""
    mri_dir = cat12_dir / "mri"
    if not mri_dir.exists():
        return False, "mri/ directory not created"

    p1 = list(mri_dir.glob("p1*.nii*"))
    p2 = list(mri_dir.glob("p2*.nii*"))
    p3 = list(mri_dir.glob("p3*.nii*"))
    if p1 and p2 and p3:
        return True, "tissue maps (p1/p2/p3) produced"

    n = len(list(mri_dir.glob("*.nii*")))
    if n:
        return False, f"partial output ({n} files, missing tissue maps)"
    return False, "no outputs produced"


def run_cat12(
    input_image: Path,
    output_dir: Optional[Path] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    input_image = Path(input_image).resolve()

    if output_dir is None:
        output_dir = Path.cwd() / "cat12"
    else:
        output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    logger, log_dir = setup_command_logging("cat12", input_image, verbose=verbose)
    logger.info(f"Input : {input_image}")
    logger.info(f"Output: {output_dir}")

    success, msg = _check_cat12_outputs(output_dir)
    if success and not force:
        logger.info(f"CAT12 already complete ({msg}). Use --force to re-run.")
        return

    if force:
        for subdir in ("mri", "label", "err", "report"):
            d = output_dir / subdir
            if d.exists():
                for f in d.glob("*"):
                    if f.is_file():
                        f.unlink()

    studydir = resolve_studydir()
    config = load_anatprep_config(studydir)
    spm_path = config_get(config, "tools.spm_path")
    matlab_cmd = config_get(config, "tools.matlab_cmd", "matlab")

    if not spm_path:
        raise RuntimeError("spm_path not set in code/anatprep_config.yml.")

    # Use central log dir if available, otherwise fall back to output dir
    cat12_log_dir = log_dir if log_dir else output_dir / "logs"
    cat12_log_dir.mkdir(parents=True, exist_ok=True)

    script = _find_script("cat12_batch.sh")
    cmd = [
        "bash", str(script),
        "-s", str(spm_path),
        "-m", str(matlab_cmd),
        "-i", str(input_image),
        "-o", str(output_dir),
        "-l", str(cat12_log_dir),
    ]

    try:
        run_command(cmd, logger)
    except RuntimeError:
        # The bash script exits 1 only when tissue maps are truly missing.
        # Double-check here to give a clear error message.
        success, msg = _check_cat12_outputs(output_dir)
        if success:
            logger.warning(
                f"CAT12 bash script returned error but tissue maps exist ({msg}). "
                "The error likely occurred during QC/reporting."
            )
            return
        raise RuntimeError(
            f"CAT12 failed and did not produce tissue maps: {msg}. "
            f"Check logs in: {cat12_log_dir}"
        )

    # If cat12 wrote logs to output_dir/logs (fallback case) and we have
    # a central log dir, copy them across
    local_log_dir = output_dir / "logs"
    if log_dir and local_log_dir.exists() and local_log_dir.resolve() != log_dir.resolve():
        copy_logs_to_central(local_log_dir, log_dir, prefix="cat12_")

    success, msg = _check_cat12_outputs(output_dir)
    if success:
        logger.info(f"CAT12 complete: {msg}")
    else:
        raise RuntimeError(f"CAT12 did not produce expected outputs: {msg}")