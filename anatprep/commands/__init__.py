"""
Command modules for anatprep CLI.

Each module exposes a single ``run_*`` function that is imported
lazily by cli.py (same pattern as dcm2bids).
"""

from typing import Callable, List, Optional
from pathlib import Path

from anatprep.core.subject import Subject


def iter_sessions(
    studydir: Path,
    subject: str,
    session: Optional[str],
) -> List[Subject]:
    """
    Resolve the list of Subject objects to process.

    If *session* is given, return a single-element list.
    If *session* is None, return one Subject per available session.
    Raises if the subject or session doesn't exist.
    """
    base = Subject(studydir, subject)
    base.validate()

    if session is not None:
        sub = Subject(studydir, subject, session)
        sub.validate()
        return [sub]

    sessions = base.get_sessions()
    if not sessions:
        raise FileNotFoundError(
            f"No sessions found for sub-{subject} in {base.rawdata_root}"
        )

    return [Subject(studydir, subject, ses) for ses in sessions]
