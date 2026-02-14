"""
pymp2rage command: computes clean T1w (UNIT1) and T1map.
Parameters come from code/mp2rage.json.
"""

from pathlib import Path
from typing import Optional

from anatprep.commands import iter_sessions
from anatprep.core import (
    setup_logging,
    load_anatprep_config,
    load_mp2rage_params,
    check_outputs_exist,
)


def run_pymp2rage(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Compute T1w and T1map from MP2RAGE inversions."""
    subjects = iter_sessions(studydir, subject, session)

    mp2rage_params = load_mp2rage_params(studydir)
    if mp2rage_params is None:
        raise RuntimeError(
            "code/mp2rage.json not found or invalid.\n"
            "This file is required for pymp2rage fitting."
        )

    # import early so we fail fast if not installed
    try:
        from pymp2rage import MP2RAGE
    except ImportError:
        raise ImportError(
            "pymp2rage is not installed in this environment.\n"
            "Install with:  pip install git+https://github.com/Gilles86/pymp2rage"
        )

    for sub in subjects:
        log_file = sub.log_dir / "pymp2rage.log"
        logger = setup_logging("pymp2rage", log_file, verbose)
        sub.ensure_deriv_dirs()

        runs = sub.get_mp2rage_runs()
        logger.info(f"Processing {sub} — runs: {runs}")

        for run in runs:
            t1w_out = sub.deriv_path("pymp2rage", "T1w", run=run)
            t1map_out = sub.deriv_path("pymp2rage", "T1map", run=run)
            mask_out = sub.deriv_path("pymp2rage", "mask", run=run)

            should_run, _ = check_outputs_exist(
                [t1w_out, t1map_out, mask_out], logger, force
            )
            if not should_run:
                continue

            # locate raw inversion images
            try:
                parts = sub.get_raw_mp2rage_parts(run)
            except FileNotFoundError as e:
                logger.error(f"Missing MP2RAGE files for run-{run}: {e}")
                continue

            logger.info(f"Fitting MP2RAGE run-{run}")
            logger.info(f"  INV1 mag:   {parts['inv1_mag'].name}")
            logger.info(f"  INV1 phase: {parts['inv1_phase'].name}")
            logger.info(f"  INV2 mag:   {parts['inv2_mag'].name}")
            logger.info(f"  INV2 phase: {parts['inv2_phase'].name}")

            # build MP2RAGE fitter
            fitter_params = {
                "MPRAGE_tr": mp2rage_params["RepetitionTimePreparation"],
                "invtimesAB": mp2rage_params["InversionTime"],
                "flipangleABdegree": mp2rage_params["FlipAngle"],
                "nZslices": mp2rage_params["NumberShots"],
                "FLASH_tr": [
                    mp2rage_params["RepetitionTimeExcitation"],
                    mp2rage_params["RepetitionTimeExcitation"],
                ],
                "inv1": str(parts["inv1_mag"]),
                "inv1ph": str(parts["inv1_phase"]),
                "inv2": str(parts["inv2_mag"]),
                "inv2ph": str(parts["inv2_phase"]),
            }

            try:
                fitter = MP2RAGE(**fitter_params)
                fitter.fit_mask()

                # write outputs
                t1w_out.parent.mkdir(parents=True, exist_ok=True)
                fitter.t1w_uni.to_filename(str(t1w_out))
                fitter.t1map.to_filename(str(t1map_out))
                fitter.mask.to_filename(str(mask_out))

                logger.info(f"  T1w:   {t1w_out.name}")
                logger.info(f"  T1map: {t1map_out.name}")
                logger.info(f"  Mask:  {mask_out.name}")

            except Exception as e:
                logger.error(f"pymp2rage fitting failed for run-{run}: {e}")
                raise
