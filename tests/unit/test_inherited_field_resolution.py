"""v2.1.2 -- inherited-field method-call resolution.

The C# parser sees one file at a time, so when a subclass calls a
method on a field declared on its parent class, the parser can't
resolve the receiver type. The builder runs a second pass over all
parsed classes that walks each one's inheritance chain and promotes
matching unresolved calls into ``field_method_calls``.

Bug history: the bake-off (evals/bakeoff/) caught this on Q8 -- clash.io
has ``EnemyMelee : EnemyBase`` and EnemyMelee calls
``animator.SetAnimation(...)`` on the inherited ``animator`` field.
``who_uses(CharacterAnimator)`` returned 4 callers (CharacterBehaviour
only) when it should have returned 8 (CharacterBehaviour + EnemyMelee).
"""

from __future__ import annotations

from pathlib import Path

from unitygraph.build.builder import _resolve_inherited_member_calls
from unitygraph.build.parsers import cs_parser
from unitygraph.build.parsers.cs_parser import (
    CallSite,
    ClassInfo,
)


def _make_call(receiver: str, method: str, line: int = 1) -> CallSite:
    """Helper -- synthesize an unresolved CallSite as the parser would."""
    return CallSite(
        method=method,
        target=receiver,  # parser stashes receiver here when unresolved
        line=line,
        col=1,
        end_line=line,
        end_col=1,
        snippet=f"{receiver}.{method}()",
        containing_method="DoStuff",
        containing_class="",
    )


def test_resolves_simple_one_level_inheritance() -> None:
    parent = ClassInfo(
        name="EnemyBase",
        namespace=None,
        base_class="MonoBehaviour",
        field_types={"animator": "CharacterAnimator"},
    )
    child = ClassInfo(
        name="EnemyMelee",
        namespace=None,
        base_class="EnemyBase",
    )
    child.unresolved_member_calls.append(_make_call("animator", "SetAnimation", line=42))

    _resolve_inherited_member_calls([(Path("a.cs"), [parent]), (Path("b.cs"), [child])])

    assert len(child.field_method_calls) == 1
    site = child.field_method_calls[0]
    assert site.target == "CharacterAnimator"
    assert site.method == "SetAnimation"
    assert site.line == 42
    assert child.unresolved_member_calls == []


def test_walks_multi_level_inheritance() -> None:
    grand = ClassInfo(
        name="Base",
        namespace=None,
        base_class="MonoBehaviour",
        field_types={"x": "Foo"},
    )
    mid = ClassInfo(name="Middle", namespace=None, base_class="Base")
    leaf = ClassInfo(name="Leaf", namespace=None, base_class="Middle")
    leaf.unresolved_member_calls.append(_make_call("x", "DoThing"))

    _resolve_inherited_member_calls(
        [(Path("a"), [grand]), (Path("b"), [mid]), (Path("c"), [leaf])]
    )

    assert len(leaf.field_method_calls) == 1
    assert leaf.field_method_calls[0].target == "Foo"


def test_unknown_parent_leaves_call_unresolved() -> None:
    """If the chain hits a non-user base (e.g. external SDK class we
    didn't parse), the receiver stays unresolved -- but doesn't crash."""
    child = ClassInfo(name="Sub", namespace=None, base_class="ThirdPartyBase")
    child.unresolved_member_calls.append(_make_call("xyz", "Run"))

    _resolve_inherited_member_calls([(Path("a"), [child])])

    assert child.field_method_calls == []
    assert len(child.unresolved_member_calls) == 1


def test_handles_inheritance_cycle_without_infinite_loop() -> None:
    """C# can't actually have inheritance cycles, but a malformed parse
    or odd source could produce one. Make sure we don't hang."""
    a = ClassInfo(name="A", namespace=None, base_class="B")
    b = ClassInfo(name="B", namespace=None, base_class="A")
    a.unresolved_member_calls.append(_make_call("doesnotexist", "Run"))

    _resolve_inherited_member_calls([(Path("a"), [a]), (Path("b"), [b])])

    # No crash, no resolution.
    assert a.field_method_calls == []


def test_does_not_clobber_already_resolved_calls() -> None:
    """Same-class field calls were already resolved by the parser into
    field_method_calls -- make sure the second pass doesn't duplicate them."""
    klass = ClassInfo(name="Solo", namespace=None, base_class=None)
    existing_call = CallSite(
        method="Foo",
        target="MyType",  # already a real type
        line=1,
        col=1,
        end_line=1,
        end_col=1,
        snippet="local.Foo()",
        containing_method="M",
        containing_class="Solo",
    )
    klass.field_method_calls.append(existing_call)

    _resolve_inherited_member_calls([(Path("a"), [klass])])

    assert len(klass.field_method_calls) == 1
    assert klass.field_method_calls[0] is existing_call


def test_end_to_end_via_real_parse() -> None:
    """Drive the real cs_parser + resolver against synthetic source so we
    cover the full pipeline (parser writes ``unresolved_member_calls``;
    resolver reads them)."""
    import tempfile

    parent_src = """
public class Base : MonoBehaviour {
    protected Animator animator;
}
"""
    child_src = """
public class Child : Base {
    void DoIt() {
        animator.Play("foo");
    }
}
"""
    with tempfile.TemporaryDirectory() as td:
        parent_path = Path(td) / "Base.cs"
        child_path = Path(td) / "Child.cs"
        parent_path.write_text(parent_src, encoding="utf-8")
        child_path.write_text(child_src, encoding="utf-8")

        parent_parsed = cs_parser.parse_file(parent_path)
        child_parsed = cs_parser.parse_file(child_path)

        # Before resolution: child has the unresolved call, no field_method_calls.
        child_class = child_parsed.classes[0]
        assert child_class.unresolved_member_calls, "parser should stash unresolved"
        assert child_class.field_method_calls == []

        _resolve_inherited_member_calls(
            [(parent_path, parent_parsed.classes), (child_path, child_parsed.classes)]
        )

        # After: the call is promoted with type=Animator.
        assert len(child_class.field_method_calls) == 1
        site = child_class.field_method_calls[0]
        assert site.target == "Animator"
        assert site.method == "Play"
        assert "Play" in site.snippet
