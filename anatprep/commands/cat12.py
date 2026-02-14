"""
cat12 command: run CAT12 tissue segmentation via SPM/MATLAB.

Wraps the cat12_batch.sh script. CAT12 produces many output files
so they go into a ``cat12/`` subdirectory under derivatives.
"""

from pathlib import Path
from typing import Optional

from anatprep.commands import iter_sessions
from anatprep.commands.spm_mask import _find_script
from anatprep.core import (
    setup_logging,
    load_anatprep_config,
    config_get,
    run_command,
    check_outputs_exist,
)


def run_cat12(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Run CAT12 segmentation on denoised T1w."""
    subjects = iter_sessions(studydir, subject, session)
    config = load_anatprep_config(studydir)

    spm_path = config_get(config, "tools.spm_path")
    matlab_cmd = config_get(config, "tools.matlab_cmd", "matlab")

    if not spm_path:
        raise RuntimeError(
            "spm_path not set in code/anatprep_config.yml."
        )

    for sub in subjects:
        log_file = sub.log_dir / "cat12.log"
        logger = setup_logging("cat12", log_file, verbose)
        sub.ensure_deriv_dirs()

        runs = sub.get_mp2rage_runs()
        logger.info(f"Processing {sub} - runs: {runs}")

        for run in runs:
            cat12_dir = sub.deriv_dir / "cat12" / f"run-{run}"
            cat12_dir.mkdir(parents=True, exist_ok=True)

            # check if already done (CAT12 writes mwp1* and p0* files)
            existing_outputs = (
                list(cat12_dir.glob("mwp1*")) + list(cat12_dir.glob("p0*"))
            )
            if existing_outputs and not force:
                logger.info(f"CAT12 outputs exist for run-{run}. Skipping.")
                continue

            # input: denoised T1w from denoise.py
            denoised = sub.find_deriv_file("desc-denoised", run=run)
            if denoised is None:
                logger.error(
                    f"Denoised T1w not found for run-{run}. "
                    "Run 'anatprep denoise' first."
                )
                continue

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

            # verify something was produced
            new_outputs = list(cat12_dir.glob("mwp1*")) + list(cat12_dir.glob("p0*"))
            if new_outputs:
                logger.info(f"CAT12 produced {len(new_outputs)} files in {cat12_dir.name}/")
            else:
                logger.warning(f"CAT12 did not produce expected outputs for run-{run}")
