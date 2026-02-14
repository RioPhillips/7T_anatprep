"""
spm-mask command: creates brain mask from INV2 using SPM segmentation.

Wraps the spm_mask.sh bash script and spmBrainMask.m MATLAB function
that ship with the package.
"""

import importlib.resources
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


def run_spm_mask(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Create brain mask from INV2 image using SPM."""
    subjects = iter_sessions(studydir, subject, session)
    config = load_anatprep_config(studydir)

    spm_path = config_get(config, "tools.spm_path")
    matlab_cmd = config_get(config, "tools.matlab_cmd", "matlab")

    if not spm_path:
        raise RuntimeError(
            "spm_path not set in code/anatprep_config.yml.\n"
            "Add:\n  tools:\n    spm_path: /path/to/spm"
        )

    for sub in subjects:
        log_file = sub.log_dir / "spm_mask.log"
        logger = setup_logging("spm_mask", log_file, verbose)
        sub.ensure_deriv_dirs()

        runs = sub.get_mp2rage_runs()
        logger.info(f"Processing {sub}, runs: {runs}")

        for run in runs:
            output = sub.deriv_path("spmmask", "mask", run=run)

            should_run, _ = check_outputs_exist([output], logger, force)
            if not should_run:
                continue

            # locate INV2 in rawdata
            try:
                inv2 = sub.get_raw_inv2(run)
            except FileNotFoundError:
                logger.warning(f"INV2 not found for run-{run}, trying inv-2_part-mag")
                try:
                    inv2 = sub.get_rawdata_file("inv-2_part-mag_MP2RAGE", run)
                except FileNotFoundError:
                    logger.error(f"No INV2 image found for run-{run}. Skipping.")
                    continue

            logger.info(f"INV2: {inv2.name}")
            logger.info(f"Output: {output}")

            # find the spm_mask.sh script shipped with the package
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
                logger.error(f"SPM mask was not produced for run-{run}")


def _find_script(name: str) -> Path:
    """Locate a script from the anatprep/scripts/ directory."""
    # this is when anatprep is installed as a package
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    candidate = scripts_dir / name
    if candidate.exists():
        return candidate

    raise FileNotFoundError(
        f"Script '{name}' not found in {scripts_dir}.\n"
        "Make sure the anatprep package is installed correctly."
    )
