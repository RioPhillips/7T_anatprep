"""
pymp2rage command: compute T1w (UNIT1), T1map, and a brain mask from the
MP2RAGE inversion components. Optionally applies B1 correction if a
DREAM (or other) TB1map is provided.

Usage:
  anatprep pymp2rage \\
      --inv1-mag <FILE> --inv1-phase <FILE> \\
      --inv2-mag <FILE> --inv2-phase <FILE> \\
      [--b1map <FILE>] [--b1mag <FILE>] \\
      [--out-dir <DIR>]

B1 correction:
  If --b1map is given, the T1w and T1map outputs are additionally corrected
  for B1+ inhomogeneities (Marques & Gruetter, 2013).

  The B1 map **must be in the same space** as the MP2RAGE inversions.
  Two options:

  1. Pre-registered B1 map:   pass only --b1map.
  2. Automatic registration:  pass both --b1map and --b1mag, where --b1mag
     is the magnitude/FID companion of the B1 acquisition (e.g. the
     ``_magnitude.nii.gz`` produced by a Philips DREAM sequence). The
     magnitude image is registered to INV1 with FLIRT (6-DOF, mutual info)
     and the resulting transform is applied to the B1 map.

  The registration matrix is cached in ``<out-dir>/../xfm/`` and the
  registered B1 map in ``<out-dir>/``, so subsequent runs reuse them
  unless --force is set.

Outputs (written to --out-dir, default CWD):
  <prefix>_desc-pymp2rage_T1w.nii.gz
  <prefix>_desc-pymp2rage_T1map.nii.gz
  <prefix>_desc-pymp2rage_mask.nii.gz

If --b1map is given, two additional outputs:
  <prefix>_desc-pymp2rageb1corr_T1w.nii.gz
  <prefix>_desc-pymp2rageb1corr_T1map.nii.gz

<prefix> is derived from the BIDS entities (sub, ses, run) shared by
the four inversion inputs. All inputs must agree on these entities.
Reads acquisition parameters from code/mp2rage.yaml.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Optional

from anatprep.core import (
    setup_command_logging,
    resolve_studydir,
    load_mp2rage_params,
    check_consistent_entities,
    bids_prefix,
    input_stem,
    check_output,
    run_command,
)


def _check_external(binary: str, package: str) -> None:
    """Raise if *binary* is not on PATH."""
    if shutil.which(binary) is None:
        raise RuntimeError(f"'{binary}' not found in PATH. Install {package}.")


def _register_b1(
    b1mag: Path,
    b1map: Path,
    ref: Path,
    out_dir: Path,
    prefix: str,
    logger,
    force: bool = False,
) -> Path:
    """Register B1 magnitude to *ref* (INV1) and apply the transform to the
    B1 map.  Returns the path to the registered B1 map.

    Intermediate outputs
    --------------------
    <out_dir>/<b1mag_stem>_space-inv1.nii.gz   – registered magnitude (QC)
    <out_dir>/../xfm/<b1mag_stem>_space-inv1.mat – FLIRT matrix
    <out_dir>/<prefix>_desc-reg_TB1map.nii.gz  – registered B1 map (used)
    """
    _check_external("flirt", "FSL")

    b1mag_stem = input_stem(b1mag)

    # Paths
    xfm_dir = out_dir.parent / "xfm"
    xfm_mat = xfm_dir / f"{b1mag_stem}_space-inv1.mat"
    mag_reg = out_dir / f"{b1mag_stem}_space-inv1.nii.gz"
    b1_reg = out_dir / f"{prefix}_desc-reg_TB1map.nii.gz"

    # --- step 1: estimate transform (magnitude → INV1) --------------------
    have_cached = mag_reg.exists() and xfm_mat.exists()
    if have_cached and not force:
        logger.info(f"Reusing cached B1-mag registration: {xfm_mat.name}")
    else:
        xfm_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Registering B1 magnitude --> INV1 (FLIRT 6-DOF, mutual info)")
        run_command([
            "flirt",
            "-in", str(b1mag),
            "-ref", str(ref),
            "-out", str(mag_reg),
            "-omat", str(xfm_mat),
            "-dof", "6",
            "-cost", "mutualinfo",
            "-searchrx", "-90", "90",
            "-searchry", "-90", "90",
            "-searchrz", "-90", "90",
            "-interp", "trilinear",
        ], logger)
        logger.info(f"  --> {mag_reg.name}")
        logger.info(f"  --> {xfm_mat.name}")

    # --- step 2: apply transform to actual B1 map -------------------------
    if b1_reg.exists() and not force:
        logger.info(f"Reusing cached registered B1 map: {b1_reg.name}")
    else:
        logger.info("Applying transform to B1 map")
        run_command([
            "flirt",
            "-in", str(b1map),
            "-ref", str(ref),
            "-out", str(b1_reg),
            "-init", str(xfm_mat),
            "-applyxfm",
            "-interp", "trilinear",
        ], logger)
        logger.info(f"  --> {b1_reg.name}")

    return b1_reg


def run_pymp2rage(
    inv1_mag: Path,
    inv1_phase: Path,
    inv2_mag: Path,
    inv2_phase: Path,
    out_dir: Optional[Path] = None,
    b1map: Optional[Path] = None,
    b1mag: Optional[Path] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    inv1_mag = Path(inv1_mag).resolve()
    inv1_phase = Path(inv1_phase).resolve()
    inv2_mag = Path(inv2_mag).resolve()
    inv2_phase = Path(inv2_phase).resolve()
    b1map = Path(b1map).resolve() if b1map else None
    b1mag = Path(b1mag).resolve() if b1mag else None

    # Validate B1 argument combinations
    if b1mag and not b1map:
        raise ValueError(
            "--b1mag requires --b1map. Provide the B1 map alongside its "
            "magnitude companion."
        )

    out_dir = Path(out_dir).resolve() if out_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    logger, log_dir = setup_command_logging("pymp2rage", inv1_mag, verbose=verbose)

    # Verify all four inversion inputs share sub/ses/run entities
    inputs = [inv1_mag, inv1_phase, inv2_mag, inv2_phase]
    try:
        entities = check_consistent_entities(inputs)
    except ValueError as e:
        logger.error(str(e))
        raise

    prefix = bids_prefix(entities, fallback=input_stem(inv1_mag))
    logger.info(f"Derived prefix: {prefix}")
    if entities:
        logger.info(f"  entities: {entities}")

    # Output paths
    t1w_out = out_dir / f"{prefix}_desc-pymp2rage_T1w.nii.gz"
    t1map_out = out_dir / f"{prefix}_desc-pymp2rage_T1map.nii.gz"
    mask_out = out_dir / f"{prefix}_desc-pymp2rage_mask.nii.gz"
    t1w_b1_out = out_dir / f"{prefix}_desc-pymp2rageb1corr_T1w.nii.gz"
    t1map_b1_out = out_dir / f"{prefix}_desc-pymp2rageb1corr_T1map.nii.gz"

    need_basic = any(
        check_output(p, logger, force) for p in (t1w_out, t1map_out, mask_out)
    )
    need_b1corr = (
        b1map is not None
        and any(check_output(p, logger, force) for p in (t1w_b1_out, t1map_b1_out))
    )

    if not need_basic and not need_b1corr:
        logger.info("All outputs already exist. Nothing to do.")
        return

    # Acquisition parameters, still loaded from code/mp2rage.yaml
    studydir = resolve_studydir()
    params = load_mp2rage_params(studydir)
    if params is None:
        raise RuntimeError(
            "code/mp2rage.yaml not found or missing required keys. "
            "Required: RepetitionTimeExcitation, RepetitionTimePreparation, "
            "InversionTime, NumberShots, FlipAngle."
        )

    try:
        from anatprep.vendor.pymp2rage import MP2RAGE
    except ImportError as e:
        raise ImportError("Vendored pymp2rage not found.") from e

    logger.info(f"Fitting MP2RAGE")
    logger.info(f"  INV1 mag  : {inv1_mag.name}")
    logger.info(f"  INV1 phase: {inv1_phase.name}")
    logger.info(f"  INV2 mag  : {inv2_mag.name}")
    logger.info(f"  INV2 phase: {inv2_phase.name}")
    logger.info(f"  B1 map    : {b1map.name if b1map else '(none)'}")
    logger.info(f"  B1 mag    : {b1mag.name if b1mag else '(none, assuming B1 pre-registered)'}")
    logger.info(f"  Out dir   : {out_dir}")

    fitter = MP2RAGE(
        MPRAGE_tr=params["RepetitionTimePreparation"],
        invtimesAB=params["InversionTime"],
        flipangleABdegree=params["FlipAngle"],
        nZslices=params["NumberShots"],
        FLASH_tr=[
            params["RepetitionTimeExcitation"],
            params["RepetitionTimeExcitation"],
        ],
        inv1=str(inv1_mag),
        inv1ph=str(inv1_phase),
        inv2=str(inv2_mag),
        inv2ph=str(inv2_phase),
    )

    if need_basic:
        fitter.fit_mask()
        fitter.t1w_uni.to_filename(str(t1w_out))
        fitter.t1map.to_filename(str(t1map_out))
        fitter.mask.to_filename(str(mask_out))
        logger.info(f"  --> {t1w_out.name}")
        logger.info(f"  --> {t1map_out.name}")
        logger.info(f"  --> {mask_out.name}")

    if b1map and need_b1corr:
        # Register B1 map if magnitude companion provided
        if b1mag:
            b1map_for_corr = _register_b1(
                b1mag=b1mag,
                b1map=b1map,
                ref=inv1_mag,
                out_dir=out_dir,
                prefix=prefix,
                logger=logger,
                force=force,
            )
        else:
            logger.info(
                "No --b1mag provided; assuming B1 map is already in "
                "INV1 space."
            )
            b1map_for_corr = b1map

        try:
            logger.info("Applying B1 correction")
            t1_corr, t1w_corr = fitter.correct_for_B1(str(b1map_for_corr))
            t1w_corr.to_filename(str(t1w_b1_out))
            t1_corr.to_filename(str(t1map_b1_out))
            logger.info(f"  --> {t1w_b1_out.name}")
            logger.info(f"  --> {t1map_b1_out.name}")
        except Exception as e:
            logger.warning(f"B1 correction failed: {e}")
            logger.warning("Continuing with uncorrected outputs only.")