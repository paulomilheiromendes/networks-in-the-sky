# Networks in the Sky: experiment template

Template for the TUM master seminar *Networks in the Sky*. You reproduce (and extend) the results of a paper and report everything in one Jupyter notebook that anyone can re-run.

Jupyter always runs on your machine. The experiments run in a pinned environment:

| Track | Experiments | Environment | Jupyter started with |
|---|---|---|---|
| **Docker** | ns-3 and/or Python simulations | one Docker container per job | `.venv` from `requirements.txt` |
| **NixNet** | emulated networks (Linux namespaces) | Nix flake (`flake.nix` + `flake.lock`) | `nix develop -c jupyter lab` |

Pick one track, delete the example parts you do not use, and replace the examples with your own experiment.

## What is in here

```
notebook.ipynb          your report: runs the experiments, analyses the results, discusses them
runner.py               runs jobs (Docker / Nix), caches results, records how they were produced
requirements.txt        Jupyter + analysis packages for the host (Docker track), pinned
docker/
  ns3.Dockerfile        ns-3 3.42 image with your scenarios from ns3/
  py.Dockerfile         Python image for your simulation in sim/
  requirements-sim.txt  packages inside the Python image, pinned
ns3/aanet/aanet.cc      example ns-3 scenario (aircraft network snapshot)
sim/main.py             example Python simulation (fleet connectivity Monte Carlo)
flake.nix               NixNet track: example experiment + Jupyter environment
results/                cached raw results (commit them!)
figures/                figures saved by the notebook
Makefile                shortcuts for the commands below
```

## Docker track: setup

Requirements: Docker (Docker Desktop on macOS/Windows), Python 3.11-3.13, Git. `make` is optional; the plain commands are given too.

```bash
# 1. Build the simulation images once (ns-3: 20-40 min the first time)
docker build -t sky-ns3:3.42 -f docker/ns3.Dockerfile .      # make ns3-image
docker build -t sky-py:1.0   -f docker/py.Dockerfile .       # make py-image

# 2. Jupyter environment on your machine
python3 -m venv .venv                                        # make venv
.venv/bin/pip install -r requirements.txt                    # (Windows: .venv\Scripts\pip)

# 3. Start Jupyter and open notebook.ipynb
.venv/bin/jupyter lab                                        # make lab
```

When to rebuild:
- **ns-3 image:** after changing anything in `ns3/` (fast, only your programs recompile) or the ns-3 modules (slow).
- **Python image:** only after changing `docker/requirements-sim.txt`. Your code in `sim/` is mounted into the container, so code changes need no rebuild.

## NixNet track: setup

Requirements: Linux with namespace support (native, WSL2, or a Linux VM), [Nix](https://nixos.org/download/) with `flakes` and `nix-command` enabled, Git. On Ubuntu you may need:

```bash
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
```

Then:

```bash
nix develop -c jupyter lab          # make nix-lab  (first run downloads everything: 5-15 min)
```

Run a single experiment by hand (useful while editing `flake.nix`):

```bash
nix run .#relay-d5-l1 1             # run 01 -> results/nixnet/relay-d5-l1/01/
nix build .#mermaid-svg             # topology diagram in ./result
```

Do not use NixNet features that need `sudo` (eBPF/XDP) from the notebook. If your experiment needs them, run that step in a terminal and let the notebook analyse its output.

## How experiments run

All experiments go through `runner.py`:

```python
configs = grid(numNodes=[50, 100], commRange=[200_000, 300_000])   # parameter grid
df = sweep(run_ns3, configs, seeds=range(1, 6))                      # parallel, cached
```

- **One job = (program, parameters, seed).** The seed controls all randomness (ns-3: `--RngRun`; Python: `--seed`). Use several seeds and report confidence intervals.
- **Caching:** each job's result is stored in `results/<kind>/<key>.csv` with a `<key>.json` describing how it was produced. A job only runs if its result is missing. The key includes the parameters, the seed, a hash of your simulation code and the Docker image ID, so changing any of them re-runs the job instead of reusing old results.
- **`ENGINE`:** `docker` (default) is required for submitted results. `ENGINE=local` runs the same jobs without Docker for quick debugging (ns-3 then needs a local build; set `NS3_DIR`).
- **NixNet:** `run_nixnet("relay-d5-l1", runs="1-3")` runs missing runs only. Delete a run folder to repeat it.

## Adapting the template

**ns-3 scenario** (`ns3/<name>/*.cc`, one folder per program)
- Accept your parameters with `CommandLine::AddValue`, and always `--outFile` (write a CSV there). `--RngRun` is handled by ns-3.
- Add the modules you need to `NS3_MODULES` in `docker/ns3.Dockerfile` (for example `wifi;mobility;spectrum`). ns-3.42 includes the 3GPP TR 38.811 non-terrestrial (NTN) channel models in `propagation`/`spectrum`.
- Call it with `run_ns3(params, seed, program="<name>")`.

**Python simulation** (`sim/`)
- Keep the command-line contract of `sim/main.py`: `--params '<json>' --seed <int> --out <csv>`.
- For third-party code you cannot change, write a small wrapper script with this contract that calls it.
- Add packages to `docker/requirements-sim.txt` with exact versions (`==`), then rebuild the image with a new tag (`sky-py:1.1`) and set `PY_IMAGE` accordingly.

**NixNet experiment** (`flake.nix`)
- Edit `mkRelay` (nodes, links, `netem`, measurement scripts) and the parameter grid. Each grid point becomes `nix run .#<name>`.
- Keep `workDir = "results/nixnet/${name}/{run}"` so the notebook finds the results.
- Option reference: [NixNet options](https://github.com/birneee/nixnet/wiki/nixnet-options-docs-latest), more examples: [NixNet examples](https://github.com/birneee/nixnet/tree/main/examples).

## What to submit

The Git repository (or a zip of it) containing:

1. `notebook.ipynb`, executed, with all outputs and figures.
2. Your simulation or experiment code (`ns3/`, `sim/`, or `flake.nix`).
3. `results/` with all raw results and their `.json` files, and `figures/`.
4. The environment files: `docker/*` + `requirements.txt` (Docker track) or `flake.nix` + **`flake.lock`** (NixNet track).
5. This README, updated: what you ran, expected run time, and the hardware you used.

**Final check:** commit everything, then run `make check` (Docker track) or `make check TRACK=nixnet`. It clones the last commit into `.check/` and runs the notebook from top to bottom. If it works there, your submission is reproducible.

## Troubleshooting

- **`Docker image 'sky-ns3:3.42' not found`**: build the images first (see setup).
- **`Command failed ...`**: the error shows the exact command and the program's error output; run that command in a terminal to debug.
- **Slow first run of a sweep**: expected; later runs reuse `results/`. Use `ENGINE=local` with few seeds while developing.
- **NixNet fails on Ubuntu**: see the AppArmor setting above and the [NixNet FAQ](https://github.com/birneee/nixnet/blob/main/FAQ.md).
