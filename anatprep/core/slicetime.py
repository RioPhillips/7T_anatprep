"""
Slice-timing correction by temporal resampling onto a uniform grid.

Used by `run-fmriprep --stc-resample` for studies where the BOLD data should
reach fMRIprep already slice-time corrected and sampled on a regular grid
whose TR differs from the acquisition TR (the "pseudo TR").

Model
-----
Slice z of volume v was acquired at

    t = v * TR + SliceTiming[z]                (seconds)

For every slice, one cubic B-spline (not-a-knot) is fitted through those
samples for all voxels at once and evaluated on a common grid

    t_k = skip_volumes * TR + k * new_tr,      for t_k < n_volumes * TR

so output volume k shows the whole brain at time t_k, counted from the start
of the first acquired volume.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import nibabel as nib
import numpy as np
from scipy.interpolate import make_interp_spline

# Key in the output sidecar that records what was done. It also marks a file
# as already resampled, so it is never resampled twice.
PROVENANCE_KEY = "AnatprepSTCResample"
# Bump when the numerical method changes, so cached outputs are regenerated.
METHOD = "cubic-bspline-per-slice-v1"

_SLICE_AXES = {"i": 0, "j": 1, "k": 2}


def sidecar_path(nii: Path) -> Path:
    # return the JSON sidecar next to a .nii / .nii.gz file
    nii = Path(nii)
    name = nii.name
    stem = name[:-7] if name.endswith(".nii.gz") else name[:-4] if name.endswith(".nii") else nii.stem
    return nii.with_name(stem + ".json")


def _read_sidecar(nii: Path) -> Dict[str, Any]:
    side = sidecar_path(nii)
    if not side.exists():
        raise FileNotFoundError(f"No JSON sidecar for {Path(nii).name} (expected {side.name}).")
    return json.loads(side.read_text())


def uniform_grid(n_volumes: int, tr: float, new_tr: float, skip_volumes: int) -> np.ndarray:
    """
    Output sample times (s): start at skip_volumes * TR, step new_tr, stop
    before n_volumes * TR (exclusive), as in the reference script's
    np.arange(blank_time_len, total_time, pseudo_TR).
    """
    if new_tr <= 0:
        raise ValueError(f"Target TR must be > 0, got {new_tr}")
    if skip_volumes < 0:
        raise ValueError(f"skip_volumes must be >= 0, got {skip_volumes}")
    t0 = skip_volumes * tr
    t_end = n_volumes * tr
    if t0 >= t_end:
        raise ValueError(
            f"skip_volumes={skip_volumes} leaves no data: first output time {t0:.3f}s "
            f">= run length {t_end:.3f}s."
        )
    # count computed explicitly: float np.arange can gain/lose a sample at the end
    n = int(np.ceil((t_end - t0) / new_tr - 1e-9))
    return t0 + new_tr * np.arange(n)


def resample_slices(
    data: np.ndarray,
    slice_times: np.ndarray,
    tr: float,
    new_times: np.ndarray,
    slice_axis: int = 2,
) -> np.ndarray:
    """
    Resample a 4D (x, y, z, t) array onto `new_times`, slice by slice.

    `slice_times[s]` is the within-TR acquisition time of slice s along
    `slice_axis`. Returns float32 with shape (x, y, z, len(new_times)).
    """
    if data.ndim != 4:
        raise ValueError(f"Expected 4D data, got shape {data.shape}")
    data_z = np.moveaxis(data, slice_axis, 2)          # put slices on axis 2 (a view)
    n_slices, n_vols = data_z.shape[2], data_z.shape[3]
    if len(slice_times) != n_slices:
        raise ValueError(f"{len(slice_times)} slice times for {n_slices} slices")

    vol_times = np.arange(n_vols) * tr
    out = np.empty(data_z.shape[:3] + (len(new_times),), dtype=np.float32)
    for z in range(n_slices):
        spline = make_interp_spline(vol_times + slice_times[z], data_z[:, :, z, :], k=3, axis=-1)
        out[:, :, z, :] = spline(new_times)
    return np.moveaxis(out, 2, slice_axis)


def stc_signature(src: Path, *, new_tr: float, skip_volumes: int) -> Dict[str, Any]:
    """
    Everything the output depends on. A cached output whose provenance matches
    this is reused; any difference (source file, its sidecar timing, or the
    parameters) means it gets regenerated.
    """
    src = Path(src)
    meta = _read_sidecar(src)
    if PROVENANCE_KEY in meta:
        raise ValueError(
            f"{src.name} is already slice-time resampled ({PROVENANCE_KEY} in its sidecar); "
            f"refusing to resample it again."
        )
    st = src.stat()  # follows symlinks: identical for a symlinked or copy2'd source
    return {
        "Method": METHOD,
        "Source": src.name,
        "SourceSize": st.st_size,
        "SourceMTime": int(st.st_mtime),
        "SourceRepetitionTime": meta.get("RepetitionTime"),
        "SourceSliceTiming": meta.get("SliceTiming"),
        "SourceSliceEncodingDirection": meta.get("SliceEncodingDirection"),
        "TargetRepetitionTime": float(new_tr),
        "SkipVolumes": int(skip_volumes),
    }


def stc_is_current(dst: Path, signature: Dict[str, Any]) -> bool:
    """True if `dst` and its sidecar exist and were made with `signature`."""
    dst = Path(dst)
    side = sidecar_path(dst)
    if not (dst.exists() and side.exists()):
        return False
    try:
        prov = json.loads(side.read_text()).get(PROVENANCE_KEY, {})
    except (OSError, ValueError):
        return False
    return all(prov.get(k) == v for k, v in signature.items())


def stc_resample_bold(
    src: Path,
    dst: Path,
    *,
    new_tr: float,
    skip_volumes: int,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """
    Slice-time correct and resample one BOLD run (`src` + sidecar) to `dst` +
    sidecar. Both files are written atomically (temp file, then rename), so an
    interrupted run never leaves a half-written output that looks complete.

    Returns the provenance dict written to the output sidecar.
    """
    log = logger or logging.getLogger(__name__)
    src, dst = Path(src), Path(dst)
    signature = stc_signature(src, new_tr=new_tr, skip_volumes=skip_volumes)
    meta = _read_sidecar(src)

    if "RepetitionTime" not in meta:
        raise ValueError(f"{src.name}: sidecar has no RepetitionTime.")
    tr = float(meta["RepetitionTime"])
    if not meta.get("SliceTiming"):
        raise ValueError(
            f"{src.name}: sidecar has no SliceTiming. Populate it first "
            f"(`bids7t slicetime`), so the slice-order model is defined in one place."
        )
    slice_times = np.asarray(meta["SliceTiming"], dtype=float)

    sed = str(meta.get("SliceEncodingDirection", "k"))
    if sed[0] not in _SLICE_AXES:
        raise ValueError(f"{src.name}: unsupported SliceEncodingDirection {sed!r}")
    slice_axis = _SLICE_AXES[sed[0]]
    if sed.endswith("-"):
        # BIDS: for a negative direction, SliceTiming lists slices in reverse order
        slice_times = slice_times[::-1]

    img = nib.load(str(src))
    if img.ndim != 4:
        raise ValueError(f"{src.name}: expected a 4D image, got shape {img.shape}")
    n_vols = img.shape[3]
    if len(slice_times) != img.shape[slice_axis]:
        raise ValueError(
            f"{src.name}: {len(slice_times)} SliceTiming entries but "
            f"{img.shape[slice_axis]} slices along axis {slice_axis}."
        )
    if slice_times.min() < 0 or slice_times.max() >= tr:
        log.warning(
            f"{src.name}: SliceTiming outside [0, TR) "
            f"(min {slice_times.min():.3f}s, max {slice_times.max():.3f}s, TR {tr}s)."
        )
    hdr_tr = float(img.header.get_zooms()[3])
    if img.header.get_xyzt_units()[1] == "msec":
        hdr_tr /= 1000.0
    if abs(hdr_tr - tr) > 1e-3:
        log.warning(
            f"{src.name}: header TR {hdr_tr}s differs from sidecar RepetitionTime {tr}s; "
            f"using the sidecar."
        )

    new_times = uniform_grid(n_vols, tr, new_tr, skip_volumes)
    # Output samples outside some slice's sampled range are extrapolated:
    # before the first sample of the latest-acquired slice (skip_volumes = 0),
    # and after the last sample of the earliest-acquired slice (the reference
    # grid runs up to n_volumes * TR).
    n_extrap_start = int(np.sum(new_times < slice_times.max() - 1e-9))
    n_extrap_end = int(np.sum(new_times > (n_vols - 1) * tr + slice_times.min() + 1e-9))

    data = img.get_fdata(dtype=np.float32)
    out = resample_slices(data, slice_times, tr, new_times, slice_axis=slice_axis)
    del data

    # keep the source's on-disk dtype, as the reference script did; nibabel
    # recomputes scl_slope/inter for it on save
    hdr = img.header.copy()
    hdr.set_slope_inter(None, None)
    new_img = nib.Nifti1Image(out, img.affine, hdr)
    new_img.header.set_zooms(img.header.get_zooms()[:3] + (float(new_tr),))
    xyz_unit = img.header.get_xyzt_units()[0]
    new_img.header.set_xyzt_units(xyz=xyz_unit, t="sec")

    provenance = dict(signature)
    provenance.update({
        "FirstVolumeTime": float(new_times[0]),
        "SourceVolumes": int(n_vols),
        "Volumes": int(len(new_times)),
        "ExtrapolatedVolumesStart": n_extrap_start,
        "ExtrapolatedVolumesEnd": n_extrap_end,
        "Description": (
            "Slice-time corrected and resampled by anatprep run-fmriprep --stc-resample: "
            "cubic B-spline through each slice's samples, evaluated at "
            "t = FirstVolumeTime + k * RepetitionTime seconds after the start of the "
            "first acquired volume."
        ),
    })
    out_meta = dict(meta)
    out_meta.pop("SliceTiming", None)
    out_meta["RepetitionTime"] = float(new_tr)
    out_meta[PROVENANCE_KEY] = provenance

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_nii = dst.with_name(".partial_" + dst.name)
    nib.save(new_img, str(tmp_nii))
    os.replace(tmp_nii, dst)
    dst_json = sidecar_path(dst)
    tmp_json = dst_json.with_name(".partial_" + dst_json.name)
    tmp_json.write_text(json.dumps(out_meta, indent=2) + "\n")
    os.replace(tmp_json, dst_json)  # written last: its presence marks the output complete
    return provenance
