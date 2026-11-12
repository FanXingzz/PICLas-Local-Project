"""Compare two completed, otherwise matched, quartz-wall pulse runs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from matplotlib.colors import LogNorm

from analyze_full_pulse import E_CHARGE, plt, table


def settings(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if "=" in line and not line.lstrip().startswith("!"))


def compare(reference, returning):
    excluded = ("Part-Boundary3-NbrOfSpeciesSwaps", "Part-Boundary3-SpeciesSwaps",
                "Part-Boundary3-SurfaceModel", "Part-Species3-PartBound3-ResultSpec")
    left, right = [
        {key.strip(): value.strip() for key, value in settings(run/"parameter.ini").items()
         if not key.strip().startswith(excluded)}
        for run in (reference, returning)
    ]
    if left != right:
        raise ValueError("Case inputs differ outside the quartz wall model")
    for name in ("helium_mesh.h5", "geometry.json", "DSMC.ini"):
        hashes = [hashlib.sha256((run/name).read_bytes()).digest() for run in (reference, returning)]
        if hashes[0] != hashes[1]:
            raise ValueError(f"Comparison requires identical {name}")
    if (reference/"run-info.txt").read_text() != (returning/"run-info.txt").read_text():
        raise ValueError("Comparison requires matching MPI ranks and run mode")

    figure = plt.figure(figsize=(10, 11), layout="constrained")
    grid = figure.add_gridspec(4, 2, height_ratios=(1, 1, 1, 2.2))
    axes = [figure.add_subplot(grid[0, :])]
    axes.extend(figure.add_subplot(grid[i, :], sharex=axes[0]) for i in (1, 2))
    rows = []
    density_grids = []
    for run, label, color in ((reference, "Absorbing quartz", "#48618c"),
                              (returning, "Quartz electron return", "#b64b2e")):
        summary = json.loads((run/"pulse-summary.json").read_text(encoding="utf-8"))
        if not summary["complete"]:
            raise ValueError(f"Pulse is incomplete: {run}")
        surface = table(run/"SurfaceAnalyze.csv")
        diagnostics = np.genfromtxt(run/"pulse-diagnostics.csv", delimiter=",", names=True)
        time = surface["TIME"]
        dt = np.diff(time, prepend=0)
        incident = np.cumsum(surface["Flux-Spec-003-BC_Quartz"]*dt)
        returned = np.cumsum(surface.get("ElectricCurrentSEE-BC_Quartz", np.zeros(len(time)))*dt/E_CHARGE)
        if not np.allclose(time*1e9, diagnostics["time_ns"], rtol=0, atol=1e-10):
            raise ValueError("Comparison diagnostics do not share the surface time grid")
        initial = summary["initial_electrons_real"]
        axes[0].plot(time*1e9, diagnostics["electrons_real"]/initial, label=label, color=color)
        axes[1].plot(time*1e9, (incident-returned)/initial, label=label, color=color)
        axes[2].plot(time*1e9, diagnostics["ionization_pairs_real"]/initial, label=label, color=color)
        density = np.genfromtxt(run/"axial-density.csv", delimiter=",", names=True)
        times = np.unique(density["time_ns"])
        positions = np.unique(density["axial_center_um"])
        density_grids.append((positions, times, density["cross_section_mean_electron_density_m3"].reshape(
            len(times), len(positions))))
        rows.append({
            "wall": label, "initial_electrons": initial,
            "rise_end_electrons": summary["rise_end_electrons_real"],
            "peak_electrons": summary["max_electrons_real"], "final_electrons": summary["final_electrons_real"],
            "quartz_incident": float(incident[-1]), "quartz_returned": float(returned[-1]),
            "quartz_net_loss": float(incident[-1]-returned[-1]),
            "gas_ionization_pairs": summary["ionization_pairs_created_real"],
            "first_zero_ns": summary["first_electron_zero_ns"],
            "last_extinction_ns": summary["electron_extinction_time_ns"],
            "breakdown_assessment": summary["assessment"], "run": str(run.resolve()),
        })
    bore = summary["geometry"]["tube_bore_um"]
    axes[0].set_ylabel("Electron population\nper initial electron")
    axes[0].set_yscale("symlog", linthresh=.001)
    axes[0].legend()
    axes[1].set_ylabel("Net wall loss\nper initial electron")
    axes[2].set_ylabel("Gas ionization pairs\nper initial electron")
    axes[2].set_xlabel("Time (ns)")
    for axis in axes[:2]:
        axis.tick_params(labelbottom=False)
    for axis in axes:
        axis.axvline(2, color="#777777", alpha=.6, linestyle=":")
        axis.axvline(7, color="#777777", alpha=.6, linestyle=":")
        axis.grid(alpha=.2)
    max_density = max(float(values.max()) for _, _, values in density_grids)
    norm = LogNorm(max_density/1e3, max_density)
    colors = plt.colormaps["turbo"].with_extremes(under="#edf2f8", bad="white")
    left_density = figure.add_subplot(grid[3, 0])
    right_density = figure.add_subplot(grid[3, 1], sharey=left_density)
    for axis, row, (positions, times, values) in zip((left_density, right_density), rows, density_grids):
        mesh = axis.pcolormesh(positions, times, np.ma.masked_less_equal(values, 0),
                               shading="nearest", cmap=colors, norm=norm)
        axis.set(title=row["wall"], xlabel="Axial position (μm)", ylim=(times[0], times[-1]))
        for phase in (2, 7):
            axis.axhline(phase, color="#777777", linewidth=.7, linestyle=":")
    left_density.set_ylabel("Time (ns)")
    right_density.tick_params(labelleft=False)
    figure.colorbar(mesh, ax=[left_density, right_density], extend="min",
                    label="Cross-section mean electron density (m⁻³)")
    figure.suptitle(f"{bore:g} μm helium capillary · +1500 V · 2/5/2 ns")
    figure.savefig(returning/"quartz-wall-comparison.png", dpi=170)
    plt.close(figure)
    with (returning/"quartz-wall-comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("returning", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.reference, args.returning), ensure_ascii=False, indent=2))
