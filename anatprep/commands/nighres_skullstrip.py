from __future__ import annotations

from pathlib import Path
from typing import Optional
from textwrap import dedent
import shutil

from anatprep.core import (
    setup_command_logging,
    default_output,
    check_output,
    load_anatprep_config,
    config_get,
    run_command,
    resolve_studydir,
    get_docker_user_args,
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
    Run Nighres MP2RAGE skullstripping in Docker.

    Parameters
    ----------
    inv2
        Second inversion magnitude image.
    t1w
        T1-weighted image.
    t1map
        T1 map image.
    output_prefix
        Base prefix for outputs. If omitted, defaults to <inv2>_strip.
        Outputs will be:
          <prefix>_mask.nii.gz
          <prefix>_inv2.nii.gz
          <prefix>_t1w.nii.gz
          <prefix>_t1map.nii.gz
    force
        Overwrite existing outputs.
    verbose
        Verbose logging.
    """
    inv2 = Path(inv2).resolve()
    t1w = Path(t1w).resolve()
    t1map = Path(t1map).resolve()

    if output_prefix is None:
        output_prefix = inv2.parent / f"{_stem_nii_gz(inv2)}_strip"
    else:
        output_prefix = Path(output_prefix).resolve()

    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    logger, log_dir = setup_command_logging("nighres-skullstrip", inv2, verbose=verbose)

    if not inv2.exists():
        raise FileNotFoundError(f"INV2 image not found: {inv2}")
    if not t1w.exists():
        raise FileNotFoundError(f"T1w image not found: {t1w}")
    if not t1map.exists():
        raise FileNotFoundError(f"T1map image not found: {t1map}")

    studydir = resolve_studydir()
    config = load_anatprep_config(studydir)

    docker_image = config_get(
        config, "tools.nighres.docker_image", "nighres/nighres:latest"
    )

    outputs = _output_paths(output_prefix)
    sentinel = outputs["mask"]

    logger.info(f"Input INV2     : {inv2}")
    logger.info(f"Input T1w      : {t1w}")
    logger.info(f"Input T1map    : {t1map}")
    logger.info(f"Output prefix  : {output_prefix}")
    logger.info(f"Docker image   : {docker_image}")

    if not check_output(sentinel, logger, force):
        return

    if force:
        for p in outputs.values():
            if p.exists():
                p.unlink()

    _run_docker_skullstrip(
        inv2=inv2,
        t1w=t1w,
        t1map=t1map,
        output_dir=output_prefix.parent,
        file_name=output_prefix.name,
        docker_image=docker_image,
        logger=logger,
    )

    found = _collect_nighres_outputs(output_prefix.parent, output_prefix.name)

    missing = [key for key in outputs if key not in found or not found[key].exists()]
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

    logger.info(f"Wrote skull mask : {outputs['mask'].name}")
    logger.info(f"Wrote masked INV2: {outputs['inv2'].name}")
    logger.info(f"Wrote masked T1w : {outputs['t1w'].name}")
    logger.info(f"Wrote masked T1map: {outputs['t1map'].name}")


def _run_docker_skullstrip(
    inv2: Path,
    t1w: Path,
    t1map: Path,
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
            (t1w.parent, False),
            (t1map.parent, False),
            (output_dir, True),
        ],
        host_to_container,
    )

    inv2_c = _container_path(inv2, host_to_container)
    t1w_c = _container_path(t1w, host_to_container)
    t1map_c = _container_path(t1map, host_to_container)
    out_c = host_to_container[output_dir.resolve()]

    script = dedent(
        f"""
        from nighres.brain import mp2rage_skullstripping

        mp2rage_skullstripping(
            r"{inv2_c}",
            r"{t1w_c}",
            r"{t1map_c}",
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


def _stem_nii_gz(path: Path) -> str:
    name = path.name
    if name.endswith(".nii.gz"):
        return name[:-7]
    if name.endswith(".nii"):
        return name[:-4]
    return path.stem


def _output_paths(prefix: Path) -> dict[str, Path]:
    base = prefix
    return {
        "mask": base.with_name(f"{base.name}_mask.nii.gz"),
        "inv2": base.with_name(f"{base.name}_inv2.nii.gz"),
        "t1w": base.with_name(f"{base.name}_t1w.nii.gz"),
        "t1map": base.with_name(f"{base.name}_t1map.nii.gz"),
    }


def _collect_nighres_outputs(root: Path, base: str) -> dict[str, Path]:
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