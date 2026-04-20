from __future__ import annotations

from pathlib import Path
from typing import Optional
from textwrap import dedent
import shutil

import nibabel as nib
import numpy as np

from anatprep.core import (
    setup_logging,
    default_output,
    check_output,
    load_anatprep_config,
    config_get,
    run_command,
    resolve_studydir,
    get_docker_user_args,
)


def run_nighres_dura(
    inv2: Path,
    brain_mask: Path,
    output_image: Optional[Path] = None,
    threshold: Optional[float] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """
    Run Nighres MP2RAGE dura estimation in Docker and binarize the result.

    Parameters
    ----------
    inv2
        Second inversion magnitude image.
    brain_mask
        Brain mask for the INV2 image.
    output_image
        Final binary dura mask. If omitted, defaults to <inv2>_dura_mask.nii.gz.
    threshold
        Threshold applied to the dura probability map. If omitted, read from config
        (tools.nighres.dura_threshold) or default to 0.8.
    force
        Overwrite existing output.
    verbose
        Verbose logging.
    """
    inv2 = Path(inv2).resolve()
    brain_mask = Path(brain_mask).resolve()

    if output_image is None:
        output_image = default_output(inv2, "dura_mask")
    else:
        output_image = Path(output_image).resolve()

    output_image.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("nighres-dura", verbose=verbose)

    if not inv2.exists():
        raise FileNotFoundError(f"INV2 image not found: {inv2}")
    if not brain_mask.exists():
        raise FileNotFoundError(f"Brain mask not found: {brain_mask}")

    studydir = resolve_studydir()
    config = load_anatprep_config(studydir)

    docker_image = config_get(
        config, "tools.nighres.docker_image", "nighres/nighres:latest"
    )
    if threshold is None:
        threshold = float(config_get(config, "tools.nighres.dura_threshold", 0.8))

    proba_image = _paired_proba_path(output_image)

    logger.info(f"Input INV2     : {inv2}")
    logger.info(f"Input mask     : {brain_mask}")
    logger.info(f"Output mask    : {output_image}")
    logger.info(f"Output proba   : {proba_image}")
    logger.info(f"Threshold      : {threshold}")
    logger.info(f"Docker image   : {docker_image}")

    if not check_output(output_image, logger, force):
        return

    if force:
        for p in (output_image, proba_image):
            if p.exists():
                p.unlink()

    _run_docker_dura(
        inv2=inv2,
        brain_mask=brain_mask,
        output_dir=output_image.parent,
        file_name=_nighres_base_name(output_image),
        docker_image=docker_image,
        logger=logger,
    )

    prob_file = _find_nighres_probability_file(output_image.parent, _nighres_base_name(output_image))
    if prob_file is None or not prob_file.exists():
        raise RuntimeError("Nighres did not produce a dura probability file.")

    prob_img = nib.load(str(prob_file))
    prob_data = prob_img.get_fdata()

    dura_mask_data = (prob_data >= threshold).astype(np.uint8)
    dura_img = nib.Nifti1Image(dura_mask_data, prob_img.affine, prob_img.header.copy())
    dura_img.set_data_dtype(np.uint8)
    dura_img.to_filename(str(output_image))

    # Keep the probability image too, under a predictable name.
    if proba_image != prob_file:
        shutil.move(str(prob_file), str(proba_image))

    logger.info(f"Wrote dura mask: {output_image.name}")
    logger.info(f"Wrote proba map : {proba_image.name}")


def _run_docker_dura(
    inv2: Path,
    brain_mask: Path,
    output_dir: Path,
    file_name: str,
    docker_image: str,
    logger,
) -> None:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker not found in PATH.")

    host_to_container = {}
    volume_args = _build_docker_volumes(
        [
            (inv2.parent, False),
            (brain_mask.parent, False),
            (output_dir, True),
        ],
        host_to_container,
    )

    inv2_c = _container_path(inv2, host_to_container)
    mask_c = _container_path(brain_mask, host_to_container)
    out_c = host_to_container[output_dir.resolve()]

    script = dedent(
        f"""
        from nighres.brain import mp2rage_dura_estimation

        mp2rage_dura_estimation(
            r"{inv2_c}",
            r"{mask_c}",
            file_name=r"{file_name}",
            output_dir=r"{out_c}",
            save_data=True,
        )
        """
    ).strip()

    cmd = [
        "docker", "run", "--rm",
        *get_docker_user_args(),
        *volume_args,
        docker_image,
        "python", "-c", script,
    ]

    run_command(cmd, logger)


def _build_docker_volumes(
    mounts: list[tuple[Path, bool]],
    host_to_container: dict[Path, Path],
) -> list[str]:
    """
    Build docker --volume arguments.

    mounts: [(host_dir, writable), ...]
    host_to_container: populated with {host_dir: container_dir}
    """
    unique: dict[Path, bool] = {}
    for host_dir, writable in mounts:
        host_dir = host_dir.resolve()
        unique[host_dir] = unique.get(host_dir, False) or writable

    volume_args: list[str] = []
    for idx, (host_dir, writable) in enumerate(unique.items()):
        container_dir = Path("/mnt") / f"vol{idx}"
        host_to_container[host_dir] = container_dir
        mode = "rw" if writable else "ro"
        volume_args.extend(["--volume", f"{host_dir}:{container_dir}:{mode}"])

    return volume_args


def _container_path(path: Path, host_to_container: dict[Path, Path]) -> Path:
    host_dir = path.resolve().parent
    return host_to_container[host_dir] / path.name


def _nighres_base_name(path: Path) -> str:
    name = path.name
    if name.endswith(".nii.gz"):
        return name[:-7]
    if name.endswith(".nii"):
        return name[:-4]
    return path.stem


def _paired_proba_path(output_mask: Path) -> Path:
    """
    If output is ..._mask.nii.gz -> ..._proba.nii.gz
    Otherwise -> <stem>_proba.nii.gz
    """
    name = output_mask.name
    if name.endswith("_mask.nii.gz"):
        return output_mask.with_name(name.replace("_mask.nii.gz", "_proba.nii.gz"))
    if name.endswith("_mask.nii"):
        return output_mask.with_name(name.replace("_mask.nii", "_proba.nii"))
    stem = _nighres_base_name(output_mask)
    return output_mask.with_name(f"{stem}_proba.nii.gz")


def _find_nighres_probability_file(root: Path, base: str) -> Optional[Path]:
    patterns = [
        f"{base}*dura*proba*.nii.gz",
        f"{base}*dura*prob*.nii.gz",
        f"{base}*dura-proba*.nii.gz",
        f"{base}*dura_proba*.nii.gz",
        f"{base}*proba*.nii.gz",
        f"{base}*prob*.nii.gz",
    ]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend([p for p in root.glob(pattern) if p.is_file()])

    if not candidates:
        return None

    # Prefer exact-looking matches first, otherwise just take the first sorted.
    candidates = sorted(set(candidates))
    return candidates[0]