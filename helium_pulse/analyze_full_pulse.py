"""Audit a completed axisymmetric pulse and export measured diagnostics/plots."""
import argparse
from array import array
import csv
import json
from pathlib import Path

import h5py
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import numpy as np

from slice_plot import render_slice
from piclas_ini import parse_parameters, real

E_CHARGE = 1.602176634e-19


def table(path, names_needed=None):
    with path.open(newline="") as stream:
        reader = csv.reader(stream)
        names = [name.split("-", 1)[1] for name in next(reader)]
        columns = [(index, name) for index, name in enumerate(names)
                   if names_needed is None or name in names_needed]
        values = {name: array("d") for _, name in columns}
        for row in reader:
            if len(row) == len(names):
                for index, name in columns:
                    values[name].append(float(row[index]))
    return {name: np.frombuffer(series, dtype=np.float64) for name, series in values.items()}


def reaction_counts(run):
    files = sorted(run.glob("JiaReactionCounts_rank*.csv"))
    if not files:
        return None
    rank_counts = [np.loadtxt(path, delimiter=",", ndmin=2) for path in files]
    time = rank_counts[0][:, 0]
    for counts in rank_counts:
        if (counts.shape != (len(time), 25) or not np.isfinite(counts).all()
                or not np.array_equal(counts[:, 0], time) or np.any(np.diff(counts[:, 1:], axis=0) < 0.)):
            raise ValueError("Inconsistent cumulative Jia chemistry diagnostics")
    rows = np.stack(rank_counts)
    return time, rows[:, :, 1:24].sum(axis=0), rows[:, :, 24].max(axis=0)


def rotational_volumes(mesh):
    # 2*pi*integral(r dA), using the exact polygon first moment in the x-r plane.
    with h5py.File(mesh) as source:
        points = source["NodeCoords"][:].reshape(-1, 8, 3)[:, [0, 1, 3, 2], :2]
    following = np.roll(points, -1, axis=1)
    cross = points[:, :, 0]*following[:, :, 1] - following[:, :, 0]*points[:, :, 1]
    return np.pi/3*np.abs(np.sum((points[:, :, 1]+following[:, :, 1])*cross, axis=1))


def axisymmetric_gauss_weights(mesh):
    """Integrate a first-order DG field over x-r cells rotated about the axis."""
    with h5py.File(mesh) as source:
        xy = source["NodeCoords"][:].reshape(-1, 8, 3)[:, [0, 1, 3, 2], :2]
    nodes = (1+np.array([-1, 1])/np.sqrt(3))/2
    weights = []
    for r in nodes:
        for x in nodes:
            shape = np.array([(1-x)*(1-r), x*(1-r), x*r, (1-x)*r])
            dx = np.array([r-1, 1-r, r, -r])
            dr = np.array([x-1, -x, x, 1-x])
            jacobian = np.linalg.det(np.stack([dx@xy, dr@xy], axis=-1))
            weights.append(np.pi/2*(shape@xy)[:, 1]*np.abs(jacobian))
    return np.stack(weights, axis=1)


def validate_axisymmetric_particles(particles, geometry, frame_name):
    x, y, z = particles[:, :3].T
    radius = np.hypot(y, z)
    tolerance = 1e-9  # Allow roundoff at surfaces, not a particle outside the gas bore.
    outside = ((abs(x) > geometry["domain_length_um"]*0.5e-6+tolerance)
               | (radius > geometry["tube_bore_um"]*0.5e-6+tolerance))
    if not np.isfinite(particles).all() or np.any(outside):
        raise ValueError(f"Non-finite or out-of-domain particles in {frame_name} ({outside.sum()} outside)")
    if np.any(np.linalg.norm(particles[:, 3:6], axis=1) >= 299792458.):
        raise ValueError(f"Non-physical particle speed in {frame_name}")


