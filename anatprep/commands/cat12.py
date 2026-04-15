"""
cat12 command: run CAT12 tissue segmentation via SPM/MATLAB.

Usage:
  anatprep cat12 INPUT [OUTPUT_DIR]

INPUT is typically a denoised (optionally B1-corrected) T1w image.
OUTPUT_DIR defaults to ``<cwd>/<input_stem>_cat12``.

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
    setup_logging,
    load_anatprep_config,
    config_get,
    resolve_studydir,
    run_command,
    input_stem,
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
        output_dir = Path.cwd() / f"cat12"
    else:
        output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("cat12", log_file=log_dir / "cat12.log", verbose=verbose)
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

    script = _find_script("cat12_batch.sh")
    cmd = [
        "bash", str(script),
        "-s", str(spm_path),
        "-m", str(matlab_cmd),
        "-i", str(input_image),
        "-o", str(output_dir),
        "-l", str(log_dir),
    ]
    run_command(cmd, logger)

    success, msg = _check_cat12_outputs(output_dir)
    if success:
        logger.info(f"CAT12 complete: {msg}")
    else:
        raise RuntimeError(f"CAT12 did not produce expected outputs: {msg}")