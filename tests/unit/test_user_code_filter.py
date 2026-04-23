"""v2.1.0 — user-code filtering for guid index + singleton/missing queries.

Real-project audit (Indian Bike, clash.io, Graudation-Saga) showed that
``Library/PackageCache/`` meta files were leaking into the guid index,
producing placeholder Script nodes that pointed at unmodifiable package
code and then dominated ``find_singletons`` / ``find_missing_scripts``
results. These tests lock down the fix.
"""

from __future__ import annotations

from pathlib import Path

from unitygraph.build.graph import Edge, Graph, Node
from unitygraph.build.parsers import meta_parser
from unitygraph.mcp import queries

# ---------------------------------------------------------------------------
# build_guid_index skip-dirs behavior
# ---------------------------------------------------------------------------


def _write_meta(dir_: Path, name: str, guid: str) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / f"{name}.meta").write_text(f"fileFormatVersion: 2\nguid: {guid}\n")
    (dir_ / name).write_text("// stub")


def test_guid_index_skips_library_packagecache(tmp_path):
    """The real-world Indian Bike/clash.io bug: Library/PackageCache/.../*.cs.meta
    was being indexed, so scene references to Unity built-ins resolved to
    Library paths. Lock that out."""
    _write_meta(tmp_path / "Assets" / "Scripts", "MyScript.cs", "a" * 32)
    _write_meta(
        tmp_path / "Library" / "PackageCache" / "com.unity.ugui@abc" / "Runtime",
        "Image.cs",
        "b" * 32,
    )
    index = meta_parser.build_guid_index(tmp_path)
    assert "a" * 32 in index, "user script must be indexed"
    assert "b" * 32 not in index, "Library/PackageCache must be skipped"


def test_guid_index_keeps_user_embedded_packages(tmp_path):
    """Packages/<user-package> is legitimate user source — NOT a Library
    package cache — and must still be indexed."""
    _write_meta(
        tmp_path / "Packages" / "com.mycompany.toolkit" / "Runtime",
        "Tool.cs",
        "c" * 32,
    )
    index = meta_parser.build_guid_index(tmp_path)
    assert "c" * 32 in index, "user-embedded Packages/ should be indexed"


def test_guid_index_allows_opt_out_of_skipping(tmp_path):
    """Tests + raw dumps want the unfiltered view; empty skip_dirs enables it."""
    _write_meta(tmp_path / "Library" / "X", "Y.cs", "d" * 32)
    index = meta_parser.build_guid_index(tmp_path, skip_dirs=())
    assert "d" * 32 in index


def test_guid_index_skips_temp_and_obj(tmp_path):
    """Temp/, obj/, Build/ are build artifacts — same treatment as Library."""
    _write_meta(tmp_path / "Temp" / "gen", "G.cs", "1" * 32)
    _write_meta(tmp_path / "obj" / "Debug", "D.cs", "2" * 32)
    _write_meta(tmp_path / "Build" / "out", "O.cs", "3" * 32)
    _write_meta(tmp_path / "Assets", "Real.cs", "4" * 32)
    index = meta_parser.build_guid_index(tmp_path)
    assert set(index.keys()) == {"4" * 32}


# ---------------------------------------------------------------------------
# _is_user_script classification
# ---------------------------------------------------------------------------


def _script_node(path: str, external: bool = False) -> Node:
    return Node(
        id=f"script::X::{path}",
        type="Script",
        data={"name": "X", "file_path": path, "external": external},
    )


def test_is_user_script_accepts_assets_path():
    assert queries._is_user_script(_script_node("Assets/Scripts/MyScript.cs"))
    # Windows-style separators are also OS-agnostic
    assert queries._is_user_script(_script_node("Assets\\Scripts\\MyScript.cs"))


def test_is_user_script_accepts_user_package():
    assert queries._is_user_script(
        _script_node("Packages/com.mycompany.toolkit/Runtime/Tool.cs")
    )


