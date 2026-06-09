"""
    Wrap FreeSurfer's recon-all for anatomical segmentation.


    Two modes:
      Initial run (no --edit):
        Full `recon-all -all` on the given T1w. Optionally use --flair
        for pial refinement (passed as -FLAIR / -FLAIRpial). Sub-mm
        (-hires) is on by default; pass --no-highres to disable.
      Rerun mode (--edit pial|wm):
        Re-run recon-all on an existing FS subject after manual edits
        in freeview (via `brainmask-edit`):
          --edit pial : brainmask.mgz edited      -> -autorecon-pial -autorecon3
          --edit wm   : wm.mgz (and possibly bm)  -> -autorecon2-wm -autorecon3
        The FS subject directory is copied to
        <subjects-dir>/.backups/<subject-id>_<timestamp>/ before
        recon-all is invoked, in case the rerun goes sideways.


    FLAIR reuse on reruns:
      The initial run conforms the FLAIR into mri/FLAIR.mgz. On a rerun we
      re-add -FLAIRpial when that file is present so the regenerated pial
      keeps using the FLAIR (matches the reference pipeline).


    Parallelism:
      --cpus N    threads for -openmp N (within-binary OpenMP threads).
                  Diminishing returns past ~8 per FreeSurfer's guidance.
      --parallel  appends -parallel so lh/rh stages run concurrently.
                  Combines with --cpus, so peak load ~= 2 * N threads.


    Subject ID is derived from BIDS entities in the T1w filename:
      sub-S01_ses-MR1_..._T1w.nii.gz  -> "sub-S01_ses-MR1"
      sub-S01_..._T1w.nii.gz          -> "sub-S01"
    Override with --subject-id


    Usage:
      run-freesurfer T1W [--flair FILE] [--subjects-dir DIR] \\
                         [--edit pial|wm] [--cpus N] [--parallel] \\
                         [--no-highres] [--no-fix-ga] [--force] [--verbose]
    """

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from anatprep.core import (
    setup_command_logging,
    load_anatprep_config,
    config_get,
    resolve_studydir,
    extract_bids_entities,
    run_command,
)


_VALID_EDIT_STAGES = ("pial", "wm")


def run_freesurfer(
    t1w: Path,
    flair: Optional[Path] = None,
    subjects_dir: Optional[Path] = None,
    subject_id: Optional[str] = None,
    edit: Optional[str] = None,
    cpus: Optional[int] = None,
    parallel: bool = False,
    highres: bool = True,
    no_fix_ga: bool = False,
    force: bool = False,
    verbose: bool = False,
) -> None:
    t1w = Path(t1w).resolve()
    if flair is not None:
        flair = Path(flair).resolve()

    if edit is not None and edit not in _VALID_EDIT_STAGES:
        raise ValueError(
            f"--edit must be one of {_VALID_EDIT_STAGES}, got {edit!r}"
        )

    logger, _ = setup_command_logging("freesurfer", t1w, verbose=verbose)
    logger.info(f"T1w     : {t1w}")
    if flair is not None:
        logger.info(f"FLAIR   : {flair}")
    logger.info(f"Mode    : {'rerun --edit ' + edit if edit else 'initial recon-all'}")

    # resolve config-driven defaults
    studydir = resolve_studydir()
    config = load_anatprep_config(studydir)

    subjects_dir = _resolve_subjects_dir(subjects_dir, config, studydir)
    subjects_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"SUBJECTS_DIR: {subjects_dir}")

    if subject_id is None:
        subject_id = _derive_subject_id(t1w)
    logger.info(f"Subject ID  : {subject_id}")

    if cpus is None:
        cpus = int(config_get(config, "tools.freesurfer.cpus", default=1))
    cpus = max(1, cpus)
    logger.info(f"CPUs        : {cpus} (-openmp)")
    if parallel:
        logger.info(
            f"Parallel    : -parallel "
            f"(peak load ~{cpus * 2} threads at hemisphere stages)"
        )
    logger.info(f"Highres     : {'-hires' if highres else 'off (--no-highres)'}")

    _warn_missing_license(config, logger)

    if shutil.which("recon-all") is None:
        raise RuntimeError("'recon-all' not found in PATH. Is FreeSurfer sourced?")

    subj_dir = subjects_dir / subject_id
    _refuse_if_running(subj_dir, logger)

    env = os.environ.copy()
    env["SUBJECTS_DIR"] = str(subjects_dir)

    if edit is None:
        _run_initial(
            t1w=t1w,
            flair=flair,
            subj_dir=subj_dir,
            subjects_dir=subjects_dir,
            subject_id=subject_id,
            cpus=cpus,
            parallel=parallel,
            highres=highres,
            no_fix_ga=no_fix_ga,
            force=force,
            env=env,
            logger=logger,
        )
    else:
        _run_rerun(
            subj_dir=subj_dir,
            subjects_dir=subjects_dir,
            subject_id=subject_id,
            edit=edit,
            cpus=cpus,
            parallel=parallel,
            highres=highres,
            no_fix_ga=no_fix_ga,
            env=env,
            logger=logger,
        )


# ---------------------------------------------------------------------------
# Initial mode
# ---------------------------------------------------------------------------

