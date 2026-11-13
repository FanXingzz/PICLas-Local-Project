"""Read PICLas parameter files and edit individual assignments in place."""
from collections.abc import Mapping
import re


ASSIGNMENT = re.compile(
    r"^(?P<prefix>\ufeff?[ \t]*(?P<key>[^ \t\r\n=!][^=\r\n!]*?)[ \t]*=[ \t]*)"
    r"(?P<value>[^!\r\n]*)(?P<comment>![^\r\n]*)?(?=\r?$)",
    re.M,
)


def entries(text):
    """Keep repeated entries for PICLas options such as BoundaryName."""
    return [(match["key"], match["value"].strip()) for match in ASSIGNMENT.finditer(text)]


class Parameters(Mapping):
    """Look up unique scalar options without requiring a specific spelling."""

    def __init__(self, pairs):
        self._values = {}
        self._duplicates = set()
        for key, value in pairs:
            key = key.casefold()
            if key in self._values:
                self._duplicates.add(key)
            self._values[key] = value

    def __getitem__(self, key):
        folded = key.casefold()
        if folded in self._duplicates:
            raise ValueError(f"参数文件包含重复的 {key}")
        return self._values[folded]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


def parse_parameters(text):
    return Parameters(entries(text))


def real(value):
    return float(value.lower().replace("d", "e"))


def replace_parameters(text, values):
    changes = {key.casefold(): (key, value) for key, value in values.items()}
    if len(changes) != len(values):
        raise ValueError("参数修改包含重复键名。")
    if not changes:
        return text
    found = set()

    def replace(match):
        key = match["key"].casefold()
        if key not in changes:
            return match[0]
        name, value = changes[key]
        if key in found:
            raise ValueError(f"参数文件包含重复的 {name}")
        found.add(key)
        old_value = match["value"]
        trailing = old_value[len(old_value.rstrip(" \t")):]
        return f"{match['prefix']}{value}{trailing}{match['comment'] or ''}"

    updated = ASSIGNMENT.sub(replace, text)
    for key, (name, _) in changes.items():
        if key not in found:
            raise ValueError(f"参数文件缺少 {name}")
    return updated
