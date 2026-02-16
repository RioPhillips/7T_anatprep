"""
sinus-auto command: auto-generate a sagittal sinus exclusion mask.

Strategy:

1. Anatomical ROI restriction
   - Constrain analysis to a superior, midline region.
   - Optionally intersect with brain mask.
   - Reduces false positives in cortex and ventricles.

2. T1w-based candidate detection
   - Compute intensity statistics within the ROI only.
   - Apply adaptive high-intensity threshold
     (mean + k*std or percentile-based).
     
3. Optional FLAIR refinement (if available)
   - Register FLAIR → T1w (FLIRT, 6 DOF, mutual information).
   - Sinus voxels tend to remain bright on T1w but not on FLAIR.

4. Post-processing
   - Remove small components (this is quite conservative, might change depending on output).
   - Preserve non-empty result.

The result is a *starting point* for manual editing
in ITK-Snap via ``anatprep sinus-edit``.
"""

from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np
from scipy import ndimage

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

        for run in runs:
            output = sub.deriv_path("sinusauto", "mask", run=run)

            should_run, _ = check_outputs_exist([output], logger, force)
            if not should_run:
                continue

            # need T1w from pymp2rage (or denoised)
            t1w = (
                sub.find_deriv_file("desc-denoised", run=run)
                or sub.find_deriv_file("desc-pymp2rage", run=run)
            )
            if t1w is None:
                logger.error(f"No T1w found for run-{run}. Run earlier steps first.")
                continue

            # brain mask from SPM
            brain_mask = sub.find_deriv_file("desc-spmmask", run=run)

            if sub.has_flair():
                flair_files = sub.get_flair_files()
                logger.info(f"FLAIR found ({len(flair_files)} files) --> utilizing intersection with T1w")
                _sinus_from_flair(
                    t1w=t1w,
                    flair=flair_files[0],  # use first FLAIR
                    brain_mask=brain_mask,
                    output=output,
                    work_dir=sub.deriv_dir,
                    logger=logger,
                )
            else:
                logger.info("No FLAIR found --> using intensity threshold on T1w only")
                _sinus_from_intensity(
                    t1w=t1w,
                    brain_mask=brain_mask,
                    output=output,
                    logger=logger,
                )

            if output.exists():
                logger.info(f"Auto sinus mask: {output.name}")
                logger.info("Run 'anatprep sinus-edit' to refine manually.")
            else:
                logger.error(f"Sinus mask was not produced for run-{run}")