def test_is_user_script_rejects_external_placeholder():
    assert not queries._is_user_script(
        _script_node("Assets/Scripts/MyScript.cs", external=True)
    )


def test_is_user_script_rejects_library_path():
    assert not queries._is_user_script(
        _script_node("Library/PackageCache/com.unity.ugui/Runtime/Image.cs")
    )


def test_is_user_script_rejects_third_party_directories():
    for path in [
        "Assets/Plugins/SomeSDK/API.cs",
        "Assets/Feel/NiceVibrations/MMVibrationManager.cs",
        "Assets/Standard Assets/Camera/FreeLook.cs",
        "Assets/ThirdParty/Something.cs",
    ]:
        assert not queries._is_user_script(_script_node(path)), path


def test_is_user_script_does_not_substring_match_plugins():
    """A file named `MyPluginsHelper.cs` sitting directly in Assets/ is
    user code — 'Plugins' as a path *segment* is what flags third-party."""
    assert queries._is_user_script(_script_node("Assets/MyPluginsHelper.cs"))


def test_is_user_script_rejects_non_script_node():
    go = Node(id="go::1", type="GameObject", data={"name": "Player"})
    assert not queries._is_user_script(go)


def test_is_user_script_rejects_empty_path():
    assert not queries._is_user_script(_script_node(""))


# ---------------------------------------------------------------------------
# find_singletons user_only filtering
# ---------------------------------------------------------------------------


def _make_mini_graph() -> Graph:
    """Graph with one user script + one third-party script, each attached twice."""
    g = Graph(project_root="/fake")
    user = Node(
        id="script::MyCtl::Assets/Scripts/MyCtl.cs",
        type="Script",
        data={"name": "MyCtl", "file_path": "Assets/Scripts/MyCtl.cs"},
    )
    image = Node(
        id="script::Image::Library/PackageCache/com.unity.ugui/Image.cs",
        type="Script",
        data={
            "name": "Image",
            "file_path": "Library/PackageCache/com.unity.ugui/Image.cs",
            "external": True,
        },
    )
    go_a = Node(id="go::a", type="GameObject", data={"name": "A"})
    go_b = Node(id="go::b", type="GameObject", data={"name": "B"})
    for n in (user, image, go_a, go_b):
        g.add_node(n)
    for src in (user.id, image.id):
        for dst in (go_a.id, go_b.id):
            g.add_edge(Edge(from_id=src, to_id=dst, type="attached_to"))
    return g


def test_find_singletons_user_only_default_drops_external():
    g = _make_mini_graph()
    result = queries.find_singletons(g, min_attachments=2)
    names = {h["script"]["name"] for h in result["singletons"]}
    assert names == {"MyCtl"}


def test_find_singletons_user_only_false_includes_external():
    g = _make_mini_graph()
    result = queries.find_singletons(g, min_attachments=2, user_only=False)
    names = {h["script"]["name"] for h in result["singletons"]}
    assert names == {"MyCtl", "Image"}


# ---------------------------------------------------------------------------
# find_missing_scripts min_attachments filtering
# ---------------------------------------------------------------------------


def test_find_missing_scripts_filters_zero_attachment_placeholders():
    g = Graph(project_root="/fake")
    g.add_node(
        Node(
            id="script::Ghost::<external:xxx>",
            type="Script",
            data={"name": "Ghost", "external": True, "guid": "xxx"},
        )
    )
    g.add_node(
        Node(
            id="script::Real::<external:yyy>",
            type="Script",
            data={"name": "Real", "external": True, "guid": "yyy"},
        )
    )
    g.add_node(Node(id="go::a", type="GameObject", data={"name": "A"}))
    # Only "Real" is attached to a GameObject.
    g.add_edge(Edge(from_id="script::Real::<external:yyy>", to_id="go::a", type="attached_to"))

    default = queries.find_missing_scripts(g)
    assert default["count"] == 1
    assert default["missing_scripts"][0]["guid"] == "yyy"

    include_all = queries.find_missing_scripts(g, min_attachments=0)
    assert include_all["count"] == 2
