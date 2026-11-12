"""Render a white-background center section of the mesh or a computed field."""
from functools import lru_cache

import h5py
import matplotlib as mpl
from matplotlib.collections import PolyCollection
from matplotlib.colors import LogNorm, Normalize
from matplotlib.patches import Patch, Polygon
import numpy as np

from tube_cases import format_length, taper_dimensions

INK = "#17263b"
MUTED = "#506176"
QUARTZ = "#d6e2ef"
HELIUM = "#b6e2ef"
HV = "#d0753b"
GROUND = "#526579"

mpl.rcParams["font.family"] = ["Microsoft YaHei", "DejaVu Sans"]
mpl.rcParams["axes.unicode_minus"] = False


@lru_cache(maxsize=4)
def mesh_slice(path, _modified, axisymmetric=False):
    with h5py.File(path) as mesh:
        vertices = mesh["NodeCoords"][:].reshape(-1, 8, 3)*1e6
        zones = mesh["ElemInfo"][:, 1]
    normal = 2 if axisymmetric else 1
    transverse = 1 if axisymmetric else 2
    mid_y = (vertices[:, :, normal].min() + vertices[:, :, normal].max())/2
    picked = np.flatnonzero((vertices[:, :, normal].min(axis=1) < mid_y) &
                            (vertices[:, :, normal].max(axis=1) >= mid_y))
    edges = [(i, i ^ bit) for bit in (1, 2, 4) for i in range(8) if not i & bit]
    polygons = []
    ids = []
    for idx in picked:
        points = vertices[idx]
        section = []
        for i, j in edges:
            a, b = points[i], points[j]
            if min(a[normal], b[normal]) < mid_y <= max(a[normal], b[normal]):
                hit = a + (b-a)*(mid_y-a[normal])/(b[normal]-a[normal])
                section.append(hit[[0, transverse]])
        if not section:
            continue
        points2 = np.unique(section, axis=0)
        if len(points2) >= 3:
            angles = np.arctan2(*(points2 - points2.mean(axis=0)).T[::-1])
            polygons.append(points2[np.argsort(angles)])
            ids.append(idx)
    if not ids:
        raise ValueError("在该网格中未找到 XZ 中心截面")
    return len(vertices), np.asarray(ids), zones[ids], polygons


@lru_cache(maxsize=8)
def read_field(path, _modified, field, cells):
    with h5py.File(path) as state:
        if field == "ElectronDensityCell":
            names = list(state.attrs["VarNamesAdd"].astype(str))
            return state["ElemData"][:, names.index(field)]
        data = state["DG_Solution"][:].reshape(cells, -1, 4)
        if field == "Phi":
            return data[:, :, 0].mean(axis=1)
        return np.linalg.norm(data[:, :, 1:4], axis=2).mean(axis=1)


def color_range(values, logarithmic, lower, upper):
    finite = values[np.isfinite(values)]
    positive = finite[finite > 0]
    if not len(finite) or (logarithmic and not len(positive)):
        if lower is None or upper is None:
            return None
        default_min, default_max = lower, upper
    elif logarithmic:
        default_max = float(positive.max())
        default_min = min(max(float(positive.min()), default_max/1e4), default_max/10)
    else:
        default_min, default_max = float(finite.min()), float(finite.max())
        if default_min == default_max:
            default_max += max(abs(default_max)*0.01, 1.0)
    lower = default_min if lower is None else lower
    upper = default_max if upper is None else upper
    if not (np.isfinite(lower) and np.isfinite(upper) and lower < upper):
        raise ValueError("色标下限须小于上限。可清空两项以恢复自动色标。")
    if logarithmic and lower <= 0:
        raise ValueError("对数色标的下限须大于零。")
    return LogNorm(lower, upper) if logarithmic else Normalize(lower, upper)


