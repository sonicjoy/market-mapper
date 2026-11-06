"""In-cluster Batch Job create/list for gap-propose worker."""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_WORKER_LABEL = "app=gap-propose-worker"
_SA_TOKEN = "/var/run/secrets/kubernetes.io/serviceaccount/token"  # nosec B105 — K8s SA mount
_SA_NS = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
_SA_CA = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
_API = "https://kubernetes.default.svc"


def _in_cluster() -> bool:
    return os.path.isfile(_SA_TOKEN)


def _auth_headers() -> dict[str, str]:
    with open(_SA_TOKEN, encoding="utf-8") as handle:
        token = handle.read().strip()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _namespace() -> str:
    if os.path.isfile(_SA_NS):
        with open(_SA_NS, encoding="utf-8") as handle:
            return handle.read().strip()
    return os.environ.get("MAPPING_CONSOLE_NAMESPACE", "mapping-console")


def worker_job_running() -> bool | None:
    """True when a gap-propose worker is still starting or active.

    None when the API list failed — the checker must not start a second worker.
    """
    if not _in_cluster():
        return False
    ns = _namespace()
    url = f"{_API}/apis/batch/v1/namespaces/{ns}/jobs?labelSelector={_WORKER_LABEL}"
    req = urllib.request.Request(url, headers=_auth_headers())
    try:
        with _open(req, 15) as resp:  # nosec B310 — in-cluster K8s API HTTPS
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning("pipeline gap-drain k8s list jobs failed: %s", exc)
        return None
    return any(job_is_active(item.get("status") or {}) for item in body.get("items") or [])


def job_is_active(status: dict[str, Any]) -> bool:
    """False once the Job has Completed or Failed. Empty status is still starting."""
    for cond in status.get("conditions") or []:
        if cond.get("status") == "True" and cond.get("type") in {"Complete", "Failed"}:
            return False
    finished = bool(status.get("succeeded") or status.get("failed"))
    return bool(status.get("active")) or not finished


def create_worker_job(image: str | None = None) -> None:
    """Create a worker Job. Pass image to hand off; otherwise use this pod."""
    if not _in_cluster():
        logger.info("pipeline gap-drain k8s: not in cluster; skip create job")
        return
    ns = _namespace()
    name = f"gap-propose-worker-{_now_suffix()}"[:63]
    body = _worker_job_body(name, ns, image or running_image())
    url = f"{_API}/apis/batch/v1/namespaces/{ns}/jobs"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_auth_headers(), method="POST")
    try:
        with _open(req, 30):  # nosec B310 — in-cluster K8s API HTTPS
            pass
    except urllib.error.HTTPError as exc:
        logger.error("pipeline gap-drain k8s create job failed: %s", exc.read())
        raise


def _open(req: urllib.request.Request, timeout: int) -> Any:
    ctx = ssl.create_default_context(cafile=_SA_CA) if os.path.isfile(_SA_CA) else None
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)  # nosec B310


def running_image() -> str:
    """Image of this checker pod, so the worker runs the deployed tag."""
    explicit = os.environ.get("MAPPING_CONSOLE_IMAGE", "").strip()
    if explicit and "DEPLOY-VIA" not in explicit:
        return explicit
    if not _in_cluster():
        return explicit or "mapping-console-app"
    name = os.environ.get("HOSTNAME", "")
    url = f"{_API}/api/v1/namespaces/{_namespace()}/pods/{name}"
    req = urllib.request.Request(url, headers=_auth_headers())
    with _open(req, 15) as resp:
        pod = json.loads(resp.read().decode("utf-8"))
    containers = (pod.get("spec") or {}).get("containers") or []
    for container in containers:
        if container.get("name") == "gap-propose" and container.get("image"):
            return str(container["image"])
    if containers and containers[0].get("image"):
        return str(containers[0]["image"])
    raise RuntimeError("checker pod has no container image")


def _now_suffix() -> int:
    return int(time.time())


def cronjob_image(name: str = "gap-propose") -> str | None:
    """Image on the gap-propose CronJob, or None when it cannot be read."""
    if not _in_cluster():
        return None
    url = f"{_API}/apis/batch/v1/namespaces/{_namespace()}/cronjobs/{name}"
    req = urllib.request.Request(url, headers=_auth_headers())
    try:
        with _open(req, 15) as resp:  # nosec B310 — in-cluster K8s API HTTPS
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("pipeline gap-drain k8s cronjob image failed: %s", exc)
        return None
    return _cronjob_container_image(body)


def _cronjob_container_image(body: dict[str, Any]) -> str | None:
    spec = ((body.get("spec") or {}).get("jobTemplate") or {}).get("spec") or {}
    containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
    for container in containers:
        if container.get("name") == "gap-propose" and container.get("image"):
            return str(container["image"])
    if containers and containers[0].get("image"):
        return str(containers[0]["image"])
    return None


def hand_off_to_deployed_image() -> str | None:
    """Start a worker on the CronJob image when this pod is behind it.

    The image is returned after the successor Job exists. None keeps this
    worker looping: the tag matches, the CronJob cannot be read, or create failed.
    """
    deployed = cronjob_image()
    if not deployed or "DEPLOY-VIA" in deployed:
        return None
    try:
        current = running_image()
    except (RuntimeError, urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("pipeline gap-drain worker image unknown: %s", exc)
        return None
    if deployed == current:
        return None
    try:
        create_worker_job(deployed)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("pipeline gap-drain handoff create failed: %s", exc)
        return None
    logger.info("pipeline gap-drain worker handing off to %s", deployed)
    return deployed


def _worker_job_body(name: str, namespace: str, image: str) -> dict[str, Any]:
    env = [
        {"name": k, "value": v}
        for k, v in os.environ.items()
        if any(k.startswith(p) for p in ("MAPPING_", "GCP_", "ALERT_", "GAP_"))
    ]
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name[:63],
            "namespace": namespace,
            "labels": {"app": "gap-propose-worker"},
        },
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 86400,
            "template": {
                "metadata": {"labels": {"app": "gap-propose-worker"}},
                "spec": {
                    "serviceAccountName": "mapping-control-plane",
                    "restartPolicy": "Never",
                    "containers": [{
                        "name": "gap-propose-worker",
                        "image": image,
                        "command": [
                            "python",
                            "-m",
                            "mappers.control_plane.pipeline_gap_drain",
                            "--role",
                            "worker",
                        ],
                        "env": env,
                        "resources": {
                            "requests": {"cpu": "100m", "memory": "256Mi"},
                            "limits": {"cpu": "1", "memory": os.environ.get(
                                "GAP_PROPOSE_MEMORY_LIMIT", "2Gi",
                            )},
                        },
                    }],
                },
            },
        },
    }
