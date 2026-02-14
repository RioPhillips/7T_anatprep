"""
Subject: file handling class for anatprep.

Methods for finding files in rawdata/ and derivatives/anatprep/,
construct BIDS-compliant output paths, and discover MP2RAGE runs.

The derivatives layout is flat per session:

    derivatives/anatprep/sub-XX/ses-YY/
        sub-XX_ses-YY_run-1_desc-spmmask_mask.nii.gz
        sub-XX_ses-YY_run-1_desc-pymp2rage_T1w.nii.gz
        ...
        cat12/   (CAT12 produces many files)
        iter-1/  (brainmask iteration outputs)

Logs go to:

    derivatives/anatprep/sub-XX/ses-YY/logs/
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Union


class Subject:
    """Represents a single subject (session level is optional)."""

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
            If None, the caller is expected to iterate over sessions
            returned by :meth:`get_sessions`.
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

        # session-specific paths (when session is set)
        if session:
            self.rawdata_dir = self.rawdata_root / self.sub_prefix / self.ses_prefix
            self.anat_dir = self.rawdata_dir / "anat"
            self.deriv_dir = self.deriv_root / self.sub_prefix / self.ses_prefix
            self.log_dir = self.deriv_dir / "logs"
        else:
            self.rawdata_dir = self.rawdata_root / self.sub_prefix
            self.anat_dir = None
            self.deriv_dir = None
            self.log_dir = None

    # session and run discovery

    def get_sessions(self) -> List[str]:
        """
        Return all session IDs for this subject (e.g. ['MR1', 'MR2']).

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
        Discover MP2RAGE run numbers from rawdata/anat/.

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

    # Rawdata file finders

    def get_rawdata_file(
        self,
        pattern: str,
        run: Optional[int] = None,
        ext: str = ".nii.gz",
        return_all: bool = False,
    ) -> Union[Path, List[Path]]:
        """
        Find file(s) matching *pattern* under rawdata/sub-XX/ses-YY/anat/.

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
        """Check if any FLAIR images exist for this session."""
        if self.anat_dir is None:
            return False
        return bool(list(self.anat_dir.glob("*FLAIR*.nii.gz")))

    def get_flair_files(self) -> List[Path]:
        """Return all FLAIR NIfTI files for this session."""
        if self.anat_dir is None:
            return []
        return sorted(self.anat_dir.glob("*FLAIR*.nii.gz"))

    # derivatives output paths

    def ensure_deriv_dirs(self) -> None:
        """Create the derivatives output directories."""
        if self.deriv_dir:
            self.deriv_dir.mkdir(parents=True, exist_ok=True)
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)

    def deriv_path(self, desc: str, suffix: str, run: Optional[int] = None,
                   ext: str = ".nii.gz", subdir: Optional[str] = None) -> Path:
        """
        Construct a BIDS-derivatives output path.

        Example
        -------
        >>> sub.deriv_path("spmmask", "mask", run=1)
        derivatives/anatprep/sub-XX/ses-YY/sub-XX_ses-YY_run-1_desc-spmmask_mask.nii.gz

        >>> sub.deriv_path("cat12", "T1w", run=1, subdir="cat12")
        derivatives/anatprep/sub-XX/ses-YY/cat12/sub-XX_ses-YY_run-1_desc-cat12_T1w.nii.gz
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

    # derivatives file finders

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

    # some validation checks

    def validate(self) -> None:
        """
        Check that the rawdata directory exists.

        Raises FileNotFoundError with a helpful message if not.
        """
        if not (self.rawdata_root / self.sub_prefix).exists():
            raise FileNotFoundError(
                f"Subject directory not found: "
                f"{self.rawdata_root / self.sub_prefix}\n"
                f"Has dcm2bids been run for sub-{self.subject}?"
            )

        if self.session and not self.rawdata_dir.exists():
            raise FileNotFoundError(
                f"Session directory not found: {self.rawdata_dir}\n"
                f"Available sessions: {self.get_sessions()}"
            )

    def __repr__(self) -> str:
        ses = f"_ses-{self.session}" if self.session else ""
        return f"<Subject sub-{self.subject}{ses}>"