def _run_initial(
    *,
    t1w: Path,
    flair: Optional[Path],
    subj_dir: Path,
    subjects_dir: Path,
    subject_id: str,
    cpus: int,
    parallel: bool,
    highres: bool,
    no_fix_ga: bool,
    force: bool,
    env: dict,
    logger,
) -> None:
    if subj_dir.exists():
        if not force:
            raise RuntimeError(
                f"FS subject directory already exists: {subj_dir}\n"
                f"  - use --force to wipe and start over, or\n"
                f"  - use --edit pial|wm for a rerun after manual edits."
            )
        logger.warning(f"--force: removing existing subject dir {subj_dir}")
        shutil.rmtree(subj_dir)

    cmd = [
        "recon-all",
        "-i", str(t1w),
        "-s", subject_id,
        "-sd", str(subjects_dir),
        "-openmp", str(cpus),
    ]
    if parallel:
        cmd.append("-parallel")

    if highres:
        cmd.append("-hires")
        logger.info("Including -hires (sub-mm input)")

    if no_fix_ga:
        cmd.append("-no-fix-ga")
        logger.info("Including -no-fix-ga (skip gyrus-ambiens cortex-label fix)")

    if flair is not None:
        if not flair.exists():
            raise FileNotFoundError(f"FLAIR image not found: {flair}")
        cmd += ["-FLAIR", str(flair), "-FLAIRpial"]
        logger.info(f"Including -FLAIR {flair.name} -FLAIRpial")

    cmd.append("-all")

    logger.info("Command: " + " ".join(cmd))
    run_command(cmd, logger, env=env)
    logger.info(f"Initial recon-all complete for {subject_id}")


# ---------------------------------------------------------------------------
# Rerun mode
# ---------------------------------------------------------------------------

def _run_rerun(
    *,
    subj_dir: Path,
    subjects_dir: Path,
    subject_id: str,
    edit: str,
    cpus: int,
    parallel: bool,
    highres: bool,
    no_fix_ga: bool,
    env: dict,
    logger,
) -> None:
    if not subj_dir.exists():
        raise RuntimeError(
            f"FS subject directory not found: {subj_dir}\n"
            f"Run without --edit to do the initial recon-all first."
        )

    # backup the subject directory before we touch it
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = subjects_dir / ".backups"
    backup_root.mkdir(exist_ok=True)
    backup_dir = backup_root / f"{subject_id}_{timestamp}"
    logger.info(f"Backing up subject directory to {backup_dir}")
    shutil.copytree(subj_dir, backup_dir, symlinks=True)

    if edit == "pial":
        recon_flags = ["-autorecon-pial", "-autorecon3"]
        logger.info("Rerun strategy: -autorecon-pial -autorecon3 (brainmask edit)")
    else:  # "wm"
        recon_flags = ["-autorecon2-wm", "-autorecon3"]
        logger.info("Rerun strategy: -autorecon2-wm -autorecon3 (wm +/- brainmask edit)")

    cmd = [
        "recon-all",
        *recon_flags,
        "-s", subject_id,
        "-sd", str(subjects_dir),
        "-openmp", str(cpus),
    ]
    if parallel:
        cmd.append("-parallel")

    if highres:
        cmd.append("-hires")

    if no_fix_ga:
        cmd.append("-no-fix-ga")

    cmd += _reuse_flair_flag(subj_dir, logger)

    logger.info("Command: " + " ".join(cmd))
    run_command(cmd, logger, env=env)
    logger.info(f"Rerun complete for {subject_id}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reuse_flair_flag(subj_dir: Path, logger) -> list:
    """Re-add -FLAIRpial on a rerun if the FLAIR was conformed into mri/FLAIR.mgz."""
    if (subj_dir / "mri" / "FLAIR.mgz").exists():
        logger.info("Re-using FLAIR for pial refinement (-FLAIRpial)")
        return ["-FLAIRpial"]
    return []


def _resolve_subjects_dir(
    cli_value: Optional[Path],
    config: dict,
    studydir: Path,
) -> Path:
    if cli_value is not None:
        return Path(cli_value).resolve()
    cfg = config_get(config, "tools.freesurfer.subjects_dir")
    if cfg is not None:
        candidate = Path(cfg)
        if not candidate.is_absolute():
            candidate = studydir / candidate
        return candidate.resolve()
    return (studydir / "derivatives" / "freesurfer").resolve()


def _derive_subject_id(t1w: Path) -> str:
    ents = extract_bids_entities(t1w)
    sub = ents.get("sub")
    if not sub:
        raise ValueError(
            f"Could not derive FS subject ID from {t1w.name}. Use --subject-id."
        )
    ses = ents.get("ses")
    return f"sub-{sub}_ses-{ses}" if ses else f"sub-{sub}"


def _warn_missing_license(config: dict, logger) -> None:
    license_path = config_get(config, "tools.freesurfer.license")
    if license_path and not Path(license_path).exists():
        logger.warning(f"FreeSurfer license configured but not found: {license_path}")


def _refuse_if_running(subj_dir: Path, logger) -> None:
    # Refuse to act if recon-all looks like it is mid-run
    if not subj_dir.exists():
        return
    scripts = subj_dir / "scripts"
    if not scripts.exists():
        return
    for hemi in ("lh", "rh", "lh+rh"):
        flag = scripts / f"IsRunning.{hemi}"
        if flag.exists():
            raise RuntimeError(
                f"recon-all appears to be running ({flag} present). "
                f"If it is not, delete this file manually and retry."
            )