def _sinus_from_flair(
    t1w: Path,
    flair: Path,
    brain_mask: Optional[Path],
    output: Path,
    work_dir: Path,
    logger,
) -> None:
    """
    Generate sinus mask from FLAIR and T1w with anatomical constraints.

    The sagittal sinus appears bright in T1w but NOT in FLAIR.
    Pipeline:
        1. Register FLAIR --> T1w (FLIRT 6-DOF, mutual information)
        2. Load images and optional brain mask
        3. Build anatomical ROI (midline ±7 voxels, superior 40%)
        4. Threshold T1w inside ROI (mean + 1.5*std, adaptive fallback)
        5. Exclude voxels bright in FLAIR (anti-mask, ROI-based)
        6. Apply brain mask if available
        7. Keep largest connected component
        8. Save result
    """
    # 1. Register FLAIR --> T1w using mutual information cost
    flair_reg = work_dir / f"flair_in_t1w_{flair.stem}.nii.gz"
    xfm_dir = work_dir / "xfm"
    xfm_dir.mkdir(parents=True, exist_ok=True)
    mat_file = xfm_dir / f"flair_to_t1w_{flair.stem}.mat"

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

    # 2. load images
    t1w_img = nib.load(str(t1w))
    t1w_data = t1w_img.get_fdata().astype(np.float32)

    flair_img = nib.load(str(flair_reg))
    flair_data = flair_img.get_fdata().astype(np.float32)

    nx, ny, nz = t1w_data.shape[:3]

    # load brain mask if available
    brain_mask_data = None
    if brain_mask is not None and Path(brain_mask).exists():
        brain_mask_data = nib.load(str(brain_mask)).get_fdata() > 0
        logger.info("Brain mask loaded for ROI restriction")

    # 3. anatomical ROI: midline + superior restriction
    # midline band: ±7 voxels around x-center
    midline_half_width = 7
    x_center = nx // 2
    x_lo = max(0, x_center - midline_half_width)
    x_hi = min(nx, x_center + midline_half_width + 1)

    midline_mask = np.zeros_like(t1w_data, dtype=bool)
    midline_mask[x_lo:x_hi, :, :] = True

    # superior restriction: keep top 40% of volume in Z
    z_cut = int(0.6 * nz)
    superior_mask = np.zeros_like(t1w_data, dtype=bool)
    superior_mask[:, :, z_cut:] = True

    roi_mask = midline_mask & superior_mask
    logger.info(
        f"Anatomical ROI: midline x=[{x_lo}:{x_hi}] (center={x_center}), "
        f"superior z>{z_cut} (of {nz})"
    )

    # 4. threshold T1w inside ROI (mean + 1.5*std within ROI)
    # compute statistics inside ROI (intersected with brain mask if available)
    stat_region = roi_mask.copy()
    if brain_mask_data is not None:
        stat_region &= brain_mask_data

    roi_values = t1w_data[stat_region]
    logger.info(f"Voxels in ROI: {roi_values.size}")
    if roi_values.size == 0:
        logger.error("No valid voxels in ROI, aborting")
        return

    t1w_mean = np.mean(roi_values)
    t1w_std = np.std(roi_values)
    t1w_thresh = t1w_mean + 1.5 * t1w_std
    logger.info(
        f"T1w threshold: mean={t1w_mean:.1f}, std={t1w_std:.1f}, "
        f"cutoff={t1w_thresh:.1f} (mean + 1.5*std)"
    )

    t1w_bright = (t1w_data > t1w_thresh) & roi_mask

    # adaptive fallback if too few voxels survive
    n_vox = int(np.sum(t1w_bright))
    logger.info(f"Voxels above threshold: {n_vox}")
    if n_vox < 50:
        t1w_thresh_relaxed = t1w_mean + 1.0 * t1w_std
        logger.warning(
            f"Only {n_vox} voxels survived threshold, relaxing to "
            f"mean + 1.0*std = {t1w_thresh_relaxed:.1f}"
        )
        t1w_bright = (t1w_data > t1w_thresh_relaxed) & roi_mask
        n_vox = int(np.sum(t1w_bright))
        logger.info(f"Voxels after relaxed threshold: {n_vox}")

    # 5. FLAIR anti-mask: exclude voxels bright in FLAIR (ROI-based)
    flair_values = flair_data[stat_region]
    if flair_values.size > 0 and np.any(flair_values > 0):
        flair_thresh = np.percentile(flair_values[flair_values > 0], 90)
        flair_bright = flair_data > flair_thresh
        logger.info(
            f"FLAIR anti-mask: excluding voxels above {flair_thresh:.1f} "
            f"(90th pctile within ROI)"
        )
        sinus = (t1w_bright & ~flair_bright).astype(np.uint8)
    else:
        logger.warning(
            "FLAIR ROI empty or all-zero, skipping FLAIR anti-mask"
        )
        sinus = t1w_bright.astype(np.uint8)

    # 6. apply brain mask
    if brain_mask_data is not None:
        sinus = sinus * brain_mask_data.astype(np.uint8)

    # 7. keep largest connected component
    total_voxels = int(np.sum(sinus))
    if total_voxels >= 100:
        labeled, n_components = ndimage.label(sinus)
        if n_components > 0:
            component_sizes = ndimage.sum(
                sinus, labeled, range(1, n_components + 1)
            )
            largest_label = np.argmax(component_sizes) + 1
            sinus = (labeled == largest_label).astype(np.uint8)
            logger.info(
                f"Connected components: {n_components} found, "
                f"kept largest (size={int(component_sizes[largest_label - 1])} voxels)"
            )
        else:
            logger.warning(
                "No connected components found, saving pre-CC mask as seed"
            )
    elif total_voxels > 0:
        logger.warning(
            f"Only {total_voxels} voxels in mask (<100), "
            f"skipping CC filtering to preserve seed mask"
        )
    else:
        logger.warning("Sinus mask is empty - image may need manual inspection")

    # 8. save
    output.parent.mkdir(parents=True, exist_ok=True)
    nib.Nifti1Image(sinus, t1w_img.affine, t1w_img.header).to_filename(str(output))


def _sinus_from_intensity(
    t1w: Path,
    brain_mask: Optional[Path],
    output: Path,
    logger,
) -> None:
    """
    Generate a rough sinus mask from T1w intensity alone.
    """
    t1w_img = nib.load(str(t1w))
    data = t1w_img.get_fdata().astype(np.float32)

    # threshold at 95% atm
    thresh = np.percentile(data[data > 0], 95) if np.any(data > 0) else 1
    sinus = (data > thresh).astype(np.uint8)

    if brain_mask is not None and Path(brain_mask).exists():
        mask_data = nib.load(str(brain_mask)).get_fdata() > 0
        sinus = sinus * mask_data.astype(np.uint8)

    output.parent.mkdir(parents=True, exist_ok=True)
    nib.Nifti1Image(sinus, t1w_img.affine, t1w_img.header).to_filename(str(output))