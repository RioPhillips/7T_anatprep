"""
Shared utility functions for anatprep.

Includes config-file discovery,
logging setup, command runners, and common helpers.
"""

import json
import logging
import os
import subprocess
import sys
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# find config

MAX_SEARCH_DEPTH = 4
ANATPREP_CONFIG_NAME = "anatprep_config.yml"
MP2RAGE_JSON_NAME = "mp2rage.json"


def find_config_from_cwd(
    config_name: str = ANATPREP_CONFIG_NAME,
    max_depth: int = MAX_SEARCH_DEPTH,
) -> Optional[Path]:
    """
    Search for code/<config_name> starting from CWD and traversing upward.

    Also recognises the study directory by the presence of code/config.json
    (from dcm2bids) if the anatprep config is not found.

    Returns
    -------
    Path or None
        Path to config file if found.
    """
    current = Path.cwd().resolve()

    for _ in range(max_depth):
        # prefer anatprep-specific config
        anatprep_cfg = current / "code" / config_name
        if anatprep_cfg.exists():
            return anatprep_cfg

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def find_studydir_from_cwd(max_depth: int = MAX_SEARCH_DEPTH) -> Optional[Path]:
    """
    Find the study directory by looking for code/config.json OR
    code/anatprep_config.yml from CWD upward.
    """
    current = Path.cwd().resolve()

    for _ in range(max_depth):
        markers = [
            current / "code" / ANATPREP_CONFIG_NAME,
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
    Load code/anatprep_config.yml.

    Returns empty dict (with a warning) if the file does not exist,
    so that sensible defaults can be used downstream.
    """
    config_path = Path(studydir) / "code" / ANATPREP_CONFIG_NAME

    if not config_path.exists():
        return {}

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    return data


def load_mp2rage_params(studydir: Path) -> Optional[Dict[str, Any]]:
    """
    Load MP2RAGE acquisition parameters from code/mp2rage.json.

    This file is shared with dcm2bids and contains:
        RepetitionTimeExcitation, RepetitionTimePreparation,
        InversionTime (list[2]), NumberShots, FlipAngle (list[2]).

    Returns None if the file is missing or invalid.
    """
    mp2rage_json = Path(studydir) / "code" / MP2RAGE_JSON_NAME

    if not mp2rage_json.exists():
        return None

    try:
        with open(mp2rage_json) as f:
            params = json.load(f)
    except (json.JSONDecodeError, OSError):
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
    """
    Dot-separated key access into a nested dict.

    >>> config_get(cfg, "tools.spm_path", "/opt/spm")
    """
    keys = key.split(".")
    val = config
    try:
        for k in keys:
            val = val[k]
    except (KeyError, TypeError):
        return default
    return val


# logging


def setup_logging(
    name: str,
    log_file: Optional[Path] = None,
    verbose: bool = False,
) -> logging.Logger:
    """
    Configure and return a logger.

    Writes to *log_file* (DEBUG level) and to the console
    (DEBUG if verbose, else INFO).
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # console
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    logger.addHandler(console)

    # file
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(fh)

    return logger


# runs commands


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


# helpers


def check_outputs_exist(
    output_files: List[Path],
    logger: logging.Logger,
    force: bool = False,
) -> Tuple[bool, List[Path]]:
    """Return (should_run, existing_files)."""
    existing = [f for f in output_files if f.exists()]

    if existing and not force:
        logger.info(f"{len(existing)} output(s) already exist (use --force to overwrite)")
        for f in existing[:5]:
            logger.info(f"  - {f.name}")
        return False, existing

    return True, existing


def find_files(directory: Path, pattern: str, recursive: bool = False) -> List[Path]:
    """Glob for files in *directory*."""
    if not directory.exists():
        return []
    if recursive:
        return sorted(directory.rglob(pattern))
    return sorted(directory.glob(pattern))


def get_docker_user_args() -> List[str]:
    """Return --user UID:GID args for Docker."""
    uid = os.getuid()
    gid = os.getgid()
    return ["--user", f"{uid}:{gid}"]