def pin_section(geometry, sign):
    radius = geometry["tip_radius_um"]
    half_gap = geometry["tip_gap_um"]/2
    end = sign*geometry["domain_length_um"]/2
    if geometry.get("needle_shape") == "tapered":
        _, _, shoulder = taper_dimensions(geometry)
        shaft = geometry["shaft_diameter_um"]/2
        stop = np.pi/2-np.radians(geometry["cone_half_angle_deg"])
        angle = np.linspace(-stop, stop, 65)
        cap_x = sign*(half_gap+radius*(1-np.cos(angle)))
        shoulder_x = sign*(half_gap+shoulder)
        return np.column_stack((np.r_[end, shoulder_x, cap_x, shoulder_x, end],
                                np.r_[-shaft, -shaft, radius*np.sin(angle), shaft, shaft]))
    angle = np.linspace(-np.pi/2, np.pi/2, 49)
    tip_x = sign*(half_gap + radius*(1-np.cos(angle)))
    return np.column_stack((np.r_[end, tip_x, end], np.r_[-radius, radius*np.sin(angle), radius]))


def geometry_bounds(geometry, bore_only):
    half_length = geometry["domain_length_um"]/2
    if bore_only:
        transverse = geometry["tube_bore_um"]/2
    elif geometry.get("structure") == "tube_only":
        transverse = geometry["tube_outer_um"]/2
    else:
        transverse = geometry["plate_gap_um"]/2 + geometry["plate_thickness_um"]
    minimum = 0 if geometry.get("mesh_method") == "axisymmetric" else -transverse
    return (-half_length, half_length), (minimum, transverse)


def focus_bounds(geometry, bore_only, focus):
    axial, radial = geometry_bounds(geometry, bore_only)
    if focus == "midgap":
        half = geometry["tip_gap_um"]/10
        return (-half, half), radial
    if focus in ("hv-tip", "ground-tip"):
        sign = -1 if focus == "hv-tip" else 1
        radius = geometry["tip_radius_um"]
        tip = sign*geometry["tip_gap_um"]/2
        back = 4*radius
        width = 5*radius
        if geometry.get("needle_shape") == "tapered":
            _, _, shoulder = taper_dimensions(geometry)
            back = max(back, shoulder+2*radius)
            width = max(width, .65*geometry["shaft_diameter_um"])
        ends = sorted((tip-6*sign*radius, tip+sign*back))
        return (max(axial[0], ends[0]), min(axial[1], ends[1])), (
            max(radial[0], -width), min(radial[1], width))
    return axial, radial


