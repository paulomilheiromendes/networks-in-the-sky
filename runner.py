"""Run experiments from the notebook and cache their results.

Three kinds of jobs:
  run_ns3(...)     an ns-3 program, inside the ns-3 Docker image
  run_py(...)      a Python simulation script, inside the Python Docker image
  run_nixnet(...)  a NixNet experiment defined in flake.nix, via `nix run`

Every ns-3 / Python job is fully described by (program, params, seed) and is
cached in results/<kind>/<key>.csv, with a <key>.json sidecar recording how it
was produced. A job only runs if its CSV is missing; the key also covers the
simulation source code, the Docker image and the engine, so changing any of
them triggers a re-run instead of silently reusing stale results.

ENGINE=docker (default) is what you must use for the results you submit.
ENGINE=local runs the same jobs without Docker; use it only for debugging.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

ENGINE = os.environ.get("ENGINE", "docker")  # "docker" | "local"
NS3_IMAGE = os.environ.get("NS3_IMAGE", "sky-ns3:3.42")
PY_IMAGE = os.environ.get("PY_IMAGE", "sky-py:1.0")
NS3_LOCAL_DIR = Path(os.environ.get("NS3_DIR", "~/ns-3.42")).expanduser()  # ENGINE=local only
TIMEOUT_S = int(os.environ.get("JOB_TIMEOUT_S", 6 * 3600))


# ---------------------------------------------------------------- helpers ---

def grid(**axes) -> list[dict]:
    """grid(a=[1, 2], b=[3]) -> [{'a': 1, 'b': 3}, {'a': 2, 'b': 3}]"""
    keys = list(axes)
    return [dict(zip(keys, values)) for values in product(*axes.values())]


def _tree_hash(path: Path) -> str:
    """Hash of all files below `path` (so code changes invalidate the cache)."""
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        h.update(str(f.relative_to(path)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


@functools.lru_cache(maxsize=None)
def _image_id(image: str) -> str:
    r = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Docker image '{image}' not found. Build it first (see README: make images).")
    return r.stdout.strip()


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S)
    if r.returncode != 0:
        raise RuntimeError(
            f"Command failed (exit {r.returncode}):\n  {' '.join(cmd)}\n"
            f"--- stderr (tail) ---\n{r.stderr[-3000:]}\n--- stdout (tail) ---\n{r.stdout[-1000:]}"
        )


def _user_flag() -> list[str]:
    # Files written to the mounted results folder belong to you, not root (Linux/macOS).
    return ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []


def _cached_job(kind: str, ident: dict, produce) -> pd.DataFrame:
    """Return the cached CSV for `ident`, producing it with produce(out_path) if missing."""
    key = hashlib.sha1(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:12]
    out = RESULTS / kind / f"{key}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        t0 = time.time()
        tmp = out.with_suffix(".partial.csv")
        produce(tmp)
        tmp.rename(out)  # only complete results enter the cache
        meta = {**ident, "runtime_s": round(time.time() - t0, 2),
                "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return pd.read_csv(out)


# -------------------------------------------------------------------- ns-3 ---

def run_ns3(params: dict, seed: int = 1, program: str = "aanet") -> pd.DataFrame:
    """Run one ns-3 program with `--key=value` arguments and `--RngRun=seed`.

    The program must accept `--outFile=<path>` and write its results there as CSV.
    """
    ident = {"kind": "ns3", "program": program, "params": params, "seed": seed,
             "engine": ENGINE, "code": _tree_hash(ROOT / "ns3")}
    if ENGINE == "docker":
        ident["image"] = _image_id(NS3_IMAGE)
    args = [f"--{k}={v}" for k, v in params.items()] + [f"--RngRun={seed}"]

    def produce(out: Path):
        if ENGINE == "docker":
            _run(["docker", "run", "--rm", *_user_flag(),
                  "-v", f"{out.parent.resolve()}:/out",
                  NS3_IMAGE, program, *args, f"--outFile=/out/{out.name}"])
        else:
            # e.g. build/scratch/aanet/ns3.42-aanet (release) or ...-aanet-default (default profile)
            pattern = re.compile(rf"ns3\.[\d.]+-{re.escape(program)}(-(default|debug|optimized))?")
            matches = sorted(p for p in NS3_LOCAL_DIR.glob("build/scratch/**/ns3.*")
                             if pattern.fullmatch(p.name))
            if not matches:
                raise RuntimeError(f"No built ns-3 program '{program}' under {NS3_LOCAL_DIR}/build/scratch. "
                                   f"Copy ns3/{program} into its scratch/ folder and run ./ns3 build.")
            _run([str(matches[0]), *args, f"--outFile={out.resolve()}"])

    return _cached_job("ns3", ident, produce)


# ------------------------------------------------------------------ Python ---

def run_py(params: dict, seed: int = 0, script: str = "main.py") -> pd.DataFrame:
    """Run one Python simulation script from sim/ as
    `python <script> --params '<json>' --seed <seed> --out <csv>`."""
    ident = {"kind": "py", "script": script, "params": params, "seed": seed,
             "engine": ENGINE, "code": _tree_hash(ROOT / "sim")}
    if ENGINE == "docker":
        ident["image"] = _image_id(PY_IMAGE)
    args = ["--params", json.dumps(params), "--seed", str(seed)]

    def produce(out: Path):
        if ENGINE == "docker":
            _run(["docker", "run", "--rm", *_user_flag(),
                  "-v", f"{(ROOT / 'sim').resolve()}:/code:ro",
                  "-v", f"{out.parent.resolve()}:/out", "-w", "/code",
                  "-e", "MPLBACKEND=Agg", "-e", "MPLCONFIGDIR=/tmp", "-e", "PYTHONHASHSEED=0",
                  PY_IMAGE, "python", script, *args, "--out", f"/out/{out.name}"])
        else:
            env = {**os.environ, "MPLBACKEND": "Agg", "PYTHONHASHSEED": "0"}
            r = subprocess.run([sys.executable, script, *args, "--out", str(out.resolve())],
                               cwd=ROOT / "sim", env=env, capture_output=True, text=True,
                               timeout=TIMEOUT_S)
            if r.returncode != 0:
                raise RuntimeError(f"{script} failed:\n{r.stderr[-3000:]}")

    return _cached_job("py", ident, produce)


# ------------------------------------------------------------------- sweeps ---

def _job(func, params, seed, kwargs):
    return func(params, seed, **kwargs).assign(**params, seed=seed)


def sweep(func, configs: list[dict], seeds, workers: int | None = None, **kwargs) -> pd.DataFrame:
    """Run func(params, seed) for every config x seed in parallel and stack the results.

    Each row of the returned DataFrame carries its parameters and seed as columns.
    Cached jobs return immediately, so re-running a notebook cell is cheap.
    """
    jobs = [(p, s) for p in configs for s in seeds]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_job, func, p, s, kwargs) for p, s in jobs]
        frames = [f.result() for f in futures]
    return pd.concat(frames, ignore_index=True)


# ------------------------------------------------------------------- NixNet ---

def run_nixnet(experiment: str, runs: str = "1-3") -> list[Path]:
    """Run a NixNet experiment from flake.nix (`nix run .#<experiment> <runs>`).

    The flake writes each run to results/nixnet/<experiment>/<run>/. Runs whose
    folder already exists are treated as cached; delete the folder to re-run.
    Returns the run folders.
    """
    base = RESULTS / "nixnet" / experiment
    lo, _, hi = runs.partition("-")
    wanted = [base / f"{k:02d}" for k in range(int(lo), int(hi or lo) + 1)]
    missing = [d for d in wanted if not d.exists()]
    if missing:
        if shutil.which("nix") is None:
            raise RuntimeError("`nix` not found. The NixNet track needs Nix (see README).")
        for d in missing:  # one call per missing run keeps existing runs untouched
            _run(["nix", "--extra-experimental-features", "nix-command flakes",
                  "run", f".#{experiment}", d.name.lstrip("0") or "0"], cwd=ROOT)
    return wanted


def read_ping(path: Path) -> dict:
    """Parse the summary of `ping` output: rtt min/avg/max/mdev in ms and loss in %."""
    text = Path(path).read_text()
    out = {}
    for line in text.splitlines():
        if "packet loss" in line:
            out["loss_pct"] = float(line.split("%")[0].split()[-1])
        if line.startswith(("rtt", "round-trip")):
            vals = line.split("=")[1].split()[0].split("/")
            out.update(dict(zip(["rtt_min_ms", "rtt_avg_ms", "rtt_max_ms", "rtt_mdev_ms"], map(float, vals))))
    return out


def read_iperf3(path: Path) -> dict:
    """Parse `iperf3 -J` output: received throughput (Mbit/s) and retransmissions."""
    end = json.loads(Path(path).read_text())["end"]
    return {"throughput_mbps": end["sum_received"]["bits_per_second"] / 1e6,
            "retransmits": end["sum_sent"].get("retransmits")}


# -------------------------------------------------------------- provenance ---

def environment_info() -> dict:
    """Versions and identifiers to report with your results."""
    def cmd(*c):
        try:
            r = subprocess.run(c, capture_output=True, text=True, cwd=ROOT, timeout=30)
            return r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    info = {
        "engine": ENGINE,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_commit": cmd("git", "rev-parse", "--short", "HEAD"),
        "git_dirty": bool(cmd("git", "status", "--porcelain")),
        "nix": cmd("nix", "--version"),
        "docker": cmd("docker", "--version"),
    }
    if ENGINE == "docker":
        for name, image in [("ns3_image", NS3_IMAGE), ("py_image", PY_IMAGE)]:
            info[name] = f"{image} {cmd('docker', 'image', 'inspect', '--format', '{{.Id}}', image)}"
    return info
