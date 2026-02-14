from pathlib import Path
from typing import Optional

from anatprep.commands import iter_sessions
from anatprep.core import setup_logging


def run_inspect(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    verbose: bool = False,
) -> None:
    subjects = iter_sessions(studydir, subject, session)

    for sub in subjects:
        logger = setup_logging("inspect", sub.log_dir / "inspect.log", verbose)
        logger.info(f"QC inspection for {sub}")
        logger.info("QC snapshot generation not yet implemented.")
        logger.info("For now, inspect outputs manually with ITK-Snap or freeview.")
