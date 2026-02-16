"""
cat12 command: run CAT12 tissue segmentation via SPM/MATLAB.

Wraps the cat12_batch.sh script. CAT12 produces output files
in a ``cat12/run-{N}`` subdirectory under derivatives.

Only processes B1-corrected denoised T1w for now.

Expected CAT12 outputs (in mri/ subdir):
  - p0*.nii : tissue label image (0=BG, 1=CSF, 2=GM, 3=WM)
  - p1*.nii : native GM probability map
  - p2*.nii : native WM probability map
  - p3*.nii : native CSF probability map
"""

from pathlib import Path
from typing import Optional, Tuple

from anatprep.commands import iter_sessions
from anatprep.commands.spm_mask import _find_script
from anatprep.core import (
    setup_logging,
    load_anatprep_config,
    config_get,
    run_command,
)


def _check_cat12_outputs(cat12_dir: Path) -> Tuple[bool, str]:
    """
    Check CAT12 output directory for successful completion.

    Returns (success, message). Success = True if tissue maps exist.
    """
    mri_dir = cat12_dir / "mri"

    if not mri_dir.exists():
        return False, "mri/ directory not created"

    # native space tissue prob maps
    p1_files = list(mri_dir.glob("p1*.nii*"))
    p2_files = list(mri_dir.glob("p2*.nii*"))
    p3_files = list(mri_dir.glob("p3*.nii*"))

    if p1_files and p2_files and p3_files:
        return True, "tissue maps (p1/p2/p3) produced"

    # count outputs
    all_outputs = list(mri_dir.glob("*.nii*"))
    if all_outputs:
        return False, f"partial output ({len(all_outputs)} files, missing tissue maps)"

    return False, "no outputs produced"


def run_cat12(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    subjects = iter_sessions(studydir, subject, session)

    config = load_anatprep_config(studydir)
    spm_path = config_get(config, "tools.spm_path")
    matlab_cmd = config_get(config, "tools.matlab_cmd", "matlab")

    if not spm_path:
        raise RuntimeError("spm_path not set in code/anatprep_config.yml.")

    for sub in subjects:
        log_file = sub.log_dir / "cat12.log"
        logger = setup_logging("cat12", log_file, verbose)
        sub.ensure_deriv_dirs()

        runs = sub.get_mp2rage_runs()
        logger.info(f"Processing {sub} - runs: {runs}")

        for run in runs:
            # for now only B1-corrected denoised T1w
            denoised = sub.find_deriv_file("desc-denoisedb1corr_T1w", run=run)
            if denoised is None:
                logger.warning(
                    f"No denoised T1w found for run-{run}.\n"
                    "Currently the script only runs on b1-corrected denoised outputs."
                    "Run 'anatprep denoise' first.\n"
                )
                continue

            cat12_dir = sub.deriv_dir / "cat12" / f"run-{run}"
            cat12_dir.mkdir(parents=True, exist_ok=True)

            # check outputs
            success, msg = _check_cat12_outputs(cat12_dir)
            if success and not force:
                logger.info(f"CAT12 already complete for run-{run} ({msg}). Skipping.")
                continue

            # cleanup previous if force
            if force:
                for subdir in ["mri", "label", "err", "report"]:
                    d = cat12_dir / subdir
                    if d.exists():
                        for f in d.glob("*"):
                            f.unlink()

            logger.info(f"Running CAT12 on {denoised.name}")

            script = _find_script("cat12_batch.sh")
            cmd = [
                "bash", str(script),
                "-s", str(spm_path),
                "-m", str(matlab_cmd),
                "-i", str(denoised),
                "-o", str(cat12_dir),
                "-l", str(sub.log_dir),
            ]
            run_command(cmd, logger)

            # verify outputs exists after running
            success, msg = _check_cat12_outputs(cat12_dir)
            if success:
                logger.info(f"CAT12 completed for run-{run}: {msg}")
            else:
                logger.warning(f"CAT12 did not produce expected outputs for run-{run}: {msg}")