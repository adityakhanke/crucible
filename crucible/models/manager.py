"""Model Manager — the GPU gatekeeper.

Only one model occupies VRAM at any time. The manager handles:
1. Killing the current inference process
2. Starting the next model's inference server
3. Waiting for the health check to pass
4. Providing the OpenAI-compatible base URL to callers
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from crucible.config import models as load_models_config, get_model_config

logger = logging.getLogger(__name__)


@dataclass
class ActiveModel:
    persona: str
    name: str
    engine: str
    process: subprocess.Popen
    port: int
    base_url: str


class ModelManager:
    """Manages sequential model loading on a single GPU.

    Usage:
        mgr = ModelManager()
        mgr.load("prospector")       # Starts DeepSeek R1
        url = mgr.base_url           # "http://localhost:8080/v1"
        mgr.load("cartographer")     # Kills DeepSeek, starts Ministral
        mgr.unload()                 # Kills current model
    """

    def __init__(self):
        self._active: ActiveModel | None = None
        self._config = load_models_config()

    @property
    def active(self) -> ActiveModel | None:
        return self._active

    @property
    def base_url(self) -> str | None:
        return self._active.base_url if self._active else None

    @property
    def active_persona(self) -> str | None:
        return self._active.persona if self._active else None

    def load(self, persona: str) -> str:
        """Load a model by persona name. Returns the base URL.

        If a different model is already loaded, it is killed first.
        If the same model is already loaded, this is a no-op.
        """
        if self._active and self._active.persona == persona:
            logger.info(f"Model '{persona}' already loaded.")
            return self._active.base_url

        if self._active:
            self.unload()

        cfg = get_model_config(persona)
        engine = cfg["engine"]
        port = cfg.get("port", 8080)

        logger.info(f"Loading model: {cfg['name']} via {engine} on port {port}")

        if engine == "llamacpp":
            process = self._start_llamacpp(cfg, port)
        elif engine in ("sglang", "vllm"):
            process = self._start_python_engine(cfg, engine, port)
        else:
            raise ValueError(f"Unknown engine: {engine}")

        # Wait for health check
        self._wait_for_health(port)

        base_url = f"http://localhost:{port}/v1"
        self._active = ActiveModel(
            persona=persona,
            name=cfg["name"],
            engine=engine,
            process=process,
            port=port,
            base_url=base_url,
        )
        logger.info(f"Model '{persona}' ({cfg['name']}) ready at {base_url}")
        return base_url

    def unload(self):
        """Kill the currently loaded model."""
        if not self._active:
            return

        logger.info(f"Unloading model: {self._active.name}")
        proc = self._active.process

        # Graceful kill
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            # Force kill
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait(timeout=5)
            except Exception:
                pass

        self._active = None
        # Brief pause to let VRAM fully release
        time.sleep(2)
        logger.info("Model unloaded. VRAM released.")

    def _start_llamacpp(self, cfg: dict, port: int) -> subprocess.Popen:
        """Start a llama-server process."""
        engine_cfg = self._config["inference"]["engines"]["llamacpp"]
        binary = engine_cfg["binary"]
        model_path = str(Path(cfg["model_path"]).expanduser())

        cmd = [
            binary,
            "--model", model_path,
            "--port", str(port),
            *engine_cfg.get("common_args", []),
            *cfg.get("extra_args", []),
        ]

        logger.debug(f"llama.cpp command: {' '.join(cmd)}")
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )

    def _start_python_engine(self, cfg: dict, engine: str, port: int) -> subprocess.Popen:
        """Start a vLLM or SGLang server."""
        engine_cfg = self._config["inference"]["engines"][engine]
        module = engine_cfg["module"]
        model_path = cfg["model_path"]

        cmd = [
            "python", "-m", module,
            "--model", model_path,
            "--port", str(port),
            "--host", "0.0.0.0",
            *engine_cfg.get("common_args", []),
            *cfg.get("extra_args", []),
        ]

        logger.debug(f"{engine} command: {' '.join(cmd)}")
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )

    def _wait_for_health(self, port: int, timeout: int = 120):
        """Poll health endpoint until the server is ready."""
        inf_cfg = self._config["inference"]
        url = inf_cfg["health_check_url"].format(port=port)
        interval = inf_cfg.get("health_check_interval", 1)
        deadline = time.time() + timeout

        logger.info(f"Waiting for health check at {url} ...")
        while time.time() < deadline:
            try:
                resp = httpx.get(url, timeout=3)
                if resp.status_code == 200:
                    return
            except httpx.ConnectError:
                pass
            time.sleep(interval)

        raise TimeoutError(f"Model server did not become healthy within {timeout}s")
