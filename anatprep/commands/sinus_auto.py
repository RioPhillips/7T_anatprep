"""
sinus-auto command: auto-generate a sagittal sinus exclusion mask.

Strategy (requires FLAIR):
    1. Register FLAIR --> T1w (FLIRT 6-DOF, mutual information).
    2. Apply existing INV2/SPM brain mask to the registered FLAIR.
       This removes skull etc, which otherwise break BET on FLAIR.
    3. Run FSL BET on the masked FLAIR. Because FLAIR lacks sagittal
       sinus signal, BET produces a brain mask that naturally excludes
       the sinus.
    4. Dilate the mask with MRtrix ``maskfilter`` for robustness.

Outputs per run:
    - desc-sinusauto_mask.nii.gz          (undilated BET mask)
    - desc-sinusauto_mask_dilated.nii.gz  (dilated mask)

Kept intermediates:
    - Registered FLAIR in derivatives dir
    - Transform matrix in xfm/ subdir

If no FLAIR is available, sinus-auto cannot run.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np

from anatprep.commands import iter_sessions
from anatprep.core import (
    setup_logging,
    check_outputs_exist,
    run_command,
)


def run_sinus_auto(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    subjects = iter_sessions(studydir, subject, session)

    for sub in subjects:
        log_file = sub.log_dir / "sinus_auto.log"
        logger = setup_logging("sinus_auto", log_file, verbose)
        sub.ensure_deriv_dirs()

        runs = sub.get_mp2rage_runs()
        logger.info(f"Processing {sub} - runs: {runs}")

        if not sub.has_flair():
            logger.warning(
                "No FLAIR found. sinus-auto requires FLAIR images. "
                "Run 'anatprep sinus-edit' to create the mask manually on the T1w."
            )
            continue

        flair_files = sub.get_flair_files()
        logger.info(f"FLAIR found ({len(flair_files)} files)")

        for run in runs:
            output = sub.deriv_path("sinusauto", "mask", run=run)
            output_dilated = output.parent / output.name.replace(
                "_mask.nii.gz", "_mask_dilated.nii.gz"
            )

            should_run, _ = check_outputs_exist(
                [output, output_dilated], logger, force
            )
            if not should_run:
                continue

            # T1w: prefer b1-corrected, fall back to standard
            t1w = (
                sub.find_deriv_file("desc-denoisedb1corr", run=run)
                or sub.find_deriv_file("desc-pymp2rageb1corr", run=run)
                or sub.find_deriv_file("desc-denoised", run=run)
                or sub.find_deriv_file("desc-pymp2rage", run=run)
            )
            if t1w is None:
                logger.error(f"No T1w found for run-{run}. Run earlier steps first.")
                continue

            # brain mask: prefer BET, fall back to SPM
            brain_mask = sub.find_deriv_file("desc-bet", run=run)
            if brain_mask is None:
                brain_mask = sub.find_deriv_file("desc-spmmask", run=run)
            if brain_mask is None:
                logger.error("No INV2-based mask found. Run 'anatprep mask' first.")
                continue

            _sinus_from_flair(
                t1w=t1w,
                flair=flair_files[0],
                brain_mask=brain_mask,
                output=output,
                output_dilated=output_dilated,
                work_dir=sub.deriv_dir,
                logger=logger,
            )

            if output.exists():
                logger.info(f"Auto sinus mask: {output.name}")
                logger.info(f"Dilated sinus mask: {output_dilated.name}")
                logger.info("Run 'anatprep sinus-edit' to refine manually.")
            else:
                logger.error(f"Sinus mask was not produced for run-{run}")


def _sinus_from_flair(
    t1w: Path,
    flair: Path,
    brain_mask: Path,
    output: Path,
    output_dilated: Path,
    work_dir: Path,
    logger,
) -> None:
    """
    Generate sinus mask from FLAIR via BET.

    Pipeline:
        1. Register FLAIR --> T1w (FLIRT 6-DOF, mutual information)
        2. Multiply registered FLAIR by brain mask (removes skull)
        3. Run BET on masked FLAIR (produces mask excluding sinus)
        4. Dilate with MRtrix maskfilter
        5. Save undilated and dilated masks

    Intermediate files (masked FLAIR, raw BET output) are created in
    a temporary directory and cleaned up automatically.
    """
    # 0.  dependencies
    if shutil.which("bet") is None:
        raise RuntimeError(
            "FSL 'bet' not found in PATH. Install FSL or update your PATH."
        )
    if shutil.which("maskfilter") is None:
        raise RuntimeError(
            "MRtrix 'maskfilter' not found in PATH. "
            "Install MRtrix3 or update your PATH."
        )

    # 1. register FLAIR --> T1w (kept in derivatives)
    
    flair_base = flair.name.replace(".nii.gz", "").replace(".nii", "")
    flair_bids = flair_base.replace("_FLAIR", "_space-t1w_FLAIR")
    flair_reg = work_dir / f"{flair_bids}.nii.gz"
    xfm_dir = work_dir / "xfm"
    xfm_dir.mkdir(parents=True, exist_ok=True)
    mat_file = xfm_dir / f"{flair_bids}.mat"

    if not flair_reg.exists():
        logger.info("Registering FLAIR --> T1w (FLIRT 6-DOF, mutual info)")
        cmd = [
            "flirt",
            "-in", str(flair),
            "-ref", str(t1w),
            "-out", str(flair_reg),
            "-omat", str(mat_file),
            "-dof", "6",
            "-cost", "mutualinfo",
            "-searchrx", "-90", "90",
            "-searchry", "-90", "90",
            "-searchrz", "-90", "90",
            "-interp", "trilinear",
        ]
        run_command(cmd, logger)

    # 2–3. mask FLAIR + BET (in temp dir, removed after)
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        tmp = Path(tmp)

        # apply brain mask to registered FLAIR
        logger.info("Applying brain mask to registered FLAIR")
        flair_img = nib.load(str(flair_reg))
        flair_data = flair_img.get_fdata().astype(np.float32)
        mask_data = nib.load(str(brain_mask)).get_fdata() > 0
        masked_flair_data = flair_data * mask_data.astype(np.float32)

        masked_flair_path = tmp / "flair_masked.nii.gz"
        nib.Nifti1Image(
            masked_flair_data, flair_img.affine, flair_img.header
        ).to_filename(str(masked_flair_path))

        # run BET
        logger.info("Running BET on masked FLAIR (f=0.3, g=-0.1)")
        bet_prefix = tmp / "bet_flair"
        bet_mask = tmp / "bet_flair_mask.nii.gz"

        cmd = [
            "bet",
            str(masked_flair_path),
            str(bet_prefix),
            "-f", "0.3",
            "-g", "-0.1",
            "-m",
        ]
        run_command(cmd, logger)

        if not bet_mask.exists():
            logger.error(
                "BET did not produce expected mask. "
                "Check BET output and FLAIR quality."
            )
            return

        n_voxels = int(np.sum(nib.load(str(bet_mask)).get_fdata() > 0))
        logger.info(f"BET mask voxels: {n_voxels}")

        # copy undilated mask to final output
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(bet_mask), str(output))
        logger.info(f"Undilated mask saved: {output.name}")

    # 4. dilate the saved undilated mask
    dilate_npass = 1
    logger.info(f"Dilating mask with maskfilter (npass={dilate_npass})")
    cmd = [
        "maskfilter",
        str(output),
        "dilate",
        str(output_dilated),
        "-npass", str(dilate_npass),
        "-force",
    ]
    run_command(cmd, logger)

    if output_dilated.exists():
        n_dilated = int(np.sum(nib.load(str(output_dilated)).get_fdata() > 0))
        logger.info(f"Dilated mask voxels: {n_dilated}")
    else:
        logger.error("maskfilter did not produce dilated mask")