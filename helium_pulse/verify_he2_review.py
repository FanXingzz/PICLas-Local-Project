"""Validate the four-species review case without starting a full pulse."""
import json

import h5py
import numpy as np

from analyze_full_pulse import (E_CHARGE, axisymmetric_gauss_weights, rotational_volumes, table,
                                validate_axisymmetric_particles)
from prepare_he2_review_case import CHECK, DATABASES, ROOT, TARGET
from record_model_settings import entries


BOUNDARIES = ("HV", "Ground", "Quartz")
WALL_CHECK = ROOT/"verification/He2_ElectrodeYieldCheck"


def latest_pilot(case):
    for run in sorted((case/"runs").glob("*-pilot-*"), reverse=True):
        if not (run/"run-status.txt").is_file() or (run/"run-status.txt").read_text().strip() != "complete":
            continue
        values = dict(entries((run/"parameter.ini").read_text()))
        if values.get("Particles-He2-ElectrodeYield") == "0.10":
            return run, values
    raise ValueError(f"No completed pilot with molecular-ion yield in {case}")


def audit(case):
    run, values = latest_pilot(case)
    part = table(run/"PartAnalyze.csv")
    surface = table(run/"SurfaceAnalyze.csv")
    time = part["TIME"]
    if not np.allclose(time, surface["TIME"], rtol=0, atol=1e-20):
        raise ValueError(f"Time grids differ in {run}")
    if not np.isclose(time[-1], 6e-12, rtol=0, atol=1e-20):
        raise ValueError(f"Unexpected short verification time in {run}")
    dt = np.diff(time, prepend=0)
    volume = rotational_volumes(run/"helium_mesh.h5").sum()
    count = {species: part[f"NumDens-Spec-{species:03d}"]*volume for species in (2, 3, 4)}
    flux = {species: {b: surface[f"Flux-Spec-{species:03d}-BC_{b}"]*dt for b in BOUNDARIES}
            for species in count}
    emitted = {b: surface.get(f"ElectricCurrentSEE-BC_{b}", np.zeros(len(dt)))*dt/E_CHARGE for b in BOUNDARIES}
    net = {species: values-values[0]+np.cumsum(sum(flux[species].values())) for species, values in count.items()}
    residual = float(np.max(abs(net[2]+net[4]-net[3]+np.cumsum(sum(emitted.values())))))
    if residual > 1e-6:
        raise ValueError(f"Electron/ion balance residual {residual:.6g} in {run}")

    weights = axisymmetric_gauss_weights(run/"helium_mesh.h5")
    wall_charge = E_CHARGE*np.cumsum(flux[2]["Quartz"]+flux[4]["Quartz"]-flux[3]["Quartz"]+emitted["Quartz"])
    charge_error = 0.
    geometry = json.loads((run/"geometry.json").read_text())
    for frame in run.glob("helium_pulse_State_*.h5"):
        with h5py.File(frame) as h5:
            validate_axisymmetric_particles(h5["PartData"][:], geometry, frame.name)
            idx = int(np.argmin(abs(time-h5.attrs["Time"][0])))
            if abs(time[idx]-h5.attrs["Time"][0]) > 1e-20:
                raise ValueError("Missing wall-charge sample for a saved state")
            charge = float(np.sum(h5["DG_SourceExt"][:].reshape(-1, 2, 4).mean(1)*weights))
            charge_error = max(charge_error, abs(charge-wall_charge[idx]))
    if charge_error > 1e-23:
        raise ValueError(f"Unexpected wall charge difference {charge_error:.6g} C in {run}")

    result = {"run": str(run.relative_to(ROOT)), "time_ps": float(time[-1]*1e12),
              "ion_electron_balance_error": residual, "wall_charge_error_C": charge_error,
              "particle_position_and_speed_valid": True}
    if case != WALL_CHECK:
        rate = float(values["Particles-He2-ThreeBodyRate"])
        density = float(values["Part-Species1-Init1-PartDensity"])
        probability = -np.expm1(-rate*density**2*time[-1])
        initial = float(part["nPart-Spec-002"][0])
        expected = initial*probability
        converted = float(net[4][-1]/float(values["Part-Species4-MacroParticleFactor"]))
        if abs(converted-expected) > max(5, 5*np.sqrt(expected*(1-probability))):
            raise ValueError(f"Conversion sample {converted:.6g} differs from expectation {expected:.6g}")
        result.update(rate_m6_per_s=rate, expected_conversion_macros=float(expected),
                      converted_macros=converted, live_He2_macros=int(part["nPart-Spec-004"][-1]))
    else:
        impacts = float(flux[4]["HV"].sum())
        secondaries = float(emitted["HV"].sum())
        if impacts < 500 or abs(secondaries/impacts-.10) > 5*np.sqrt(.10*.90/impacts):
            raise ValueError(f"Unexpected electrode test: {impacts:g} impacts, {secondaries:g} emissions")
        result.update(He2_HV_incident=impacts, emitted_electrons=secondaries, measured_yield=secondaries/impacts)
    return result


if __name__ == "__main__":
    filename = "XSec_Database_He_Plasma.h5"
    with h5py.File(DATABASES/filename) as original, h5py.File(TARGET/filename) as updated:
        def check(name, item):
            if isinstance(item, h5py.Dataset) and not np.array_equal(item[:], updated[name][:]):
                raise ValueError(f"Original cross section changed: {name}")
        original.visititems(check)
        threshold = updated["He-electron/REACTION/HeIon1-electron-electron"].attrs["Threshold [eV]"]
        if float(threshold) != 24.587:
            raise ValueError("Unexpected ground-state ionization threshold")
    settings = dict(entries((TARGET/"parameter.ini").read_text()))
    if settings["Particles-He2-ThreeBodyRate"] != "1.1e-43" or any((TARGET/"runs").glob("*-research-*")):
        raise ValueError("Check the nominal rate and the review gate")
    checks = {"nominal_pilot": audit(TARGET), "accelerated_conversion": audit(CHECK),
              "electrode_yield": audit(WALL_CHECK), "original_cross_sections_unchanged": True}
    (TARGET/"review-checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=2))
