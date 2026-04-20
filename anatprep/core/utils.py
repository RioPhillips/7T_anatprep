"""
Shared utility functions for anatprep.

Includes config-file discovery, logging setup, command runners, BIDS
entity extraction, and output-path helpers.
"""

import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------

MAX_SEARCH_DEPTH = 4
ANATPREP_CONFIG_NAME = "anatprep_config.yml"
MP2RAGE_PARAMS_NAME = "mp2rage.yaml"


def find_studydir_from_cwd(max_depth: int = MAX_SEARCH_DEPTH) -> Optional[Path]:
    """
    Find the study directory by walking upward from CWD.

    Recognises a study by the presence of any of:
        code/anatprep_config.yml
        code/mp2rage.yaml
        code/config.json      (dcm2bids config)
        rawdata/
    """
    current = Path.cwd().resolve()

    for _ in range(max_depth):
        markers = [
            current / "code" / ANATPREP_CONFIG_NAME,
            current / "code" / MP2RAGE_PARAMS_NAME,
            current / "code" / "config.json",
            current / "rawdata",
        ]
        if any(m.exists() for m in markers):
            return current

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def resolve_studydir(explicit: Optional[Path] = None) -> Path:
    """
    Resolve the study directory to use.

    Priority:
        1. Explicitly provided via --studydir
        2. Auto-detect from CWD upward

    Raises click.UsageError if nothing found.
    """
    import click

    if explicit is not None:
        path = Path(explicit)
        if not path.exists():
            raise click.UsageError(f"Study directory does not exist: {path}")
        return path.resolve()

    studydir = find_studydir_from_cwd()
    if studydir is not None:
        return studydir

    raise click.UsageError(
        "Could not locate the study directory.\n\n"
        "Either:\n"
        "  1. Run from within your study directory tree\n"
        "  2. Use '--studydir /path/to/study'"
    )


def load_anatprep_config(studydir: Path) -> Dict[str, Any]:
    """
    Load code/anatprep_config.yml. Returns {} if missing.
    """
    config_path = Path(studydir) / "code" / ANATPREP_CONFIG_NAME
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def load_mp2rage_params(studydir: Path) -> Optional[Dict[str, Any]]:
    """
    Load MP2RAGE acquisition parameters from code/mp2rage.yaml.

    Expected keys:
        RepetitionTimeExcitation, RepetitionTimePreparation,
        InversionTime (list[2]), NumberShots, FlipAngle (list[2])

    Returns None if the file is missing or incomplete.
    """
    params_path = Path(studydir) / "code" / MP2RAGE_PARAMS_NAME
    if not params_path.exists():
        return None

    try:
        with open(params_path) as f:
            params = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return None

    required = [
        "RepetitionTimeExcitation",
        "RepetitionTimePreparation",
        "InversionTime",
        "NumberShots",
        "FlipAngle",
    ]
    if any(k not in params for k in required):
        return None

    return params


def config_get(config: Dict[str, Any], key: str, default: Any = None) -> Any:
    """Dot-separated key access into a nested dict."""
    keys = key.split(".")
    val = config
    try:
        for k in keys:
            val = val[k]
    except (KeyError, TypeError):
        return default
    return val


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def resolve_log_dir(studydir: Path, subject: str) -> Path:
    """
    Return the central log directory for a subject.

    Path: <studydir>/derivatives/logs/anatprep/sub-<subject>/
    """
    log_dir = studydir / "derivatives" / "logs" / "anatprep" / f"sub-{subject}"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_command_logging(
    command_name: str,
    input_path: Path,
    verbose: bool = False,
) -> Tuple[logging.Logger, Optional[Path]]:
    """
    Set up logging for a command with a central log file.

    Extracts the subject from the input filename, resolves the study
    directory, and writes a timestamped log to:
        <studydir>/derivatives/logs/anatprep/sub-<subject>/<command>_<timestamp>.log

    Returns (logger, log_dir). log_dir is None if the subject or study
    directory could not be determined (logging still works on the console).
    """
    entities = extract_bids_entities(input_path)
    subject = entities.get("sub")
    log_dir = None
    log_file = None

    if subject:
        try:
            studydir = resolve_studydir()
            log_dir = resolve_log_dir(studydir, subject)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = log_dir / f"{command_name}_{timestamp}.log"
        except Exception:
            pass

    logger = setup_logging(command_name, log_file=log_file, verbose=verbose)

    if log_file:
        logger.info(f"Log file: {log_file}")
    elif subject is None:
        logger.debug("Could not extract subject from filename; no file log created.")

    return logger, log_dir


