"""Rented-GPU provisioning scaffold (Vast.ai / RunPod).

E4 is the only stage that needs a big NVIDIA GPU, so it is isolated and rented
by the hour. This module builds the provisioning *plan* (image, ports, mounts,
boot command); wiring it to a provider API is a thin layer on top and gated
behind an API key supplied in the app's Settings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

COMFY_IMAGE = "ghcr.io/kaika/comfyui-wan:latest"


@dataclass
class GPUPlan:
    image: str
    gpu: str
    ports: Dict[int, int]
    env: Dict[str, str]
    boot_cmd: List[str]

    def docker_run(self) -> str:
        ports = " ".join(f"-p {h}:{c}" for h, c in self.ports.items())
        env = " ".join(f"-e {k}={v}" for k, v in self.env.items())
        return (f"docker run --gpus all {ports} {env} "
                f"{self.image} {' '.join(self.boot_cmd)}").strip()


def plan(gpu: str = "RTX5090", comfy_port: int = 8188) -> GPUPlan:
    return GPUPlan(
        image=COMFY_IMAGE,
        gpu=gpu,
        ports={comfy_port: 8188},
        env={"COMFY_PORT": "8188"},
        boot_cmd=["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"],
    )
