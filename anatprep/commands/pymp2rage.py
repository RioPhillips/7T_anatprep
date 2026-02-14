"""
pymp2rage command: computes clean T1w (UNIT1) and T1map from MP2RAGE inversions.

Optionally applies B1 correction using DREAM TB1map if available.
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

# to be updated to handle more kinds of b1 fieldmaps
def _find_tb1map(sub, run: int, logger) -> Optional[Path]:
    """
    Find B1 fildmap for a given run.
    
    Looks in rawdata/sub-XX/ses-YY/fmap/ for files matching:
        *_acq-dream_run-{run}_TB1map.nii.gz
    
    Returns None if not found.
    """
    if sub.fmap_dir is None or not sub.fmap_dir.exists():
        logger.debug(f"No fmap directory found for {sub}")
        return None
    
    pattern = f"*_acq-dream_run-{run}_TB1map.nii.gz"
    matches = list(sub.fmap_dir.glob(pattern))
    
    if not matches:
        pattern_norun = "*_acq-dream_TB1map.nii.gz"
        matches_norun = list(sub.fmap_dir.glob(pattern_norun))
        if matches_norun:
            logger.warning(
                f"No TB1map found for run-{run}, but found TB1map without run tag. "
                f"B1 correction skipped for run-{run}."
            )
        return None
    
    if len(matches) > 1:
        logger.warning(f"Multiple TB1maps found for run-{run}, using first: {matches[0].name}")
    
    return matches[0]



def run_pymp2rage(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """
    Compute T1w and T1map from MP2RAGE inversions.
    
    If a DREAM TB1map is available (matched by run number), also produces
    B1-corrected T1w and T1map outputs.
    
    Outputs
    -------
    For each run, produces in derivatives/anatprep/sub-XX/ses-YY/pymp2rage/:
    
    Always:
        - sub-XX_ses-YY_run-{N}_desc-pymp2rage_T1w.nii.gz       (UNIT1 image)
        - sub-XX_ses-YY_run-{N}_desc-pymp2rage_T1map.nii.gz     (quantitative T1)
        - sub-XX_ses-YY_run-{N}_desc-pymp2rage_mask.nii.gz      (brain mask from INV2)
    
    If TB1map available for that run:
        - sub-XX_ses-YY_run-{N}_desc-pymp2rageb1corr_T1w.nii.gz
        - sub-XX_ses-YY_run-{N}_desc-pymp2rageb1corr_T1map.nii.gz
    """
    subjects = iter_sessions(studydir, subject, session)

    mp2rage_params = load_mp2rage_params(studydir)
    if mp2rage_params is None:
        raise RuntimeError(
            "code/mp2rage.json not found or invalid.\n"
            "This file is required for pymp2rage fitting."
        )

    try:
        from anatprep.vendor.pymp2rage import MP2RAGE
    except ImportError:
        raise ImportError(
            "Vendored pymp2rage not found in package installation.\n"
        )

    for sub in subjects:
        log_file = sub.log_dir / "pymp2rage.log"
        logger = setup_logging("pymp2rage", log_file, verbose)
        sub.ensure_deriv_dirs()

        runs = sub.get_mp2rage_runs()
        logger.info(f"Processing {sub} - runs: {runs}")

        for run in runs:
            # output paths for base files
            t1w_out = sub.deriv_path("pymp2rage", "T1w", run=run, subdir="pymp2rage")
            t1map_out = sub.deriv_path("pymp2rage", "T1map", run=run, subdir="pymp2rage")
            mask_out = sub.deriv_path("pymp2rage", "mask", run=run, subdir="pymp2rage")
            
            # output paths for b1 corrected ones
            t1w_b1corr_out = sub.deriv_path("pymp2rageb1corr", "T1w", run=run, subdir="pymp2rage")
            t1map_b1corr_out = sub.deriv_path("pymp2rageb1corr", "T1map", run=run, subdir="pymp2rage")

            # check if base files already exist
            need_basic, _ = check_outputs_exist(
                [t1w_out, t1map_out, mask_out], logger, force
            )
            
            # check b1 map (matched by run)
            tb1map_path = _find_tb1map(sub, run, logger)
            
            # check if b1-corrected outputs exists and b1map available
            need_b1corr = False
            if tb1map_path:
                need_b1corr, _ = check_outputs_exist(
                    [t1w_b1corr_out, t1map_b1corr_out], logger, force
                )
            
            # skip if all exist
            if not need_basic and not need_b1corr:
                logger.debug(f"All outputs exist for run-{run}, skipping")
                continue

            # raw inversion images
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
            if tb1map_path:
                logger.info(f"  TB1map:     {tb1map_path.name}")
            else:
                logger.info(f"  TB1map:     not found for run-{run} (B1 correction skipped)")

            # mp2rage fitters
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
                # creates the object
                fitter = MP2RAGE(**fitter_params)
                
                # base files
                if need_basic:
                    fitter.fit_mask()

                    # output dir
                    t1w_out.parent.mkdir(parents=True, exist_ok=True)

                    # save base outputs
                    fitter.t1w_uni.to_filename(str(t1w_out))
                    fitter.t1map.to_filename(str(t1map_out))
                    fitter.mask.to_filename(str(mask_out))

                    logger.info(f"  --> T1w:   {t1w_out.name}")
                    logger.info(f"  --> T1map: {t1map_out.name}")
                    logger.info(f"  --> Mask:  {mask_out.name}")
                else:
                    logger.info(f"  Basic outputs exist, skipping")

                # b1-correction if possible
                if tb1map_path and need_b1corr:
                    try:
                        logger.info(f"  Applying B1 correction...")
                        
                        t1_corrected, t1w_corrected = fitter.correct_for_B1(str(tb1map_path))
                        
                        # save b1-corr outputs
                        t1w_b1corr_out.parent.mkdir(parents=True, exist_ok=True)
                        t1w_corrected.to_filename(str(t1w_b1corr_out))
                        t1_corrected.to_filename(str(t1map_b1corr_out))
                        
                        logger.info(f"  --> T1w (B1-corr):   {t1w_b1corr_out.name}")
                        logger.info(f"  --> T1map (B1-corr): {t1map_b1corr_out.name}")
                        
                    except Exception as e:
                        logger.warning(f"  B1 correction failed: {e}")
                        logger.warning(f"  Continuing with uncorrected outputs only")
                        
                elif tb1map_path and not need_b1corr:
                    logger.info(f"  B1-corrected outputs exist, skipping B1 correction")

            except Exception as e:
                logger.error(f"pymp2rage fitting failed for run-{run}: {e}")
                raise