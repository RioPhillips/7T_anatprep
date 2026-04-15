"""
pymp2rage command: compute T1w (UNIT1), T1map, and a brain mask from the
MP2RAGE inversion components. Optionally applies B1 correction if a
DREAM (or other) TB1map is provided.

Usage:
  anatprep pymp2rage \\
      --inv1-mag <FILE> --inv1-phase <FILE> \\
      --inv2-mag <FILE> --inv2-phase <FILE> \\
      [--b1map <FILE>] \\
      [--out-dir <DIR>]

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

from pathlib import Path
from typing import Optional

from anatprep.core import (
    setup_logging,
    resolve_studydir,
    load_mp2rage_params,
    check_consistent_entities,
    bids_prefix,
    input_stem,
    check_output,
)


def run_pymp2rage(
    inv1_mag: Path,
    inv1_phase: Path,
    inv2_mag: Path,
    inv2_phase: Path,
    out_dir: Optional[Path] = None,
    b1map: Optional[Path] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    inv1_mag = Path(inv1_mag).resolve()
    inv1_phase = Path(inv1_phase).resolve()
    inv2_mag = Path(inv2_mag).resolve()
    inv2_phase = Path(inv2_phase).resolve()
    b1map = Path(b1map).resolve() if b1map else None

    out_dir = Path(out_dir).resolve() if out_dir else Path.cwd()
    out_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("pymp2rage", verbose=verbose)

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
        try:
            logger.info("Applying B1 correction")
            t1_corr, t1w_corr = fitter.correct_for_B1(str(b1map))
            t1w_corr.to_filename(str(t1w_b1_out))
            t1_corr.to_filename(str(t1map_b1_out))
            logger.info(f"  --> {t1w_b1_out.name}")
            logger.info(f"  --> {t1map_b1_out.name}")
        except Exception as e:
            logger.warning(f"B1 correction failed: {e}")
            logger.warning("Continuing with uncorrected outputs only.")