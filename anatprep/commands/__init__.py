"""
Command modules for anatprep CLI.

Each module exposes a single ``run_*`` function that is imported
lazily by cli.py.

Supports both session-based and sessionless BIDS datasets:
  - Session-based: rawdata/sub-XX/ses-YY/anat/
  - Sessionless:   rawdata/sub-XX/anat/
"""

from typing import List, Optional
from pathlib import Path

from anatprep.core.subject import Subject


def iter_sessions(
    studydir: Path,
    subject: str,
    session: Optional[str],
) -> List[Subject]:
    """
    Resolve the list of Subject objects to process.

    Behaviour
    ---------
    - If *session* is explicitly given: return that single session.
    - If *session* is None and the dataset has sessions: return one
      Subject per session found in rawdata/.
    - If *session* is None and the dataset is sessionless (anat/ sits
      directly under sub-XX/): return a single sessionless Subject.

    Raises
    ------
    FileNotFoundError
        If the subject directory does not exist, a requested session is
        missing, or no processable data can be found at all.
    """
    base = Subject(studydir, subject)
    base.validate()

    # --- explicit session requested ---
    if session is not None:
        sub = Subject(studydir, subject, session)
        sub.validate()
        return [sub]

    # --- auto-detect: session-based vs sessionless ---
    sessions = base.get_sessions()

    if sessions:
        # session-based dataset
        return [Subject(studydir, subject, ses) for ses in sessions]

    # No ses-* directories found.  Check whether this is a sessionless
    # dataset (anat/ directly under sub-XX/).
    if base.is_sessionless():
        return [base]

    raise FileNotFoundError(
        f"No sessions and no anat/ directory found for sub-{subject} "
        f"in {base.rawdata_root}.\n"
        f"Expected either:\n"
        f"  {base.rawdata_root}/sub-{subject}/ses-*/   (session-based)\n"
        f"  {base.rawdata_root}/sub-{subject}/anat/    (sessionless)"
    )