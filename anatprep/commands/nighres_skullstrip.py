"""
nighres-skullstrip command: run Nighres MP2RAGE skullstripping.

Usage:
  anatprep nighres-skullstrip INV2 T1W T1MAP [OUTPUT_PREFIX]

Produces four outputs under ``<prefix>_mask / _inv2 / _t1w / _t1map``.

Requires the ``nighres`` Python package (plus its dependencies: psutil,
antspyx, dipy).  Install with::

    pip install nighres
    pip install psutil antspyx dipy

Or via the anatprep extras::

    pip install "anatprep[nighres]"
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import shutil

from anatprep.core import (
    setup_command_logging,
    check_output,
)


def _check_nighres() -> None:
    """Raise with a helpful message if nighres is not importable."""
    try:
        import nighres  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "The 'nighres' Python package is not installed or not on your "
            "PYTHONPATH.\n\n"
            "To install nighres and its dependencies:\n"
            "  pip install nighres psutil antspyx dipy\n\n"
            "Or install via the anatprep extras:\n"
            "  pip install 'anatprep[nighres]'\n\n"
            "If you installed nighres manually, make sure your PYTHONPATH "
            "includes the directory containing the nighres package."
        )


def run_nighres_skullstrip(
    inv2: Path,
    t1w: Path,
    t1map: Path,
    output_prefix: Optional[Path] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """
    Run Nighres MP2RAGE skullstripping.

    Parameters
    ----------
    inv2
        Second inversion magnitude image.
    t1w
        T1-weighted image.
    t1map
        T1 map image.
    output_prefix
        Base prefix for outputs.  If omitted, defaults to
        ``<inv2_stem>_strip`` in the INV2 directory.
        Outputs will be:
          ``<prefix>_mask.nii.gz``
          ``<prefix>_inv2.nii.gz``
          ``<prefix>_t1w.nii.gz``
          ``<prefix>_t1map.nii.gz``
    force
        Overwrite existing outputs.
    verbose
        Verbose logging.
    """
    _check_nighres()

    inv2 = Path(inv2).resolve()
    t1w = Path(t1w).resolve()
    t1map = Path(t1map).resolve()

    if output_prefix is None:
        output_prefix = inv2.parent / f"{_stem_nii_gz(inv2)}_strip"
    else:
        output_prefix = Path(output_prefix).resolve()

    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    logger, log_dir = setup_command_logging(
        "nighres-skullstrip", inv2, verbose=verbose
    )

    if not inv2.exists():
        raise FileNotFoundError(f"INV2 image not found: {inv2}")
    if not t1w.exists():
        raise FileNotFoundError(f"T1w image not found: {t1w}")
    if not t1map.exists():
        raise FileNotFoundError(f"T1map image not found: {t1map}")

    outputs = _output_paths(output_prefix)
    sentinel = outputs["mask"]

    logger.info(f"Input INV2     : {inv2}")
    logger.info(f"Input T1w      : {t1w}")
    logger.info(f"Input T1map    : {t1map}")
    logger.info(f"Output prefix  : {output_prefix}")

    if not check_output(sentinel, logger, force):
        return

    if force:
        for p in outputs.values():
            if p.exists():
                p.unlink()

    #  run nighres
    from nighres.brain import mp2rage_skullstripping

    logger.info("Running Nighres MP2RAGE skullstripping...")
    result = mp2rage_skullstripping(
        str(inv2),
        str(t1w),
        str(t1map),
        save_data=True,
        output_dir=str(output_prefix.parent),
        file_name=output_prefix.name,
    )

    # collect & rename outputs 
    found = _collect_nighres_outputs(output_prefix.parent, output_prefix.name)

    missing = [
        key for key in outputs if key not in found or not found[key].exists()
    ]
    if missing:
        raise RuntimeError(
            "Nighres skullstripping did not produce all expected outputs: "
            + ", ".join(missing)
        )

    for key, src in found.items():
        dst = outputs[key]
        if src.resolve() != dst.resolve():
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))

    logger.info(f"Wrote skull mask  : {outputs['mask'].name}")
    logger.info(f"Wrote masked INV2 : {outputs['inv2'].name}")
    logger.info(f"Wrote masked T1w  : {outputs['t1w'].name}")
    logger.info(f"Wrote masked T1map: {outputs['t1map'].name}")



# Helpers


def _stem_nii_gz(path: Path) -> str:
    """Strip .nii.gz / .nii to get a filename stem."""
    name = path.name
    if name.endswith(".nii.gz"):
        return name[:-7]
    if name.endswith(".nii"):
        return name[:-4]
    return path.stem


def _output_paths(prefix: Path) -> dict[str, Path]:
    """Expected output paths from the given prefix."""
    return {
        "mask": prefix.with_name(f"{prefix.name}_mask.nii.gz"),
        "inv2": prefix.with_name(f"{prefix.name}_inv2.nii.gz"),
        "t1w": prefix.with_name(f"{prefix.name}_t1w.nii.gz"),
        "t1map": prefix.with_name(f"{prefix.name}_t1map.nii.gz"),
    }


def _collect_nighres_outputs(root: Path, base: str) -> dict[str, Path]:
    """Find nighres outputs by glob patterns."""
    patterns = {
        "mask": [
            f"{base}*strip*mask*.nii.gz",
            f"{base}*brain*mask*.nii.gz",
        ],
        "inv2": [
            f"{base}*strip*inv2*.nii.gz",
            f"{base}*masked*inv2*.nii.gz",
        ],
        "t1w": [
            f"{base}*strip*t1w*.nii.gz",
            f"{base}*masked*t1w*.nii.gz",
        ],
        "t1map": [
            f"{base}*strip*t1map*.nii.gz",
            f"{base}*masked*t1map*.nii.gz",
        ],
    }

    found: dict[str, Path] = {}
    for key, pats in patterns.items():
        candidates: list[Path] = []
        for pat in pats:
            candidates.extend([p for p in root.glob(pat) if p.is_file()])
        if candidates:
            found[key] = sorted(set(candidates))[0]

    return found