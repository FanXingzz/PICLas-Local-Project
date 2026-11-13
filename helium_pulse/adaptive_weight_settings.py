"""Shared validation for the checkpoint runner and the VS Code editor."""
import json
import math
from pathlib import Path
from tempfile import NamedTemporaryFile

from piclas_ini import real, replace_parameters


CASE = Path("verification/He_D100um_Pos6000V_AdaptiveSqrt_Restart1250ps")
FIELDS = (
    ("exponent", "增重指数", 0.5, 0, 1, "Part-AdaptiveVMPFExponent"),
    ("interval", "更新间隔（步）", 50, 1, 1000, "Part-AdaptiveVMPFInterval"),
    ("min_count", "每组合并后最少宏粒子", 16, 4, 100, "Part-AdaptiveVMPFMinCount"),
    ("max_gain", "目标权重倍率上限", 2.0, 1, 8, "Part-AdaptiveVMPFMaxGain"),
    ("tip_width_um", "电子针尖保护宽度（μm）", 25.0, 0, 500, "Part-AdaptiveVMPFTipWidth"),
)
MERGE_FIELDS = tuple(
    (f"merge_{species}", label, 100, 0, 2**31-1, f"Part-Species{species}-vMPFMergeThreshold")
    for species, label in ((3, "电子 e⁻"), (2, "He⁺"), (4, "He₂⁺"), (5, "He*"), (6, "He₂*"))
)
ALL_FIELDS = FIELDS + MERGE_FIELDS
FIELD_HELP = {
    "exponent": "0 只用固定阈值，0.5 按加权粒子数的平方根提高目标权重。",
    "interval": "自适应算法每隔多少个时间步更新一次。固定合并仍逐步检查。",
    "min_count": "每个参与自适应合并的单元内同物种粒子组，合并后至少保留的宏粒子数。",
    "max_gain": "自适应目标平均权重相对于参考权重的最大倍率。",
    "tip_width_um": "从针尖向间隙内量取。在该区域和针尖后方，电子沿用固定阈值。",
}


def validate(settings):
    if not isinstance(settings, dict) or settings.keys() != {key for key, *_ in ALL_FIELDS}:
        raise ValueError("请填写全部动态权重参数。")
    result = {}
    for key, label, default, low, high, _ in ALL_FIELDS:
        if settings[key] is None or isinstance(settings[key], bool):
            raise ValueError(f"请为「{label}」填写有效数值。")
        try:
            value = float(settings[key])
        except (ValueError, TypeError) as error:
            raise ValueError(f"请为「{label}」填写有效数值。") from error
        integer = isinstance(default, int)
        if not math.isfinite(value) or not low <= value <= high or (integer and value != int(value)):
            kind = "的整数" if integer else "的数值"
            raise ValueError(f"{label}需要 {low} 到 {high} 之间{kind}。")
        if key.startswith("merge_") and value == 1:
            raise ValueError(f"{label}的固定合并阈值需为 0 或至少 2，以便保留粒子的速度方差。")
        result[key] = int(value) if integer else value
    return result


def case_settings(parameters):
    # PICLas defaults an unspecified fixed merge threshold to zero.
    values = {}
    for key, _, default, _, _, parameter in ALL_FIELDS:
        fallback = 0 if key.startswith("merge_") else default
        if parameter in parameters:
            value = real(parameters[parameter])
            if key == "tip_width_um":
                value = float(f"{value*1e6:.16g}")
        else:
            value = fallback
        values[key] = value
    return validate(values)


def weight_parameters(values, definitions=ALL_FIELDS):
    return {parameter: f"{(values[key]*1e-6 if key == 'tip_width_um' else values[key]):.16g}"
            for key, _, _, _, _, parameter in definitions}


def write_weight_parameters(text, parameters, changes):
    text = replace_parameters(text, {key: value for key, value in changes.items() if key in parameters})
    added = [f"{key} = {value}" for key, value in changes.items() if key not in parameters]
    if added:
        text = text.rstrip() + "\n\n! Jia dynamic solver settings\n" + "\n".join(added) + "\n"
    return text


def settings_for(directory):
    path = directory/"settings.json"
    defaults = {key: default for key, _, default, *_ in ALL_FIELDS}
    stored = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(stored, dict):
        raise ValueError("动态权重设置文件格式有误。")
    return validate(defaults | stored)


def save_settings(directory, settings):
    if not isinstance(settings, dict):
        raise ValueError("动态权重设置格式有误。")
    values = validate(settings_for(directory) | settings)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(values, stream, indent=2)
        stream.write("\n")
    try:
        temporary.replace(directory/"settings.json")
    finally:
        temporary.unlink(missing_ok=True)
    return values


def editor_fields(values, definitions=FIELDS):
    return [{"id": key, "label": label, "value": values[key], "integer": isinstance(default, int),
             "min": low, "max": high, "help": FIELD_HELP.get(key, "该物种每个单元的固定合并阈值。0 关闭合并。")}
            for key, label, default, low, high, _ in definitions]
