"""
fmriprep command: run fMRIprep + FreeSurfer via Docker.

Handles injection of the custom brainmask and sinus mask.
Updates the iteration state tracker.
"""

from pathlib import Path
from typing import Optional

from anatprep.commands import iter_sessions
from anatprep.core import (
    IterationState,
    setup_logging,
    load_anatprep_config,
    config_get,
    run_command,
    get_docker_user_args,
)


def run_fmriprep(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False,
) -> None:
    """Run fMRIprep + FreeSurfer via Docker."""
    subjects = iter_sessions(studydir, subject, session)
    config = load_anatprep_config(studydir)

    fmriprep_image = config_get(
        config, "tools.fmriprep.docker_image", "nipreps/fmriprep:latest"
    )
    fs_license = config_get(config, "tools.freesurfer.license")
    n_threads = config_get(config, "tools.fmriprep.n_threads", 8)
    mem_mb = config_get(config, "tools.fmriprep.mem_mb", 32000)

    if not fs_license:
        raise RuntimeError(
            "FreeSurfer license path not set in code/anatprep_config.yml.\n"
            "Add:\n  tools:\n    freesurfer:\n      license: /path/to/license.txt"
        )

    for sub in subjects:
        log_file = sub.log_dir / "fmriprep.log"
        logger = setup_logging("fmriprep", log_file, verbose)
        sub.ensure_deriv_dirs()

        # iteration state
        state = IterationState(sub.deriv_dir)
        iteration = state.current_iteration

        logger.info(f"Processing {sub} - iteration {iteration}")
        logger.info(f"  fMRIprep image: {fmriprep_image}")

        # paths
        rawdata_root = studydir / "rawdata"
        deriv_root = studydir / "derivatives"
        fmriprep_out = deriv_root / "fmriprep"
        freesurfer_out = deriv_root / "freesurfer"

        fmriprep_out.mkdir(parents=True, exist_ok=True)
        freesurfer_out.mkdir(parents=True, exist_ok=True)

        # save current masks to the iteration directory
        iter_dir = sub.iter_dir(iteration)
        _snapshot_masks(sub, iter_dir, logger)

        # mark as running
        state.set_status("running", f"fMRIprep iteration {iteration}")

        # build Docker command
        user_args = get_docker_user_args()

        cmd = [
            "docker", "run", "--rm",
            *user_args,
            # mounts
            "--volume", f"{rawdata_root}:/data:ro",
            "--volume", f"{fmriprep_out}:/out/fmriprep",
            "--volume", f"{freesurfer_out}:/out/freesurfer",
            "--volume", f"{fs_license}:/opt/freesurfer/license.txt:ro",
            "--volume", f"{sub.deriv_dir}:/anatprep:ro",
            # fmriprep
            fmriprep_image,
            "/data", "/out/fmriprep",
            "participant",
            "--participant-label", sub.subject,
            "--output-spaces", "T1w", "fsnative",
            "--fs-subjects-dir", "/out/freesurfer",
            "--nthreads", str(n_threads),
            "--mem-mb", str(mem_mb),
            "--skip-bids-validation",
            "--anat-only",
        ]

        # TODO: inject custom brainmask via --skull-strip-fixed-seed
        # or by pre-placing the mask in the FreeSurfer subject dir.
        # need more testing per fMRIprep version.

        logger.info(f"Running fMRIprep (iteration {iteration})")
        logger.debug(f"Command: {' '.join(cmd)}")

        try:
            run_command(cmd, logger, log_file=log_file)
            state.set_status("awaiting_review", f"Iteration {iteration} complete")
            logger.info(
                f"fMRIprep complete. Inspect results and run:\n"
                f"  anatprep brainmask-edit --subject {sub.subject} --session {sub.session}\n"
                f"  anatprep fmriprep --subject {sub.subject} --session {sub.session}\n"
                f"Or finalize with:\n"
                f"  anatprep status --subject {sub.subject} --session {sub.session}"
            )
        except RuntimeError:
            state.set_status("failed", f"fMRIprep failed at iteration {iteration}")
            logger.error("fMRIprep failed. Check the log for details.")
            raise


def _snapshot_masks(sub, iter_dir: Path, logger) -> None:
    """Copy current masks into the iteration directory for provenance."""
    import shutil

    for desc in ["spmmask", "sinusfinal", "sinusauto"]:
        for run in sub.get_mp2rage_runs():
            src = sub.find_deriv_file(f"desc-{desc}", run=run)
            if src and src.exists():
                dst = iter_dir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
                    logger.debug(f"Snapshot: {src.name} --> iter-{iter_dir.name}/")
