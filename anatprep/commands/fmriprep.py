"""
run-fmriprep command: wrap fMRIprep as the terminal step of the pipeline.

We assemble a small BIDS input tree containing the *cleaned*
anatomical (desc-denoised by default) plus the subject's func/fmap mirrored
from rawdata, and run fMRIprep on that. FreeSurfer recon-all is reused from
derivatives/freesurfer via --fs-subjects-dir (it is NOT copied into the tree).

Ingredients
-----------
  anat : the single cleaned T1w (desc-denoised; or desc-masked + skull-strip
         skip). Renamed to a raw-style BIDS name so pybids treats it as the T1w.
  func : mirrored from rawdata/sub-X[/ses-Y]/func   (niftis symlinked, sidecars copied)
  fmap : mirrored from rawdata/sub-X[/ses-Y]/fmap
  fs   : referenced via --fs-subjects-dir (run-freesurfer output), not copied

The assembled tree lives at <output_dir>/sourcedata/bids and is rebuilt per run.

Usage:
  run-fmriprep SUBJECT [--anat FILE | --anat-desc denoised|masked]
               [--session SES] [--anat-only] [--task TASK]
               [--bids-filter-file FILE.json] [--skull-strip-t1w skip|auto|force]
               [--bids-dir DIR]            # use a prebuilt tree, skip assembly
               [--output-dir DIR] [--subjects-dir DIR] [--workdir DIR]
               [--input-tree DIR]
               [--cpus N] [--omp-nthreads N] [--mem-mb M]
               [--output-spaces "fsnative ..."] [--kwargs-file FILE]
               [--notrack/--track] [--local] [--clean-workdir] [--force] [--verbose]

By default fMRIprep runs via `docker run` using the image in
tools.fmriprep.docker_image (with --shm-size from tools.fmriprep.shm_size).
Pass --local to use a bare-metal `fmriprep` binary.
"""

import json
import os
import shutil
from pathlib import Path
from typing import List, Optional

from anatprep.core import (
    setup_command_logging,
    load_anatprep_config,
    config_get,
    resolve_studydir,
    resolve_subjects_dir,
    run_command,
    extract_bids_entities,
    bids_prefix,
    input_stem,
)

_ANAT_DESCS = ("denoised", "masked")
_SKULL_STRIP = ("skip", "auto", "force")


# ---------------------------------------------------------------------------
# Public entry point (one participant per call; CLI loops a comma-list)
# ---------------------------------------------------------------------------

