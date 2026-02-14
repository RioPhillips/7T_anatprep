"""
IterationState: tracks the brainmask refinement loop on disk.

State is persisted as a JSON file inside the derivatives directory so
that the user can close the terminal, edit masks in ITK-Snap, and
resume later.

    derivatives/anatprep/sub-XX/ses-YY/iteration_state.json

The file records the current iteration number, the status of each
iteration, and which masks were used.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


MAX_ITERATIONS = 5

# statuses for an iteration
STATUS_PENDING = "pending"            # fMRIprep has not been run yet
STATUS_RUNNING = "running"            # fMRIprep is currently running
STATUS_AWAITING_REVIEW = "awaiting_review"  # fMRIprep done, user should inspect
STATUS_AWAITING_EDIT = "awaiting_edit"      # user chose to refine mask
STATUS_FINALIZED = "finalized"              # user accepted this iteration


class IterationState:
    """
    Manage brainmask iteration state for a single subject/session.

    Usage
    -----
    >>> state = IterationState(deriv_dir)
    >>> state.current_iteration
    1
    >>> state.status
    'pending'
    >>> state.set_status("running")
    >>> state.advance()   # -> iteration 2
    """

    def __init__(self, deriv_dir: Path):
        self.deriv_dir = Path(deriv_dir)
        self.state_file = self.deriv_dir / "iteration_state.json"
        self._state = self._load()

    # properties

    @property
    def current_iteration(self) -> int:
        return self._state["current_iteration"]

    @property
    def status(self) -> str:
        return self._state["status"]

    @property
    def is_finalized(self) -> bool:
        return self.status == STATUS_FINALIZED

    @property
    def can_advance(self) -> bool:
        return (
            self.current_iteration < MAX_ITERATIONS
            and not self.is_finalized
        )

    @property
    def history(self) -> list:
        return self._state.get("history", [])

    
    # state updating

    def set_status(self, status: str, note: str = "") -> None:
        """Update the status of the current iteration."""
        self._state["status"] = status
        self._state["updated_at"] = _now()

        # append to history
        self._state.setdefault("history", []).append({
            "iteration": self.current_iteration,
            "status": status,
            "note": note,
            "timestamp": _now(),
        })

        self._save()

    def advance(self) -> int:
        """
        Move to the next iteration.

        Returns the new iteration number.

        Raises
        ------
        RuntimeError
            If already at MAX_ITERATIONS or finalized.
        """
        if self.is_finalized:
            raise RuntimeError("Cannot advance: iteration is finalized.")

        if self.current_iteration >= MAX_ITERATIONS:
            raise RuntimeError(
                f"Cannot advance: already at max iterations ({MAX_ITERATIONS})."
            )

        self._state["current_iteration"] += 1
        self._state["status"] = STATUS_PENDING
        self._state["updated_at"] = _now()
        self._save()

        return self.current_iteration

    def finalize(self) -> None:
        """Mark the current iteration as the final, accepted result."""
        self.set_status(STATUS_FINALIZED, "User accepted this iteration.")

    def reset(self) -> None:
        """Reset to iteration 1 (destructive - does not delete files)."""
        self._state = self._default_state()
        self._save()

    # persistance

    def _load(self) -> Dict[str, Any]:
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return self._default_state()

    def _save(self) -> None:
        self.deriv_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(self._state, f, indent=2)

    @staticmethod
    def _default_state() -> Dict[str, Any]:
        return {
            "current_iteration": 1,
            "status": STATUS_PENDING,
            "created_at": _now(),
            "updated_at": _now(),
            "history": [],
        }

    # display

    def summary(self) -> str:
        """One-line human-readable summary."""
        return (
            f"Iteration {self.current_iteration}/{MAX_ITERATIONS}  "
            f"status: {self.status}"
        )

    def __repr__(self) -> str:
        return f"<IterationState iter={self.current_iteration} status={self.status}>"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
