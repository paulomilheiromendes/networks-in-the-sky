"""Example Python simulation for the "Networks in the Sky" template.

Monte Carlo snapshot of an aeronautical ad-hoc network (AANET) over an ocean:
aircraft are placed uniformly at random in a square area, two ground stations
sit on the west and east coasts. Aircraft within `range_km` of each other share
an air-to-air link; aircraft within `gs_range_km` of a ground station can reach it
directly. The script reports how much of the fleet can reach the ground and how
many hops a west-to-east path needs.

Replace `simulate()` with your own model, but keep the command-line contract
used by the notebook (runner.run_py):

    python main.py --params '{"n_aircraft": 100}' --seed 3 --out /out/result.csv
"""

import argparse
import json
import random

import networkx as nx
import numpy as np
import pandas as pd


def simulate(n_aircraft=100, range_km=300.0, area_km=3000.0, gs_range_km=370.0, rng=None):
    """Return a list of result rows (dicts). One row per run here."""
    rng = rng or np.random.default_rng()
    pos = rng.uniform(0.0, area_km, size=(n_aircraft, 2))
    gs = {"GS-W": np.array([0.0, area_km / 2]), "GS-E": np.array([area_km, area_km / 2])}

    g = nx.Graph()
    g.add_nodes_from(range(n_aircraft))
    g.add_nodes_from(gs)
    # air-to-air links
    d = np.linalg.norm(pos[:, None, :] - pos[None, :, :], axis=-1)
    i, j = np.where(np.triu(d <= range_km, k=1))
    g.add_edges_from(zip(i.tolist(), j.tolist()))
    # air-to-ground links
    for name, p in gs.items():
        close = np.where(np.linalg.norm(pos - p, axis=1) <= gs_range_km)[0]
        g.add_edges_from((name, int(k)) for k in close)

    # hops from each aircraft to its nearest (in hops) ground station
    hops = {}
    for name in gs:
        for node, h in nx.single_source_shortest_path_length(g, name).items():
            if isinstance(node, int):
                hops[node] = min(h, hops.get(node, h))
    reach = np.array([hops.get(k, np.nan) for k in range(n_aircraft)], dtype=float)

    try:
        w2e_hops = nx.shortest_path_length(g, "GS-W", "GS-E")
    except nx.NetworkXNoPath:
        w2e_hops = np.nan

    return [
        {
            "frac_connected": float(np.mean(~np.isnan(reach))),
            "mean_hops_to_ground": float(np.nanmean(reach)) if np.any(~np.isnan(reach)) else np.nan,
            "max_hops_to_ground": float(np.nanmax(reach)) if np.any(~np.isnan(reach)) else np.nan,
            "west_east_hops": float(w2e_hops),
            "mean_degree": 2 * len(i) / n_aircraft,
        }
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", type=json.loads, default={}, help="JSON dict of simulate() kwargs")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True, help="output CSV path")
    a = ap.parse_args()

    random.seed(a.seed)
    rng = np.random.default_rng(a.seed)
    rows = simulate(**a.params, rng=rng)
    pd.DataFrame(rows).to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