def render_slice(figure, title, geometry=None, mesh=None, frame=None, field="",
                 logarithmic=False, limits=(None, None), vertical=True, bore_only=False, equal=False,
                 mesh_overlay=False, focus="full", clean=False):
    figure.clear()
    axes = figure.add_subplot()
    right = .88 if focus != "full" else .94
    figure.subplots_adjust(left=0.15, right=right, bottom=0.15, top=0.86)
    axes.set_facecolor("white")
    if focus == "full":
        axes.set_title(title, loc="left", color=INK, fontsize=15, weight="bold", pad=23)
    else:
        figure.text(.15, .925, title, color=INK, fontsize=15, weight="bold")
    axes.tick_params(colors=MUTED, labelsize=9)
    for spine in axes.spines.values():
        spine.set_color("#a6b4c3")
    transverse_scale = 1000 if geometry and bore_only and geometry["tube_bore_um"] < 1 else 1
    transverse_unit = "nm" if transverse_scale == 1000 else "μm"

    def plot_points(points):
        axial = points[:, 0]
        transverse = points[:, 1]*transverse_scale
        return np.column_stack((transverse, axial) if vertical else (axial, transverse))

    axial_label = "轴向 X (μm)"
    axisymmetric = geometry is not None and geometry.get("mesh_method") == "axisymmetric"
    transverse_label = f"径向 r ({transverse_unit})" if axisymmetric else f"横向 Z ({transverse_unit})"
    axes.set_xlabel(transverse_label if vertical else axial_label, color=INK)
    axes.set_ylabel(axial_label if vertical else transverse_label, color=INK)
    axes.set_aspect((transverse_scale if vertical else 1/transverse_scale) if equal else "auto")
    subtitle = "二维轴对称 x-r 剖面" if axisymmetric else "XZ 中心截面"
    if geometry:
        d = format_length(geometry["tube_bore_um"])
        g = format_length(geometry["tip_gap_um"])
        r = format_length(geometry["tip_radius_um"])
        if focus in ("hv-tip", "ground-tip"):
            subtitle = f"{'高压针尖' if focus == 'hv-tip' else '接地针尖'} · R {r}"
        else:
            subtitle += f" · 管内径 {d} · 针距 {g} · 针尖 R {r}"
    subtitle += " · 等比例" if equal else " · 双轴独立比例"
    if focus == "full":
        axes.text(0, 1.015, subtitle, transform=axes.transAxes, color=MUTED, fontsize=9, va="bottom")
    else:
        figure.text(.15, .885, subtitle, color=MUTED, fontsize=9)

    values = None
    if mesh is not None and frame is not None and field:
        count, ids, zones, polygons = mesh_slice(mesh, mesh.stat().st_mtime_ns, axisymmetric)
        values = read_field(frame, frame.stat().st_mtime_ns, field, count)[ids]
        bounds = np.concatenate(polygons)
        axial_limits = (bounds[:, 0].min(), bounds[:, 0].max())
        transverse_limits = (bounds[:, 1].min(), bounds[:, 1].max())
        if geometry and (bore_only or focus != "full"):
            axial_limits, transverse_limits = focus_bounds(geometry, bore_only, focus)
        visible = np.ones(len(ids), dtype=bool)
        if geometry and bore_only:
            radius = geometry["tube_bore_um"]/2
            visible = np.array([abs(poly[:, 1].mean()) <= radius for poly in polygons])
        if geometry and focus != "full":
            lower = np.array([axial_limits[0], transverse_limits[0]])
            upper = np.array([axial_limits[1], transverse_limits[1]])
            visible &= np.array([np.all(poly.max(axis=0) >= lower) and np.all(poly.min(axis=0) <= upper)
                                 for poly in polygons])
        active = zones != 2 if field == "ElectronDensityCell" else np.ones(len(ids), dtype=bool)
        if field == "ElectronDensityCell":
            quartz = [plot_points(poly) for poly, zone in zip(polygons, zones) if zone == 2]
            if quartz:
                axes.add_collection(PolyCollection(quartz, facecolors=QUARTZ, edgecolors="none",
                                                   antialiaseds=False))
        norm = color_range(values[active & visible], logarithmic, *limits)
        colored = [plot_points(poly) for poly, mask in zip(polygons, active) if mask]
        colors = values[active]
        cmap = mpl.colormaps["turbo"].with_extremes(under="#302c79", bad="#f3f5fa")
        if clean:
            cmap = mpl.colormaps["jet"].with_extremes(under="#000080", bad="#ffffff")
        if norm is None:
            axes.add_collection(PolyCollection(colored, facecolors=cmap(0), edgecolors="none",
                                               antialiaseds=False))
            axes.text(0.5, 0.985, "当前截面没有正值", transform=axes.transAxes,
                      ha="center", va="top", color=INK, bbox={"facecolor": "white", "edgecolor": "none"})
        else:
            if field in ("ElectronDensityCell", "E") and not np.any(values[active & visible] > 0):
                label = "当前无电子（nₑ = 0）" if field == "ElectronDensityCell" else "当前电场为零"
                axes.text(0.5, 0.985, label, transform=axes.transAxes,
                          ha="center", va="top", color=INK,
                          bbox={"facecolor": "white", "edgecolor": "none"})
            if logarithmic:
                colors = np.maximum(colors, norm.vmin/10)
            cloud = PolyCollection(colored, array=colors, cmap=cmap, norm=norm,
                                   edgecolors="none", antialiaseds=False)
            axes.add_collection(cloud)
            extend = "both" if any(bound is not None for bound in limits) else ("min" if logarithmic else "neither")
            if not clean:
                bar = figure.colorbar(cloud, ax=axes, fraction=0.058, pad=0.055, extend=extend)
                bar.set_label(title, color=INK)
                bar.ax.tick_params(labelsize=8, colors=MUTED)
    elif geometry:
        axial_limits, transverse_limits = focus_bounds(geometry, bore_only, focus)
        length = geometry["domain_length_um"]
        radius = geometry["tube_bore_um"]/2
        outer = geometry["tube_outer_um"]/2
        tube = geometry.get("structure") == "tube_only"
        materials = [(-radius, radius, HELIUM)]
        if not tube:
            plate = geometry["plate_gap_um"]/2
            thickness = geometry["plate_thickness_um"]
            materials += [(sign*plate, sign*(plate+thickness), QUARTZ) for sign in (-1, 1)]
        materials += [(sign*radius, sign*outer, "#a8bbd3") for sign in ((1,) if axisymmetric else (-1, 1))]
        for bottom, top, color in materials:
            vertices = np.array([[-length/2, bottom], [length/2, bottom],
                                 [length/2, top], [-length/2, top]])
            axes.add_patch(Polygon(plot_points(vertices), facecolor=color, edgecolor="#7187a1",
                                   linewidth=0.65))
        handles = [Patch(facecolor=HELIUM, label="氦气"), Patch(facecolor="#a8bbd3", label="石英管"),
                   Patch(facecolor=HV, label="高压针"), Patch(facecolor=GROUND, label="接地针")]
        if not tube:
            handles.insert(1, Patch(facecolor=QUARTZ, label="石英板"))
        axes.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.13),
                    ncol=len(handles), frameon=False, fontsize=9)
        figure.subplots_adjust(bottom=0.21)
    elif mesh:
        _, _, _, polygons = mesh_slice(mesh, mesh.stat().st_mtime_ns, axisymmetric)
        bounds = np.concatenate(polygons)
        axial_limits = (bounds[:, 0].min(), bounds[:, 0].max())
        transverse_limits = (bounds[:, 1].min(), bounds[:, 1].max())
        axes.add_collection(PolyCollection([plot_points(p) for p in polygons],
                                           facecolors=HELIUM, edgecolors="none", antialiaseds=False))
    else:
        raise ValueError("当前没有可显示的网格")

    if mesh_overlay and mesh is not None and mesh.is_file():
        _, _, _, polygons = mesh_slice(mesh, mesh.stat().st_mtime_ns, axisymmetric)
        axes.add_collection(PolyCollection([plot_points(poly) for poly in polygons],
                                           facecolors="none", edgecolors="#334964",
                                           linewidths=0.27, alpha=0.62))

    if geometry:
        for sign, color in ((-1, HV), (1, GROUND)):
            axes.add_patch(Polygon(plot_points(pin_section(geometry, sign)), facecolor="white" if clean else color,
                                   edgecolor="none" if clean else "#37495e", linewidth=0.55))
    axial_padding = (axial_limits[1] - axial_limits[0])*0.045
    transverse_padding = (transverse_limits[1] - transverse_limits[0])*0.10
    axial = (axial_limits[0]-axial_padding, axial_limits[1]+axial_padding)
    transverse = ((transverse_limits[0]-transverse_padding)*transverse_scale,
                  (transverse_limits[1]+transverse_padding)*transverse_scale)
    if axisymmetric:
        transverse = (0., transverse[1])
    axes.set_xlim(*(transverse if vertical else axial))
    axes.set_ylim(*(axial if vertical else transverse))
    if focus != "full":
        axes.set_anchor((.72, .5))
    if frame is not None and values is not None:
        time_ns = float(frame.stem.rsplit("_", 1)[-1])*1e9
        if focus == "full":
            axes.text(1, 1.07, f"t = {time_ns:g} ns", transform=axes.transAxes,
                      ha="right", color=MUTED, fontsize=10)
        else:
            figure.text(.94, .925, f"t = {time_ns:g} ns", ha="right", color=MUTED, fontsize=10)
    if clean:
        for label in list(figure.texts) + list(axes.texts):
            label.remove()
        axes.set_axis_off()
        axes.set_position((0, 0, 1, 1))
