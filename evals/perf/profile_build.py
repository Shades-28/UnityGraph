"""Profile ``build_project`` on a given project with per-phase timings.

One-shot script -- not part of the committed CLI. Usage::

    python evals/perf/profile_build.py D:/PR/Unity/SomeProject
"""

from __future__ import annotations

import contextlib
import sys
import time
from pathlib import Path

from unitygraph.build.parsers import cs_parser, meta_parser, scene_parser


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: profile_build.py <project>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()

    def _discover(pattern: str) -> list[Path]:
        skip = {"Library", "Temp", "obj", "Build", "Builds", "Logs"}
        return [p for p in root.rglob(pattern) if not (set(p.parts) & skip)]

    t = time.perf_counter()
    cs_files = _discover("*.cs")
    scene_files = _discover("*.unity")
    prefab_files = _discover("*.prefab")
    print(
        f"discover:     {time.perf_counter() - t:6.2f}s  (cs={len(cs_files)} scenes={len(scene_files)} prefabs={len(prefab_files)})"
    )

    t = time.perf_counter()
    guid_index = meta_parser.build_guid_index(root)
    print(f"guid_index:   {time.perf_counter() - t:6.2f}s  ({len(guid_index)} guids)")

    t = time.perf_counter()
    parsed_scripts = []
    for p in cs_files:
        with contextlib.suppress(Exception):
            parsed_scripts.append(cs_parser.parse_file(p))
    print(f"cs_parse:     {time.perf_counter() - t:6.2f}s  ({len(parsed_scripts)} files)")

    t = time.perf_counter()
    parsed_scenes = []
    for p in scene_files:
        with contextlib.suppress(Exception):
            parsed_scenes.append(scene_parser.parse_file(p))
    print(f"scene_parse:  {time.perf_counter() - t:6.2f}s  ({len(parsed_scenes)} files)")

    t = time.perf_counter()
    parsed_prefabs = []
    for p in prefab_files:
        with contextlib.suppress(Exception):
            parsed_prefabs.append(scene_parser.parse_file(p))
    print(f"prefab_parse: {time.perf_counter() - t:6.2f}s  ({len(parsed_prefabs)} files)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
