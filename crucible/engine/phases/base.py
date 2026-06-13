"""Base class for all dialectical phases.

Handles checkpointing (idempotent execution) and prompt loading.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from crucible.config import get_paths
from crucible.models.client import LLMClient

logger = logging.getLogger(__name__)


class BasePhase(ABC):
    """Abstract base for pipeline phases.

    Provides:
    - Checkpoint loading/saving (idempotent LLM calls)
    - System prompt loading from prompts/ directory
    - Atomic writes (write-then-rename pattern)
    """

    phase_name: str = "base"
    persona: str = "base"

    def __init__(self, cycle_id: str, llm: Optional[LLMClient] = None):
        self.cycle_id = cycle_id
        self.llm = llm
        self._prompts_dir = Path(get_paths()["prompts_dir"])
        self._checkpoints_dir = Path(get_paths()["checkpoints_dir"])
        self._checkpoints_dir.mkdir(parents=True, exist_ok=True)

    @property
    def checkpoint_path(self) -> Path:
        return self._checkpoints_dir / f"cycle_{self.cycle_id}_phase_{self.phase_name}_output.json"

    def has_checkpoint(self) -> bool:
        return self.checkpoint_path.exists()

    def load_checkpoint(self) -> Optional[dict]:
        if self.has_checkpoint():
            logger.info(f"[{self.phase_name}] Loading checkpoint: {self.checkpoint_path}")
            with open(self.checkpoint_path) as f:
                return json.load(f)
        return None

    def save_checkpoint(self, data: dict):
        """Atomic write: write to .tmp, fsync, rename."""
        tmp_path = self.checkpoint_path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, self.checkpoint_path)
        logger.info(f"[{self.phase_name}] Checkpoint saved: {self.checkpoint_path}")

    def load_prompt(self) -> str:
        """Load the system prompt for this phase."""
        prompt_file = self._prompts_dir / f"{self.persona}.md"
        if not prompt_file.exists():
            raise FileNotFoundError(f"Prompt not found: {prompt_file}")
        return prompt_file.read_text(encoding="utf-8")

    def run(self, **kwargs) -> dict:
        """Execute the phase with checkpointing.

        If a checkpoint exists, return cached output.
        Otherwise, execute the phase and save the checkpoint.
        """
        cached = self.load_checkpoint()
        if cached is not None:
            logger.info(f"[{self.phase_name}] Using cached output.")
            return cached

        logger.info(f"[{self.phase_name}] Executing...")
        result = self.execute(**kwargs)
        self.save_checkpoint(result)
        return result

    @abstractmethod
    def execute(self, **kwargs) -> dict:
        """Phase-specific logic. Must be implemented by subclasses."""
        ...