def analyze(run, allow_partial=False, assessment=None):
    if not allow_partial and (run/"run-status.txt").read_text().strip() != "complete":
        raise ValueError("Run must finish solving before final analysis")
    geometry = json.loads((run/"geometry.json").read_text())
    info_file = run/"case-info.json"
    case_info = json.loads(info_file.read_text(encoding="utf-8")) if info_file.is_file() else {}
    inputs = parse_parameters((run/"parameter.ini").read_text(encoding="utf-8-sig"))
    parameter = {key: real(inputs[key]) for key in
                 ("PulsePeak", "PulseRise", "PulseFlat", "PulseFall", "tend", "ManualTimeStep")}
    if geometry["mesh_method"] != "axisymmetric":
        raise ValueError("This analysis requires an axisymmetric x-r mesh")
    boundaries = ("HV", "Ground", "Quartz")
    part = table(run/"PartAnalyze.csv", {"TIME", "nPart-Spec-003",
                                        *(f"NumDens-Spec-{s:03d}" for s in (2, 3, 4))})
    surface = table(run/"SurfaceAnalyze.csv", {
        "TIME", *(f"Flux-Spec-{s:03d}-BC_{b}" for s in (2, 3, 4) for b in boundaries),
        *(f"{column}-BC_{b}" for column in ("ElectricCurrentSEE", "TotalElectricCurrent") for b in boundaries),
    })
    field = table(run/"FieldAnalyze.csv", {"time", "BFO-boundary-001-bc_hv",
                                          "ElecDisplCurrent-001-bc_hv", "ElecDisplCurrent-002-bc_ground"})
    n = min(len(part["TIME"]), len(surface["TIME"]), len(field["time"]))
    t = part["TIME"][:n]
    for other in (surface["TIME"][:n], field["time"][:n]):
        if not np.allclose(t, other, rtol=0, atol=1e-20):
            raise ValueError("Diagnostic time grids differ; do not interpolate impulsive particle fluxes")
    dt = np.diff(t, prepend=t[0])
    expected_voltage = parameter["PulsePeak"]*np.maximum(0, np.minimum.reduce([
        np.ones_like(t), t/parameter["PulseRise"],
        (parameter["PulseRise"]+parameter["PulseFlat"]+parameter["PulseFall"]-t)/parameter["PulseFall"]]))
    voltage_error = float(np.max(np.abs(field["BFO-boundary-001-bc_hv"][:n]-expected_voltage)))
    if voltage_error > 1e-6:
        raise ValueError(f"Applied voltage differs from saved pulse parameters: {voltage_error} V")
    if not allow_partial and abs(t[-1]-parameter["tend"]) > 1e-20:
        raise ValueError("Simulation did not reach the requested final time")
    volumes = rotational_volumes(run/"helium_mesh.h5")
    volume = volumes.sum()
    ne = part["NumDens-Spec-003"][:n]*volume
    molecular = "NumDens-Spec-004" in part
    ion_species = (2, 4) if molecular else (2,)
    ni = sum(part[f"NumDens-Spec-{species:03d}"][:n]*volume for species in ion_species)
    ion_flux = {boundary: sum(surface[f"Flux-Spec-{species:03d}-BC_{boundary}"][:n]
                             for species in ion_species) for boundary in ("HV", "Ground", "Quartz")}
    loss_e = sum(surface[f"Flux-Spec-003-BC_{boundary}"][:n]*dt
                 for boundary in ("HV", "Ground", "Quartz"))
    loss_i = sum(ion_flux.values())*dt
    emission = {boundary: surface.get(f"ElectricCurrentSEE-BC_{boundary}", np.zeros(n))[:n]
                for boundary in ("HV", "Ground", "Quartz")}
    emitted = np.cumsum(sum(emission.values())*dt/E_CHARGE)
    wall_impacts = np.cumsum(surface["Flux-Spec-003-BC_Quartz"][:n]*dt)
    wall_returns = np.cumsum(emission["Quartz"]*dt/E_CHARGE)
    wall_ions = np.cumsum(ion_flux["Quartz"]*dt)
    wall_charge = E_CHARGE*(wall_ions-wall_impacts+wall_returns)
    birth_e = ne-ne[0]+np.cumsum(loss_e)-emitted
    birth_i = ni-ni[0]+np.cumsum(loss_i)
    currents = {}
    for boundary, field_boundary in (("HV", "001-bc_hv"), ("Ground", "002-bc_ground")):
        total = surface[f"TotalElectricCurrent-BC_{boundary}"][:n]
        displacement = field[f"ElecDisplCurrent-{field_boundary}"][:n]
        particle = E_CHARGE*(ion_flux[boundary]
                             -surface[f"Flux-Spec-003-BC_{boundary}"][:n])+emission[boundary]
        if not np.allclose(total-displacement, particle, atol=1e-14, rtol=1e-7):
            raise ValueError("Particle-flux and total-minus-displacement currents disagree")
        currents[boundary] = (total, displacement, particle)
    balance = float(np.max(np.abs(birth_e-birth_i)))
    if balance > 1e-5 + max(ne[0], ni[0], birth_i[-1], emitted[-1])*1e-7:
        raise ValueError(f"Electron/ion balance after subtracting SEE differs by {balance:.6g} particles")
    chemistry = reaction_counts(run)
    if chemistry is not None:
        chemistry_time, counts, max_hazard = chemistry
        ionization = counts[:, np.array((3, 4, 5, 17, 18, 19, 20, 21, 22))-1].sum(axis=1)
        recombination = counts[:, 7:15].sum(axis=1)
        indices = np.searchsorted(t, chemistry_time)
        indices = np.clip(indices, 1, len(t)-1)
        indices -= (abs(t[indices-1]-chemistry_time) < abs(t[indices]-chemistry_time))
        if np.max(abs(t[indices]-chemistry_time)) > 1e-20:
            raise ValueError("Jia chemistry and particle diagnostics are on different time grids")
        chemistry_balance = float(np.max(abs(ionization-recombination-birth_i[indices])))
        if chemistry_balance > 1e-5 + max(ni[0], ionization[-1], recombination[-1])*1e-7:
            raise ValueError(f"Jia ionization/recombination and total ion balance differ by {chemistry_balance:.6g} particles")
    frames = sorted(run.glob("helium_pulse_State_*.h5"), key=lambda p: float(p.stem.rsplit("_", 1)[1]))
    half_gap_m = geometry["tip_gap_um"]*0.5e-6
    axial_edges = np.linspace(-half_gap_m, half_gap_m, 51)
    axial_centers = (axial_edges[:-1]+axial_edges[1:])/2
    bin_volume = np.pi*(geometry["tube_bore_um"]*0.5e-6)**2*np.diff(axial_edges)
    axial_density = []
    snapshots = []
    charge_weights = axisymmetric_gauss_weights(run/"helium_mesh.h5") if case_info.get("quartz_wall_model") else None
    charge_errors = []
    for path in frames:
        with h5py.File(path) as state:
            names = list(state.attrs["VarNamesAdd"].astype(str))
            density = state["ElemData"][:, names.index("ElectronDensityCell")]
            particles = state["PartData"][:]
            validate_axisymmetric_particles(particles, geometry, path.name)
            electron = particles[:, 6] == 3
            weights = particles[electron, -1]
            if not np.isclose(density@volumes, weights.sum(), atol=1e-7, rtol=1e-8):
                raise ValueError(f"Density integral and electron weights disagree: {path.name}")
            axial_density.append(np.histogram(particles[electron, 0], bins=axial_edges,
                                              weights=weights)[0]/bin_volume)
            valid = state["ElemData"][:, names.index("PICValidPlasmaCell")] > 0
            ppdx = state["ElemData"][:, names.index("PPDCellDirX")][valid]
            ppdr = state["ElemData"][:, names.index("PPDCellDirY")][valid]
            timestep = state["ElemData"][:, names.index("PICTimeStepCell")]
            state_time = float(state.attrs["Time"][0])
            snapshots.append({"time_ns": state_time*1e9,
                              "electron_macroparticles": int(electron.sum()),
                              "electron_real_number": float(weights.sum()),
                              "density_max_m3": float(density.max()),
                              "density_integral_real_number": float(density@volumes),
                              "electron_x_min_um": float(particles[electron, 0].min()*1e6) if electron.any() else None,
                              "electron_x_max_um": float(particles[electron, 0].max()*1e6) if electron.any() else None,
                              "quasi_neutral_pic_cells": int(valid.sum()),
                              "axial_ppd_min": float(ppdx.min()) if len(ppdx) else None,
                              "radial_ppd_min": float(ppdr.min()) if len(ppdr) else None,
                              "plasma_step_limit_min_ps": float(timestep[timestep > 0].min()*1e12)
                              if np.any(timestep > 0) else None})
            if charge_weights is not None:
                source_charge = float(np.sum(state["DG_SourceExt"][:].reshape(-1, 2, 4).mean(1)*charge_weights))
                time_index = int(np.argmin(abs(t-state_time)))
                if abs(t[time_index]-state_time) < 1e-20:
                    charge_errors.append(abs(source_charge-wall_charge[time_index]))
                    snapshots[-1]["quartz_deposited_charge_C"] = source_charge
    max_density = max(item["density_max_m3"] for item in snapshots)
    axial_density = np.asarray(axial_density)
    seed_density = case_info.get("seed_density_m3")
    density_lower = min(max_density/1e4, seed_density/10) if seed_density else max_density/1e4
    nonzero = np.flatnonzero(ne > 1e-8)
    extinct = float(t[nonzero[-1]+1]*1e9) if len(nonzero) and nonzero[-1]+1 < len(t) else None
    zeros = np.flatnonzero((t > 0) & (ne <= 1e-8))
    first_zero = float(t[zeros[0]]*1e9) if len(zeros) and ne[0] > 0 else None
    rise_end = int(np.argmin(np.abs(t-parameter["PulseRise"])))
    rise_covered = t[-1] >= parameter["PulseRise"]-1e-20
    peak_idx = int(np.argmax(ne))
    summary = {
        "run": str(run.resolve()), "geometry": geometry, "complete": not allow_partial,
        "case_info": case_info,
        "pulse_parameters": parameter, "voltage_max_abs_error_V": voltage_error,
        "diagnostic_steps": n-1, "mesh_cells": len(volumes),
        "end_time_ns": float(t[-1]*1e9), "initial_electrons_real": float(ne[0]),
        "max_electrons_real": float(ne.max()), "final_electrons_real": float(ne[-1]),
        "electron_peak_time_ns": float(t[peak_idx]*1e9),
        "rise_end_electrons_real": float(ne[rise_end]) if rise_covered else None,
        "rise_end_electron_macroparticles": int(round(part["nPart-Spec-003"][rise_end])) if rise_covered else None,
        "rise_end_electron_fraction": float(ne[rise_end]/ne[0]) if rise_covered and ne[0] > 0 else None,
        "minimum_electrons_during_rise_real": float(ne[:rise_end+1].min()),
        "initial_ions_real": float(ni[0]), "final_ions_real": float(ni[-1]),
        "ionization_pairs_created_real": float(ionization[-1] if chemistry is not None else birth_i[-1]),
        "electron_extinction_time_ns": extinct,
        "first_electron_zero_ns": first_zero,
        "density_max_m3": max_density, "density_scale_min_m3": density_lower, "stored_frames": len(frames),
        "secondary_electrons_emitted_real": {b: float(np.sum(values*dt)/E_CHARGE)
                                             for b, values in emission.items()},
        "quartz_electron_impacts_real": float(wall_impacts[-1]),
        "quartz_electron_returns_real": float(wall_returns[-1]),
        "quartz_net_electron_loss_real": float(wall_impacts[-1]-wall_returns[-1]),
        "quartz_deposited_charge_C": float(wall_charge[-1]),
        "quartz_charge_integration_max_error_C": max(charge_errors) if charge_errors else None,
        "max_particle_balance_error_real": balance,
        "axial_mean_density_max_m3": float(axial_density.max()),
        "max_axial_bin_fraction_above_10x_seed": float(np.mean(axial_density >= 10*seed_density, axis=1).max())
        if seed_density else None,
        "electron_losses_real": {b: float(np.sum(surface[f"Flux-Spec-003-BC_{b}"][:n]*dt))
                                  for b in ("HV", "Ground", "Quartz")},
        "ion_losses_real": {b: float(np.sum(ion_flux[b]*dt))
                             for b in ("HV", "Ground", "Quartz")},
        "particle_current_peak_abs_A": {b: float(np.max(np.abs(c[2]))) for b, c in currents.items()},
        "snapshots": snapshots,
        "assessment": assessment or ("本次条件未观察到击穿" if extinct is not None and ne.max() <= ne[0]*(1+1e-8)
                                     else "需结合电子通道与电流进一步判断"),
        "limitations": case_info.get("limitations") or ["当前较粗网格、单次随机种子结果，尚非击穿电压或等离子体收敛结果。",
                        f"初始{snapshots[0]['electron_macroparticles']}个电子宏粒子；本算例未启用持续预电离、二次电子发射、亚稳态逐级电离或杂质化学。",
                        "密度输出间隔0.25 ns；电流尖峰是离散宏粒子撞击，应结合时间积分与位移电流判断。"]}
    if chemistry is not None:
        summary["recombination_pairs_lost_real"] = float(recombination[-1])
        summary["net_ionization_pairs_real"] = float(birth_i[-1])
        summary["chemistry_particle_balance_error_real"] = chemistry_balance
        summary["max_pair_reaction_hazard"] = float(max_hazard[-1])
        summary["weighted_reaction_events"] = {f"R{i}": float(value) for i, value in enumerate(counts[-1], 1)}
        with (run/"reaction-diagnostics.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_ns", *(f"R{i}_events_real" for i in range(1, 24)), "max_pair_hazard"])
            writer.writerows(zip(chemistry_time*1e9, *counts.T, max_hazard))
    if molecular:
        summary["final_He2_ions_real"] = float(part["NumDens-Spec-004"][n-1]*volume)
        summary["converted_He_ions_real"] = (float(counts[-1, 15]) if chemistry is not None else
            summary["final_He2_ions_real"] - part["NumDens-Spec-004"][0]*volume
            + sum(float(surface[f"Flux-Spec-004-BC_{b}"][:n]@dt) for b in ion_flux))
    (run/"pulse-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (run/"pulse-summary.txt").write_text(
        f'{summary["assessment"]}\n'
        f'二维轴对称氦气石英管针针，内径{geometry["tube_bore_um"]:g} μm，'
        f'针尖半径{geometry["tip_radius_um"]:g} μm，针尖间距{geometry["tip_gap_um"]:g} μm。\n'
        f'脉冲峰值 +{parameter["PulsePeak"]:g} V，上升{parameter["PulseRise"]*1e9:g} ns、'
        f'平顶{parameter["PulseFlat"]*1e9:g} ns、下降{parameter["PulseFall"]*1e9:g} ns；'
        f'计算到 {t[-1]*1e9:.9g} ns，{len(frames)} 帧。\n'
        f'电子实际粒子数：初始{ne[0]:.6g}，最大{ne.max():.6g}，结束{ne[-1]:.6g}。\n'
        f'累计电离新增电子-离子对 {summary["ionization_pairs_created_real"]:.6g}。\n'
        + (f'累计复合损失电子-离子对 {summary["recombination_pairs_lost_real"]:.6g}。\n' if chemistry is not None else '')
        +
        f'电极离子诱导发射电子数：高压针 {summary["secondary_electrons_emitted_real"]["HV"]:.6g}，'
        f'接地针 {summary["secondary_electrons_emitted_real"]["Ground"]:.6g}。\n'
        f'石英壁电子入射 {wall_impacts[-1]:.6g}，返回 {wall_returns[-1]:.6g}，'
        f'净损失 {wall_impacts[-1]-wall_returns[-1]:.6g}（按粒子权重折算）。\n'
        + (f'上升沿结束电子数 {ne[rise_end]:.6g}，'
           f'{summary["rise_end_electron_macroparticles"]} 个宏粒子。\n' if rise_covered else '')
        + (f'电子首次降至零的时刻 {first_zero:.6g} ns。\n' if first_zero is not None else '')
        + (f'最后一次电子耗尽时刻 {extinct:.6g} ns。\n'
           if extinct is not None and first_zero != extinct else '')
        + f'电压波形最大偏差 {voltage_error:.3g} V。\n'
        + '\n'.join(summary["limitations"])+'\n', encoding="utf-8")
    with (run/"pulse-diagnostics.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["time_ns", "voltage_V", "electrons_real", "ions_real", "ionization_pairs_real",
                         "HV_total_A", "HV_displacement_A", "HV_particle_A", "Ground_particle_A",
                         "secondary_electrons_cumulative_real", "HV_SEE_A", "Ground_SEE_A",
                         "quartz_incident_cumulative_real", "quartz_return_cumulative_real",
                         "quartz_net_loss_cumulative_real"])
        writer.writerows(zip(t*1e9, field["BFO-boundary-001-bc_hv"][:n], ne, ni, birth_i,
                             *currents["HV"], currents["Ground"][2], emitted, emission["HV"], emission["Ground"],
                             wall_impacts, wall_returns, wall_impacts-wall_returns))
    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True, constrained_layout=True)
    axes[0].plot(t*1e9, field["BFO-boundary-001-bc_hv"][:n], color="#b54a26")
    axes[0].set_ylabel("Applied voltage (V)")
    axes[1].plot(t*1e9, ne, label="Electrons", color="#1766bb")
    axes[1].plot(t*1e9, ni, label="He+ + He2+" if molecular else "He+", color="#b54a26")
    if molecular:
        axes[1].plot(t*1e9, part["NumDens-Spec-004"][:n]*volume, label="He2+", color="#be9a34")
    if chemistry is not None:
        axes[1].plot(chemistry_time*1e9, ionization, "--", label="Cumulative ionization pairs", color="#25814c")
        axes[1].plot(chemistry_time*1e9, recombination, ":", label="Cumulative recombination pairs", color="#78563b")
    else:
        axes[1].plot(t*1e9, birth_i, "--", label="Cumulative ionization pairs", color="#25814c")
    electrode_returns = emitted-wall_returns
    if electrode_returns[-1] > 0:
        axes[1].plot(t*1e9, electrode_returns, ":", label="Cumulative electrode secondaries", color="#673aa1")
    axes[1].set_ylabel("Physical particle number")
    axes[1].legend(loc="best")
    width = max(1, int(round(0.1e-9/(t[1]-t[0]))))
    stops = np.r_[np.arange(0, n-1, width), n-1]
    for b, (_, _, current) in currents.items():
        charge = np.r_[0., np.cumsum(current*dt)]
        # Interval averages conserve collected charge, including discrete particle impacts.
        average = (charge[stops[1:]+1]-charge[stops[:-1]+1])/(t[stops[1:]]-t[stops[:-1]])
        axes[2].plot((t[stops[1:]]+t[stops[:-1]])*0.5e9, average*1e6, label=b)
    axes[2].set_ylabel("Particle current (μA)\n0.1 ns interval averages")
    axes[2].set_xlabel("Time (ns)")
    axes[2].legend()
    for ax in axes:
        ax.grid(alpha=.2)
    pulse = "/".join(f'{parameter[key]*1e9:g}' for key in ("PulseRise", "PulseFlat", "PulseFall"))
    fig.suptitle(f'He tube: D={geometry["tube_bore_um"]:g} μm, tip R={geometry["tip_radius_um"]:g} μm, '
                 f'gap={geometry["tip_gap_um"]/1000:g} mm; positive {pulse} ns pulse')
    fig.savefig(run/"pulse-diagnostics.png", dpi=160)
    plt.close(fig)
    if len(frames) > 1 and axial_density.max() > 0:
        times_ns = np.array([row["time_ns"] for row in snapshots])
        with (run/"axial-density.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_ns", "axial_center_um", "cross_section_mean_electron_density_m3"])
            for stamp, row in zip(times_ns, axial_density):
                writer.writerows(zip(np.full(len(row), stamp), axial_centers*1e6, row))
        fig, ax = plt.subplots(figsize=(8.4, 5), constrained_layout=True)
        vmax = float(axial_density.max())
        # Keep one-particle bins visible and distinguish them from empty bins.
        positive = axial_density[axial_density > 0]
        vmin = min(vmax/10, float(positive.min())/2)
        im = ax.pcolormesh(axial_centers*1e6, times_ns, np.maximum(axial_density, vmin/10),
                           shading="nearest", norm=LogNorm(vmin, vmax),
                           cmap=matplotlib.colormaps["turbo"].with_extremes(under="#edf2f8"))
        fig.colorbar(im, ax=ax, extend="min", label="Cross-section mean electron density (m⁻³)")
        ax.set(xlabel="Axial position (μm): anode ← gas gap → cathode", ylabel="Time (ns)",
               ylim=(times_ns[0], times_ns[-1]), title="Axial evolution of electron density")
        ax.text(.02, .97, "Light background: no electrons in stored frame", transform=ax.transAxes,
                ha="left", va="top", fontsize=9, color="#506176")
        for phase in (parameter["PulseRise"], parameter["PulseRise"]+parameter["PulseFlat"]):
            if times_ns[0] < phase*1e9 < times_ns[-1]:
                ax.axhline(phase*1e9, linestyle="--", color="white", linewidth=.8)
        fig.savefig(run/"axial-density.png", dpi=170)
        plt.close(fig)
    # Fixed density scale for time comparisons; preserve actual cell averages.
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure = Figure(figsize=(7, 7), dpi=110)
    canvas = FigureCanvasAgg(figure)
    from PIL import Image
    pictures = []
    for path in frames:
        render_slice(figure, "电子密度 (m⁻³)", geometry, run/"helium_mesh.h5", path,
                     "ElectronDensityCell", True, (density_lower, max_density) if max_density else (None, None), True, True)
        canvas.draw()
        pictures.append(Image.fromarray(np.asarray(canvas.buffer_rgba())[:, :, :3].copy()))
    pictures[0].save(run/"electron-distribution.png")
    pictures[0].save(run/"electron-evolution.gif", save_all=True, append_images=pictures[1:],
                     duration=300, loop=0)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--assessment", help="Reviewed breakdown assessment for the result summary")
    args = parser.parse_args()
    result = analyze(args.run, args.allow_partial, args.assessment)
    print(json.dumps({k: v for k, v in result.items() if k not in ("snapshots", "geometry")},
                     ensure_ascii=False, indent=2))