def run_fmriprep(
    subject: str,
    anat: Optional[Path] = None,
    anat_desc: str = "denoised",
    session: Optional[str] = None,
    bids_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    subjects_dir: Optional[Path] = None,
    workdir: Optional[Path] = None,
    input_tree: Optional[Path] = None,
    anat_only: bool = False,
    task: Optional[str] = None,
    bids_filter_file: Optional[Path] = None,
    skull_strip_t1w: Optional[str] = None,
    output_spaces: Optional[str] = None,
    cpus: Optional[int] = None,
    omp_nthreads: Optional[int] = None,
    mem_mb: Optional[int] = None,
    kwargs_file: Optional[Path] = None,
    local: bool = False,
    notrack: bool = True,
    stop_on_first_crash: bool = True,
    clean_workdir: bool = False,
    force: bool = False,
    verbose: bool = False,
) -> None:
    label = subject[4:] if subject.startswith("sub-") else subject
    if anat_desc not in _ANAT_DESCS:
        raise ValueError(f"--anat-desc must be one of {_ANAT_DESCS}, got {anat_desc!r}")
    if skull_strip_t1w is not None and skull_strip_t1w not in _SKULL_STRIP:
        raise ValueError(f"--skull-strip-t1w must be one of {_SKULL_STRIP}")

    logger, _ = setup_command_logging(
        "fmriprep", Path(f"sub-{label}_desc-fmriprep.nii.gz"), verbose=verbose
    )
    logger.info(f"Participant : sub-{label}" + (f"  ses-{session}" if session else ""))
    logger.info(f"Mode        : {'--anat-only' if anat_only else 'anat + func'}")

    studydir = resolve_studydir()
    config = load_anatprep_config(studydir)

    # --- paths -------------------------------------------------------------
    output_dir = (
        Path(output_dir).resolve() if output_dir
        else (studydir / "derivatives" / "fmriprep").resolve()
    )
    subjects_dir = resolve_subjects_dir(subjects_dir, config, studydir)
    workdir = _resolve_workdir(workdir, config, studydir)
    input_tree = (
        Path(input_tree).resolve() if input_tree
        else (output_dir / "sourcedata" / "bids").resolve()
    )

    if not subjects_dir.exists():
        raise RuntimeError(
            f"FreeSurfer SUBJECTS_DIR not found: {subjects_dir}\n"
            f"Run `run-freesurfer` first so fMRIprep can reuse the recon-all."
        )
    if not (subjects_dir / f"sub-{label}").exists():
        logger.warning(
            f"No FreeSurfer subject 'sub-{label}' under {subjects_dir}; fMRIprep "
            f"would run recon-all itself. (Session-based recon-all is named "
            f"'sub-X_ses-Y' by run-freesurfer and won't be auto-found here.)"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Study dir   : {studydir}")
    logger.info(f"Output dir  : {output_dir}")
    logger.info(f"SUBJECTS_DIR: {subjects_dir}")
    logger.info(f"Work dir    : {workdir}")

    # --- FreeSurfer license (shared with run-freesurfer config) ------------
    license_path = config_get(config, "tools.freesurfer.license")
    if not license_path or not Path(license_path).exists():
        raise RuntimeError(
            "FreeSurfer license required by fMRIprep but not found.\n"
            "Set tools.freesurfer.license in code/anatprep.yml."
        )
    license_path = Path(license_path).resolve()

    # --- resources ---------------------------------------------------------
    if cpus is None:
        cpus = int(config_get(config, "tools.fmriprep.nthreads", default=8))
    cpus = max(1, cpus)
    if omp_nthreads is None:
        omp_nthreads = int(config_get(config, "tools.fmriprep.omp_nthreads",
                                      default=min(cpus, 8)))
    # Independent of cpus: -j caps how many processes run at once, --omp-nthreads
    # sets threads *per* process. fMRIprep handles the relationship itself, so we
    # don't clamp omp to cpus (that was collapsing `-j 1 --omp-nthreads 4` to 1).
    omp_nthreads = max(1, omp_nthreads)
    if mem_mb is None:
        mem_mb = int(config_get(config, "tools.fmriprep.mem_mb", default=32000))
    if output_spaces is None:
        output_spaces = str(config_get(config, "tools.fmriprep.output_spaces",
                                       default="fsnative"))
    logger.info(f"Resources   : nthreads={cpus} omp={omp_nthreads} mem_mb={mem_mb}")
    logger.info(f"Output space: {output_spaces}")

    # --- skip / clean ------------------------------------------------------
    report = output_dir / f"sub-{label}.html"
    subj_out = output_dir / f"sub-{label}"
    if (report.exists() or subj_out.exists()) and not force:
        logger.info(
            f"fMRIprep output already present for sub-{label}. Use --force to "
            f"re-run (fMRIprep otherwise resumes from the work dir)."
        )
        return
    if clean_workdir:
        _clean_subject_workdir(workdir, label, logger)

    # --- assemble (or reuse) the BIDS input tree ---------------------------
    if bids_dir is not None:
        bids_root = Path(bids_dir).resolve()
        if not bids_root.exists():
            raise FileNotFoundError(f"--bids-dir not found: {bids_root}")
        logger.info(f"Using prebuilt BIDS input (assembly skipped): {bids_root}")
    else:
        anat_path = _resolve_anat(anat, anat_desc, studydir, label, session, logger)
        # a skull-stripped anat must skip fMRIprep's own brain extraction
        if anat_desc == "masked" and skull_strip_t1w is None:
            skull_strip_t1w = "skip"
            logger.info("masked anat is skull-stripped; defaulting "
                        "--skull-strip-t1w skip (override with --skull-strip-t1w).")
        link_mode = "symlink" if local else "copy"
        bids_root = _assemble_bids_input(
            input_tree=input_tree, studydir=studydir, label=label, session=session,
            anat_path=anat_path, anat_only=anat_only, link_mode=link_mode,
            logger=logger,
        )

    if skull_strip_t1w:
        logger.info(f"--skull-strip-t1w {skull_strip_t1w}")

    extra = _read_kwargs_file(kwargs_file, logger)

    # --- build & run -------------------------------------------------------
    common = dict(
        label=label, output_spaces=output_spaces, cpus=cpus,
        omp_nthreads=omp_nthreads, mem_mb=mem_mb, anat_only=anat_only, task=task,
        skull_strip_t1w=skull_strip_t1w, stop_on_first_crash=stop_on_first_crash,
        notrack=notrack, extra=extra,
    )
    if local:
        if shutil.which("fmriprep") is None:
            raise RuntimeError(
                "'fmriprep' not found on PATH. Drop --local to use the container, "
                "or fix the bare-metal install."
            )
        cmd = ["fmriprep"] + _build_bidsapp_args(
            bids_root=str(bids_root), output_dir=str(output_dir),
            subjects_dir=str(subjects_dir), workdir=str(workdir),
            license_path=str(license_path), bids_filter_file=bids_filter_file,
            **common,
        )
    else:
        if shutil.which("docker") is None:
            raise RuntimeError(
                "'docker' not found on PATH. Install Docker, or pass --local."
            )
        image = config_get(config, "tools.fmriprep.docker_image",
                           default="nipreps/fmriprep:latest")
        # fmriprep-docker can't set --shm-size, and Docker's 64MB default starves
        # the MultiProc worker pool (BrokenProcessPool at startup), so we run
        # `docker run` directly with an adequate /dev/shm.
        shm_size = str(config_get(config, "tools.fmriprep.shm_size", default="8g"))
        logger.info(f"Container /dev/shm: --shm-size={shm_size}")
        cmd = _build_docker_run_cmd(
            image=image, shm_size=shm_size, bids_root=bids_root,
            output_dir=output_dir, subjects_dir=subjects_dir, workdir=workdir,
            license_path=license_path, bids_filter_file=bids_filter_file,
            **common,
        )

    logger.info("Command: " + " ".join(cmd))
    run_command(cmd, logger)
    logger.info(f"fMRIprep complete for sub-{label}")


# ---------------------------------------------------------------------------
# BIDS input-tree assembly
# ---------------------------------------------------------------------------

def _resolve_anat(anat, anat_desc, studydir, label, session, logger) -> Path:
    """Explicit --anat wins; otherwise glob the chosen desc under anatprep."""
    if anat is not None:
        p = Path(anat).resolve()
        if not p.exists():
            raise FileNotFoundError(f"--anat not found: {p}")
        logger.info(f"Anatomical input: {p}")
        return p

    base = studydir / "derivatives" / "anatprep" / f"sub-{label}"
    if session:
        base = base / f"ses-{session}"
    pattern = f"sub-{label}*_desc-{anat_desc}_T1w.nii.gz"
    cands = sorted(base.glob(pattern))
    if not cands:
        raise FileNotFoundError(
            f"No '{pattern}' under {base}. Pass --anat explicitly."
        )
    if len(cands) > 1:
        raise RuntimeError(
            f"Ambiguous anat: {[c.name for c in cands]} under {base}. Pass --anat."
        )
    logger.info(f"Anatomical input (auto, desc-{anat_desc}): {cands[0]}")
    return cands[0]


def _assemble_bids_input(
    *, input_tree, studydir, label, session, anat_path, anat_only, link_mode, logger
) -> Path:
    raw_base = studydir / "rawdata" / f"sub-{label}"
    if session:
        raw_base = raw_base / f"ses-{session}"
    if not raw_base.exists():
        raise FileNotFoundError(f"rawdata subject tree not found: {raw_base}")

    dst_sub = input_tree / f"sub-{label}"
    dst_base = dst_sub / f"ses-{session}" if session else dst_sub

    # rebuild this subject's subtree from scratch (cheap with symlinks)
    if dst_sub.exists():
        shutil.rmtree(dst_sub)
    (dst_base / "anat").mkdir(parents=True, exist_ok=True)

    # anat: ONLY the cleaned T1w (raw-style name), plus a sidecar
    t1w_name = _normalize_t1w_name(anat_path)
    _place(anat_path, dst_base / "anat" / t1w_name, link_mode)
    _place_t1w_sidecar(anat_path, raw_base, dst_base / "anat" / t1w_name, logger)
    rel = Path(f"sub-{label}") / (f"ses-{session}" if session else "") / "anat" / t1w_name
    logger.info(f"anat -> {rel}")

    # func + fmap mirrored from rawdata (only when including functional data)
    if not anat_only:
        for kind in ("func", "fmap"):
            src = raw_base / kind
            if src.exists():
                _mirror_dir(src, dst_base / kind, link_mode)
                logger.info(f"{kind} -> mirrored from {src}")
            elif kind == "func":
                logger.warning(f"No func/ under {raw_base}; nothing to inject.")

    _write_dataset_description(input_tree)
    return input_tree


def _normalize_t1w_name(anat_path: Path) -> str:
    """Drop the derivative desc- entity, keep sub/ses/acq/run, suffix T1w."""
    ents = extract_bids_entities(anat_path)
    ents.pop("desc", None)
    prefix = bids_prefix(ents, fallback=input_stem(anat_path))
    return f"{prefix}_T1w.nii.gz"


def _place(src: Path, dst: Path, link_mode: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if link_mode == "symlink":
        os.symlink(os.path.realpath(src), dst)
    else:
        shutil.copy2(src, dst)


def _place_t1w_sidecar(anat_path: Path, raw_base: Path, dst_t1w: Path, logger) -> None:
    dst_json = Path(str(dst_t1w).replace(".nii.gz", ".json"))
    side = Path(str(anat_path).replace(".nii.gz", ".json"))
    if side.exists():
        shutil.copy2(side, dst_json)
        return
    raw_anat = raw_base / "anat"
    cands = sorted(raw_anat.glob("*T1w.json")) if raw_anat.exists() else []
    if cands:
        shutil.copy2(cands[0], dst_json)
        logger.info(f"T1w sidecar from rawdata: {cands[0].name}")
        return
    dst_json.write_text("{}\n")
    logger.info("No T1w sidecar found; wrote minimal '{}'.")


def _mirror_dir(src: Path, dst: Path, link_mode: str) -> None:
    """Replicate a directory; sidecars copied, heavy images linked/copied."""
    dst.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.iterdir()):
        if f.is_dir():
            _mirror_dir(f, dst / f.name, link_mode)
            continue
        if f.suffix in (".json", ".tsv", ".bval", ".bvec"):
            shutil.copy2(f, dst / f.name)
        else:
            _place(f, dst / f.name, link_mode)


def _write_dataset_description(input_tree: Path) -> None:
    dd = input_tree / "dataset_description.json"
    if not dd.exists():
        dd.write_text(json.dumps(
            {"Name": "anatprep fMRIprep input", "BIDSVersion": "1.8.0",
             "DatasetType": "raw"}, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------

def _build_docker_run_cmd(
    *, image, shm_size, label, bids_root, output_dir, subjects_dir, workdir,
    license_path, output_spaces, cpus, omp_nthreads, mem_mb, anat_only, task,
    bids_filter_file, skull_strip_t1w, stop_on_first_crash, extra,
) -> List[str]:
    """Raw `docker run` so we can set --shm-size (fmriprep-docker can't) and
    mount the TemplateFlow cache. Host paths are bound to fixed container mount
    points, and the BIDS-App args use those container paths.
    """
    c_bids, c_out, c_work, c_fs = "/data", "/out", "/work", "/opt/subjects"
    c_lic = "/opt/freesurfer/license.txt"
    c_tf = "/templateflow"
    tf_home = Path.home() / ".cache" / "templateflow"
    tf_home.mkdir(parents=True, exist_ok=True)

    binds = [
        "-v", f"{bids_root}:{c_bids}:ro",
        "-v", f"{output_dir}:{c_out}",
        "-v", f"{workdir}:{c_work}",
        "-v", f"{subjects_dir}:{c_fs}",
        "-v", f"{license_path}:{c_lic}:ro",
        "-v", f"{tf_home}:{c_tf}",
    ]
    c_filter = None
    if bids_filter_file is not None:
        bff = Path(bids_filter_file).resolve()
        c_filter = f"/filters/{bff.name}"
        binds += ["-v", f"{bff}:{c_filter}:ro"]

    docker = [
        "docker", "run", "--rm",
        f"--shm-size={shm_size}",
        "-u", f"{os.getuid()}:{os.getgid()}",   # own outputs as us, not root
        "-e", f"TEMPLATEFLOW_HOME={c_tf}",
        "-e", "HOME=/tmp",                       # writable HOME for the non-root uid
        *binds,
        image,
    ]
    return docker + _build_bidsapp_args(
        label=label, bids_root=c_bids, output_dir=c_out, subjects_dir=c_fs,
        workdir=c_work, license_path=c_lic, output_spaces=output_spaces,
        cpus=cpus, omp_nthreads=omp_nthreads, mem_mb=mem_mb, anat_only=anat_only,
        task=task, bids_filter_file=c_filter, skull_strip_t1w=skull_strip_t1w,
        stop_on_first_crash=stop_on_first_crash, extra=extra,
    )


def _build_bidsapp_args(
    *, label, bids_root, output_dir, subjects_dir, workdir, license_path,
    output_spaces, cpus, omp_nthreads, mem_mb, anat_only, task, bids_filter_file,
    skull_strip_t1w, stop_on_first_crash, notrack, extra,
) -> List[str]:
    """The BIDS-App argument list, shared by the bare-metal `fmriprep` binary
    (host paths) and the `docker run` path (container paths)."""
    args = [
        str(bids_root), str(output_dir), "participant",
        "--participant-label", label,
        "--fs-subjects-dir", str(subjects_dir),
        "--fs-license-file", str(license_path),
        "--skip-bids-validation",
        "--md-only-boilerplate",
        "--output-spaces", *output_spaces.split(),
        "--nthreads", str(cpus),
        "--omp-nthreads", str(omp_nthreads),
        "--mem-mb", str(mem_mb),
        "-w", str(workdir),
    ]
    args += _common_flags(anat_only, task, bids_filter_file, skull_strip_t1w,
                          stop_on_first_crash, notrack)
    args += extra
    return args


def _common_flags(anat_only, task, bids_filter_file, skull_strip_t1w,
                  stop_on_first_crash, notrack) -> List[str]:
    flags: List[str] = []
    if anat_only:
        flags.append("--anat-only")
    if task:
        flags += ["--task-id", task]
    if bids_filter_file is not None:
        flags += ["--bids-filter-file", str(bids_filter_file)]
    if skull_strip_t1w:
        flags += ["--skull-strip-t1w", skull_strip_t1w]
    if stop_on_first_crash:
        flags.append("--stop-on-first-crash")
    if notrack:
        # Disable sentry telemetry: its background network threads can segfault
        # the main process during GC on Python 3.12 (cpython#111049-class crash).
        flags.append("--notrack")
    return flags


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_workdir(cli_value, config, studydir) -> Path:
    if cli_value is not None:
        return Path(cli_value).resolve()
    cfg = config_get(config, "tools.fmriprep.workdir")
    if cfg is not None:
        c = Path(cfg)
        if not c.is_absolute():
            c = studydir / c
        return c.resolve()
    # Default OUTSIDE the output tree: fMRIprep's work dir must not live inside
    # the dir bind-mounted as /out (nested mounts misbehave), and heavy work
    # dirs are a poor fit for some networked study filesystems. Namespaced by
    # study so multiple studies don't collide. Override via tools.fmriprep.workdir.
    return (Path.home() / ".cache" / "anatprep" / studydir.name / "fmriprep_work").resolve()


def _read_kwargs_file(kwargs_file, logger) -> List[str]:
    """Whitespace-split extra fMRIprep args from a file ('#' comments ignored)."""
    if kwargs_file is None:
        return []
    p = Path(kwargs_file)
    if not p.exists():
        raise FileNotFoundError(f"kwargs file not found: {p}")
    tokens: List[str] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens += line.split()
    if tokens:
        logger.info(f"Extra fMRIprep args from {p.name}: {' '.join(tokens)}")
    return tokens


def _clean_subject_workdir(workdir: Path, label: str, logger) -> None:
    """Remove this participant's fMRIprep workflow folder(s) so the next run
    re-imports updated FreeSurfer surfaces. Leaves other participants intact.
    Matches both the pre-24.x (`single_subject_<label>_wf`) and current
    (`sub_<label>_wf`) naming.
    """
    patterns = (f"single_subject_{label}_wf", f"sub_{label}_wf")
    targets = [t for p in patterns for t in workdir.rglob(p) if t.is_dir()]
    if not targets:
        logger.info(f"--clean-workdir: no subject workflow folder for {label} under {workdir}")
        return
    for t in targets:
        logger.info(f"--clean-workdir: removing {t}")
        shutil.rmtree(t, ignore_errors=True)