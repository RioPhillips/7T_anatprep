"""
Subject: file handling class for anatprep.

Supports both session-based and sessionless BIDS datasets.

Session-based layout (rawdata/sub-XX/ses-YY/anat/):
    derivatives/anatprep/sub-XX/ses-YY/

Sessionless layout (rawdata/sub-XX/anat/):
    derivatives/anatprep/sub-XX/

The derivatives layout is flat per subject/session:

    derivatives/anatprep/sub-XX/[ses-YY/]
        sub-XX[_ses-YY]_run-1_desc-spmmask_mask.nii.gz
        sub-XX[_ses-YY]_run-1_desc-pymp2rage_T1w.nii.gz
        ...
        cat12/   (CAT12 produces many files)
        iter-1/  (brainmask iteration outputs)

Logs go to:

    derivatives/anatprep/sub-XX/[ses-YY/]logs/
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Union


class Subject:
    """Represents a single subject (optionally pinned to a session)."""

    def __init__(self, studydir: Path, subject: str, session: Optional[str] = None):
        """
        Parameters
        ----------
        studydir : Path
            Root of the BIDS study (contains rawdata/, derivatives/, code/).
        subject : str
            Subject ID *without* the ``sub-`` prefix.
        session : str or None
            Session ID *without* ``ses-`` prefix.
            If None, auto-detects whether the dataset is sessionless and
            sets up paths accordingly. For session-based datasets without
            a pinned session, use :meth:`get_sessions` to iterate.
        """
        self.studydir = Path(studydir).resolve()
        self.subject = subject
        self.session = session

        # prefixes
        self.sub_prefix = f"sub-{subject}"
        self.ses_prefix = f"ses-{session}" if session else None
        self.subses_prefix = (
            f"sub-{subject}_ses-{session}" if session else f"sub-{subject}"
        )

        # root paths
        self.rawdata_root = self.studydir / "rawdata"
        self.deriv_root = self.studydir / "derivatives" / "anatprep"

        sub_dir = self.rawdata_root / self.sub_prefix

        if session:
            # --- session-based, pinned to a specific session ---
            self.rawdata_dir = sub_dir / self.ses_prefix
            self.anat_dir = self.rawdata_dir / "anat"
            self.fmap_dir = self.rawdata_dir / "fmap"
            self.deriv_dir = self.deriv_root / self.sub_prefix / self.ses_prefix
            self.log_dir = self.deriv_dir / "logs"

        elif self._is_sessionless(sub_dir):
            # --- sessionless dataset (anat/ directly under sub-XX/) ---
            self.rawdata_dir = sub_dir
            self.anat_dir = sub_dir / "anat"
            self.fmap_dir = sub_dir / "fmap"
            self.deriv_dir = self.deriv_root / self.sub_prefix
            self.log_dir = self.deriv_dir / "logs"

        else:
            # --- session-based, no session pinned (discovery/base mode) ---
            self.rawdata_dir = sub_dir
            self.anat_dir = None
            self.fmap_dir = None
            self.deriv_dir = None
            self.log_dir = None

    # ------------------------------------------------------------------
    # Session / run discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _is_sessionless(sub_dir: Path) -> bool:
        """
        Return True when anat/ lives directly under sub-XX/ (no ses-* dirs).

        A dataset is sessionless when:
          - sub_dir/anat/ exists, OR
          - sub_dir/ exists but contains no ses-* subdirectories.
        """
        if not sub_dir.exists():
            return False
        if (sub_dir / "anat").exists():
            return True
        # directory exists but has no ses-* children → treat as sessionless
        has_sessions = any(
            d.is_dir() and d.name.startswith("ses-")
            for d in sub_dir.iterdir()
        )
        return not has_sessions

    def is_sessionless(self) -> bool:
        """Return True if this subject's dataset has no session level."""
        return self.session is None and self._is_sessionless(
            self.rawdata_root / self.sub_prefix
        )

    def get_sessions(self) -> List[str]:
        """
        Return all session IDs for this subject (e.g. ['MR1', 'MR2']).

        Returns an empty list for sessionless datasets.
        Scans rawdata/sub-XX/ for ses-* directories.
        """
        sub_dir = self.rawdata_root / self.sub_prefix
        if not sub_dir.exists():
            return []

        sessions = []
        for d in sorted(sub_dir.iterdir()):
            if d.is_dir() and d.name.startswith("ses-"):
                sessions.append(d.name.removeprefix("ses-"))
        return sessions

    def for_session(self, session: str) -> "Subject":
        """Return a new Subject pinned to a specific session."""
        return Subject(self.studydir, self.subject, session)

    def get_mp2rage_runs(self) -> List[int]:
        """
        Discover MP2RAGE run numbers from rawdata/[ses-YY/]anat/.

        Looks for *inv-1_part-mag_MP2RAGE* files and extracts run-N.
        Returns [1] if files exist but lack a run entity.
        """
        if self.anat_dir is None or not self.anat_dir.exists():
            return []

        pattern = "inv-1_part-mag_MP2RAGE"
        files = list(self.anat_dir.glob(f"*{pattern}*.nii.gz"))

        runs = set()
        for f in files:
            m = re.search(r"run-(\d+)", f.name)
            if m:
                runs.add(int(m.group(1)))
            else:
                runs.add(1)

        return sorted(runs) if runs else []

    # ------------------------------------------------------------------
    # Rawdata file finders
    # ------------------------------------------------------------------

    def get_rawdata_file(
        self,
        pattern: str,
        run: Optional[int] = None,
        ext: str = ".nii.gz",
        return_all: bool = False,
    ) -> Union[Path, List[Path]]:
        """
        Find file(s) matching *pattern* under rawdata anat directory.

        Parameters
        ----------
        pattern : str
            Substring to match in filenames (e.g. 'inv-2_part-mag_MP2RAGE').
        run : int or None
            If given, only match files containing ``run-{run}``.
        ext : str
            File extension to match.
        return_all : bool
            If True return list, else return first match.

        Raises
        ------
        FileNotFoundError
            If no matching files are found.
        """
        if self.anat_dir is None or not self.anat_dir.exists():
            raise FileNotFoundError(
                f"Anat directory not found: {self.anat_dir}"
            )

        found = []
        for f in sorted(self.anat_dir.glob(f"*{ext}")):
            if pattern not in f.name:
                continue
            if run is not None and f"run-{run}" not in f.name:
                continue
            found.append(f)

        if not found:
            raise FileNotFoundError(
                f"No rawdata files matching '{pattern}' "
                f"(run={run}) in {self.anat_dir}"
            )

        return found if return_all else found[0]

    def get_raw_mp2rage_parts(self, run: int) -> Dict[str, Path]:
        """Return the four MP2RAGE component files for a given run."""
        return {
            "inv1_mag": self.get_rawdata_file("inv-1_part-mag_MP2RAGE", run),
            "inv1_phase": self.get_rawdata_file("inv-1_part-phase_MP2RAGE", run),
            "inv2_mag": self.get_rawdata_file("inv-2_part-mag_MP2RAGE", run),
            "inv2_phase": self.get_rawdata_file("inv-2_part-phase_MP2RAGE", run),
        }

    def get_raw_inv2(self, run: int) -> Path:
        """Return the combined INV2 magnitude file (for SPM masking)."""
        return self.get_rawdata_file("inv-2_MP2RAGE", run)

    def get_raw_t1w(self, run: int) -> Path:
        """Return the raw UNIT1 (T1w) file from rawdata."""
        return self.get_rawdata_file("acq-mp2rage", run)

    def has_flair(self) -> bool:
        """Check if any FLAIR images exist for this subject/session."""
        if self.anat_dir is None:
            return False
        return bool(list(self.anat_dir.glob("*FLAIR*.nii.gz")))

    def get_flair_files(self) -> List[Path]:
        """Return all FLAIR NIfTI files for this subject/session."""
        if self.anat_dir is None:
            return []
        return sorted(self.anat_dir.glob("*FLAIR*.nii.gz"))

    # ------------------------------------------------------------------
    # Derivatives output paths
    # ------------------------------------------------------------------

    def ensure_deriv_dirs(self) -> None:
        """Create the derivatives output directories."""
        if self.deriv_dir:
            self.deriv_dir.mkdir(parents=True, exist_ok=True)
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

    def deriv_path(
        self,
        desc: str,
        suffix: str,
        run: Optional[int] = None,
        ext: str = ".nii.gz",
        subdir: Optional[str] = None,
    ) -> Path:
        """
        Construct a BIDS-derivatives output path.

        Examples
        --------
        Session-based:
            >>> sub.deriv_path("spmmask", "mask", run=1)
            derivatives/anatprep/sub-XX/ses-YY/sub-XX_ses-YY_run-1_desc-spmmask_mask.nii.gz

        Sessionless:
            >>> sub.deriv_path("spmmask", "mask", run=1)
            derivatives/anatprep/sub-XX/sub-XX_run-1_desc-spmmask_mask.nii.gz
        """
        parts = [self.subses_prefix]
        if run is not None:
            parts.append(f"run-{run}")
        parts.append(f"desc-{desc}")
        parts.append(suffix)

        filename = "_".join(parts) + ext

        base = self.deriv_dir
        if subdir:
            base = base / subdir
            base.mkdir(parents=True, exist_ok=True)

        return base / filename

    def iter_dir(self, iteration: int) -> Path:
        """Return the directory for a brainmask iteration."""
        d = self.deriv_dir / f"iter-{iteration}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------
    # Derivatives file finders
    # ------------------------------------------------------------------

    def find_deriv_file(
        self,
        pattern: str,
        run: Optional[int] = None,
        subdir: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Find a single file in derivatives matching *pattern*.

        Returns None if not found (does not raise).
        """
        search_root = self.deriv_dir
        if subdir:
            search_root = search_root / subdir

        if search_root is None or not search_root.exists():
            return None

        for f in sorted(search_root.glob("*.nii.gz")):
            if pattern not in f.name:
                continue
            if run is not None and f"run-{run}" not in f.name:
                continue
            return f

        return None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Check that the rawdata directory structure is as expected.

        Raises FileNotFoundError if:
          - The subject directory doesn't exist.
          - A specific session was requested but its directory is missing.
        """
        sub_dir = self.rawdata_root / self.sub_prefix
        if not sub_dir.exists():
            raise FileNotFoundError(
                f"Subject directory not found: {sub_dir}\n"
                f"Has bids7t been run for sub-{self.subject}?"
            )

        if self.session and not self.rawdata_dir.exists():
            raise FileNotFoundError(
                f"Session directory not found: {self.rawdata_dir}\n"
                f"Available sessions: {self.get_sessions()}"
            )

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        ses = f"_ses-{self.session}" if self.session else ""
        return f"<Subject sub-{self.subject}{ses}>"