def setup_logging(
    name: str,
    log_file: Optional[Path] = None,
    verbose: bool = False,
) -> logging.Logger:
    """Configure and return a logger."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    logger.addHandler(console)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# Command runner
# ---------------------------------------------------------------------------

def run_command(
    cmd: List[str],
    logger: logging.Logger,
    log_file: Optional[Path] = None,
    capture_output: bool = False,
    check: bool = True,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess:
    """Run a shell command with logging."""
    logger.debug(f"Running: {' '.join(cmd)}")

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "w") as lf:
            result = subprocess.run(
                cmd, stdout=lf, stderr=subprocess.STDOUT, text=True,
                env=run_env, cwd=cwd,
            )
    elif capture_output:
        result = subprocess.run(
            cmd, capture_output=True, text=True, env=run_env, cwd=cwd,
        )
    else:
        result = subprocess.run(cmd, text=True, env=run_env, cwd=cwd)

    if check and result.returncode != 0:
        logger.error(f"Command failed with code {result.returncode}")
        if log_file:
            logger.error(f"See log: {log_file}")
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")

    return result


# ---------------------------------------------------------------------------
# Log copying helper
# ---------------------------------------------------------------------------

def copy_logs_to_central(source_dir: Path, central_log_dir: Path, prefix: str = "") -> None:
    """
    Copy .log files from source_dir into the central log directory.

    Files are prefixed to avoid collisions.
    """
    import shutil

    if not source_dir.exists() or central_log_dir is None:
        return

    for log_file in source_dir.glob("*.log"):
        dest_name = f"{prefix}{log_file.name}" if prefix else log_file.name
        dest = central_log_dir / dest_name
        try:
            shutil.copy2(str(log_file), str(dest))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------

def input_stem(path: Path) -> str:
    """
    Return the filename stem, handling the double extension ``.nii.gz``.

    >>> input_stem(Path("sub-01_run-1_T1w.nii.gz"))
    'sub-01_run-1_T1w'
    """
    name = Path(path).name
    if name.endswith(".nii.gz"):
        return name[:-7]
    return Path(path).stem


def default_output(
    input_path: Path,
    suffix: str,
    outdir: Optional[Path] = None,
    ext: str = ".nii.gz",
) -> Path:
    """
    Build a default output path as ``<outdir>/<input_stem>_<suffix><ext>``.

    If *outdir* is None, the current working directory is used.
    """
    outdir = Path(outdir) if outdir is not None else Path.cwd()
    return outdir / f"{input_stem(input_path)}_{suffix}{ext}"


def check_output(
    output: Path,
    logger: logging.Logger,
    force: bool = False,
) -> bool:
    """
    Return True if the command should run, False if the output already exists
    and force is False.
    """
    if output.exists() and not force:
        logger.info(f"Output already exists (use --force to overwrite): {output}")
        return False
    return True


# ---------------------------------------------------------------------------
# BIDS helpers
# ---------------------------------------------------------------------------

_BIDS_ENTITY_RE = {
    "sub": re.compile(r"(?:^|_)sub-([a-zA-Z0-9]+)"),
    "ses": re.compile(r"(?:^|_)ses-([a-zA-Z0-9]+)"),
    "run": re.compile(r"(?:^|_)run-(\d+)"),
}


def extract_bids_entities(path: Path) -> Dict[str, str]:
    """
    Extract BIDS entities (sub, ses, run) from a filename.

    Missing entities are simply absent from the returned dict.
    """
    name = Path(path).name
    result: Dict[str, str] = {}
    for key, regex in _BIDS_ENTITY_RE.items():
        m = regex.search(name)
        if m:
            result[key] = m.group(1)
    return result


def check_consistent_entities(
    files: Sequence[Path],
    entities: Sequence[str] = ("sub", "ses", "run"),
) -> Dict[str, str]:
    """
    Verify that all *files* share the same value for each given entity.

    An entity that is missing on one file but present on another counts as
    an inconsistency. Entities absent from *all* files are simply skipped.

    Returns the dict of shared entity values.

    Raises
    ------
    ValueError
        If any entity differs between inputs.
    """
    if not files:
        return {}

    per_file = [(Path(f), extract_bids_entities(f)) for f in files]
    shared: Dict[str, str] = {}

    for key in entities:
        values = {ents.get(key) for _, ents in per_file}

        if values == {None}:
            continue  # entity not present anywhere

        if len(values) > 1:
            details = "\n".join(
                f"  {f.name}: {key}={ents.get(key, '<missing>')}"
                for f, ents in per_file
            )
            raise ValueError(
                f"Input files have inconsistent '{key}' entity:\n{details}"
            )

        shared[key] = next(iter(values - {None}))

    return shared


def bids_prefix(entities: Dict[str, str], fallback: str) -> str:
    """
    Build a ``sub-XX[_ses-YY][_run-N]`` prefix from an entities dict.

    Falls back to *fallback* if no ``sub`` entity is present.
    """
    parts = []
    if "sub" in entities:
        parts.append(f"sub-{entities['sub']}")
    if "ses" in entities:
        parts.append(f"ses-{entities['ses']}")
    if "run" in entities:
        parts.append(f"run-{entities['run']}")
    return "_".join(parts) if parts else fallback


def get_docker_user_args() -> List[str]:
    # Return --user UID:GID args for Docker
    uid = os.getuid()
    gid = os.getgid()
    return ["--user", f"{uid}:{gid}"]