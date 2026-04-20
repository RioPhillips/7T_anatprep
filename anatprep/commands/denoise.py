from pathlib import Path
from typing import Optional
import nibabel as nib
import numpy as np
import os

from anatprep.core import (
    setup_command_logging,
    default_output,
    check_output,
    run_command,
    load_anatprep_config,
    resolve_studydir,
    config_get,
    copy_logs_to_central,
)
from anatprep.commands.mask import _find_script

def run_denoise(
    t1w: Path,
    mask: Path,
    inv2: Path,
    out: Optional[Path] = None,
    run_sanlm: bool = True,
    run_bias: bool = True,
    force: bool = False,
    verbose: bool = False,
) -> None:
    t1w = Path(t1w).resolve()
    mask = Path(mask).resolve()
    inv2 = Path(inv2).resolve()
    if out is None:
        out = default_output(t1w, "denoised")
    else:
        out = Path(out).resolve()

    out.parent.mkdir(parents=True, exist_ok=True)
    logger, log_dir = setup_command_logging("denoise", t1w, verbose=verbose)

    if not check_output(out, logger, force):
        return

    # Temporary filenames
    tmp_heij = out.parent / f"tmp_heij_{out.name}"
    tmp_trunc = out.parent / f"tmp_trunc_{out.name}"

    # STEP 1: HEIJ / DE HOLLANDER (Background Removal)
    logger.info("Step 1: Applying background noise removal formula...")
    t1w_img = nib.load(str(t1w))
    mask_data = (nib.load(str(mask)).get_fdata() > 0).astype(np.float64)
    inv2_data = nib.load(str(inv2)).get_fdata().astype(np.float64)

    inv2_norm = inv2_data / np.max(inv2_data)
    mean_inside = float(np.mean(inv2_norm[mask_data == 1])) if np.any(mask_data == 1) else 1.0

    denoised_data = (t1w_img.get_fdata() * mask_data * mean_inside) + \
                    (t1w_img.get_fdata() * inv2_norm * (1 - mask_data))

    nib.Nifti1Image(denoised_data, t1w_img.affine, t1w_img.header).to_filename(str(tmp_heij))

    # STEP 2: ANTs IMAGEMATH (Intensity truncation)
    # Truncate at 0.1% and 99.9% to remove 7T intensity spikes
    logger.info("Step 2: Truncating intensities with ANTs ImageMath...")
    run_command([
        "ImageMath", "3", str(tmp_trunc), "TruncateImageIntensity",
        str(tmp_heij), "0.01", "0.999", "256"
    ], logger)

    # STEP 3: SANLM & BIAS CORRECTION
    if run_sanlm or run_bias:
        logger.info("Step 3: Running SANLM/SPM BIAS correction")
        script_path = _find_script("sanlm_batch.sh")

        studydir = resolve_studydir()
        config = load_anatprep_config(studydir)
        spm_path = config_get(config, "tools.spm_path")
        matlab_cmd = config_get(config, "tools.matlab_cmd", "matlab")

        cmd = [
            "bash", str(script_path),
            "-s", str(spm_path),
            "-m", str(matlab_cmd),
            "-i", str(tmp_trunc),
            "-o", str(out)
        ]
        if run_sanlm: cmd.append("-n")
        if run_bias: cmd.append("-b")

        run_command(cmd, logger)

        # Copy SANLM/bias logs to central log dir
        sanlm_local_log_dir = out.parent / "logs"
        if log_dir and sanlm_local_log_dir.exists():
            copy_logs_to_central(sanlm_local_log_dir, log_dir, prefix="sanlm_")
            logger.info(f"SANLM logs copied to {log_dir}")
    else:
        # If both are skipped, move the truncated file to final output
        tmp_trunc.rename(out)

    # CLEANUP
    if tmp_heij.exists(): tmp_heij.unlink()
    if tmp_trunc.exists(): tmp_trunc.unlink()

    logger.info(f"Denoising complete. Final output: {out}")