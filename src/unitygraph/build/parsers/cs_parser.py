"""C# parser — tree-sitter based.

Extracts per-file: namespace, class names, base class, interfaces, serialized +
public fields, method names, MonoBehaviour lifecycle methods, ``GetComponent<T>``
calls, and class inheritance. No semantic type resolution — structural parsing.

Grammar reference: the tree-sitter-c-sharp AST uses ``name``/``body`` field
accessors on namespace/class nodes, an unnamed ``base_list`` child on classes,
and ``variable_declaration`` (with ``type`` field) wrapping ``variable_declarator``
(with ``name`` field + unnamed ``=`` + literal) for field defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tree_sitter_c_sharp as tsc
from tree_sitter import Language, Parser
from tree_sitter import Node as TSNode

_LANGUAGE = Language(tsc.language())
_PARSER = Parser(_LANGUAGE)

LIFECYCLE_METHODS = frozenset(
    {
        "Awake",
        "OnEnable",
        "Start",
        "FixedUpdate",
        "Update",
        "LateUpdate",
        "OnDisable",
        "OnDestroy",
        "OnTriggerEnter",
        "OnTriggerStay",
        "OnTriggerExit",
        "OnCollisionEnter",
        "OnCollisionStay",
        "OnCollisionExit",
        "OnApplicationQuit",
        "OnApplicationPause",
        "OnApplicationFocus",
    }
)


@dataclass
class FieldInfo:
    name: str
    type_name: str
    is_serialized: bool
    is_public: bool
    default_literal: str | None = None
    line: int = 0  # 1-indexed; 0 = unknown (v1.x graphs)
    col: int = 0


@dataclass
class MethodInfo:
    name: str
    is_lifecycle: bool
    line: int = 0
    col: int = 0
    end_line: int = 0


@dataclass
class CallSite:
    """One location where a call happens.

    Applies to both ``GetComponent<T>()`` invocations and method calls on
    stored fields (``_rigidbody.AddForce(...)``). The ``target`` is the
    type argument for generic calls, or the (guessed) type of the
    receiver for member-access calls.
    """

    method: str  # e.g. "GetComponent", "FindObjectOfType", "AddForce"
    target: str  # type-arg / receiver-type / or the method name when ambiguous
    line: int
    col: int
    end_line: int
    end_col: int
    snippet: str
    containing_method: str
    containing_class: str


@dataclass
class ClassInfo:
    name: str
    namespace: str | None
    base_class: str | None
    interfaces: list[str] = field(default_factory=list)
    fields: list[FieldInfo] = field(default_factory=list)
    methods: list[MethodInfo] = field(default_factory=list)
    # Bare-string lists kept for v1.x consumers (tests, builder).
    get_component_types: list[str] = field(default_factory=list)
    find_object_of_type_types: list[str] = field(default_factory=list)
    # v1.2+: rich call-site records.
    get_component_calls: list[CallSite] = field(default_factory=list)
    find_object_calls: list[CallSite] = field(default_factory=list)
    # Method calls on stored fields (`_rigidbody.AddForce(...)`) — each
    # entry's ``target`` is the receiver identifier, which the builder
    # resolves to the field's declared type.
    field_method_calls: list[CallSite] = field(default_factory=list)
    # Source span of the class itself (for Rationale harvesting later).
    class_line: int = 0
    class_end_line: int = 0
    is_monobehaviour: bool = False
    is_scriptable_object: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "base_class": self.base_class,
            "interfaces": list(self.interfaces),
            "fields": [
                {
                    "name": f.name,
                    "type": f.type_name,
                    "serialized": f.is_serialized,
                    "public": f.is_public,
                    "default": f.default_literal,
                    "line": f.line,
                }
                for f in self.fields
            ],
            "methods": [
                {
                    "name": m.name,
                    "lifecycle": m.is_lifecycle,
                    "line": m.line,
                    "end_line": m.end_line,
                }
                for m in self.methods
            ],
            "get_component_types": list(self.get_component_types),
            "find_object_of_type_types": list(self.find_object_of_type_types),
            "is_monobehaviour": self.is_monobehaviour,
            "is_scriptable_object": self.is_scriptable_object,
            "class_line": self.class_line,
            "class_end_line": self.class_end_line,
        }


@dataclass
class ParsedScript:
    path: Path
    classes: list[ClassInfo] = field(default_factory=list)
    # Field-name -> declared type, assembled across all classes in this
    # file. Used by the builder to resolve receivers in field_method_calls.
    field_types: dict[str, str] = field(default_factory=dict)


def parse_file(path: Path) -> ParsedScript:
    source = path.read_bytes()
    tree = _PARSER.parse(source)
    visitor = _Visitor(source)
    visitor.visit(tree.root_node)
    # Visitor tracks every field's declared type (serialized OR private).
    return ParsedScript(
        path=path,
        classes=visitor.classes,
        field_types=dict(visitor._field_types),
    )


def _text(node: TSNode, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _line_col(node: TSNode) -> tuple[int, int, int, int]:
    """Return (line, col, end_line, end_col) as 1-indexed values."""
    sp = node.start_point
    ep = node.end_point
    return sp[0] + 1, sp[1] + 1, ep[0] + 1, ep[1] + 1


def _snippet(node: TSNode, source: bytes, max_len: int = 140) -> str:
    text = _text(node, source).strip()
    # Collapse multi-line calls into one readable line.
    text = " ".join(text.split())
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


class _Visitor:
    def __init__(self, source: bytes) -> None:
        self.source = source
        self.classes: list[ClassInfo] = []
        self._ns_stack: list[str] = []
        # Field name -> declared type, populated during field parsing so
        # later method-body walks can resolve ``_rigidbody.AddForce(...)``
        # receivers to their declared ``Rigidbody`` type. Scoped per-file
        # (not per-class) which is fine for Unity's one-class-per-file
        # convention; cross-class lookups are rare and handled at builder.
        self._field_types: dict[str, str] = {}

    def visit(self, node: TSNode) -> None:
        t = node.type
        if t in {"namespace_declaration", "file_scoped_namespace_declaration"}:
            name_node = node.child_by_field_name("name")
            ns = _text(name_node, self.source) if name_node else None
            if ns:
                self._ns_stack.append(ns)
            for child in node.children:
                self.visit(child)
            if ns:
                self._ns_stack.pop()
            return

        if t == "class_declaration":
            self._visit_class(node)
            return

        for child in node.children:
            self.visit(child)

    def _visit_class(self, node: TSNode) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        class_name = _text(name_node, self.source)
        namespace = ".".join(self._ns_stack) if self._ns_stack else None

        base_class, interfaces = self._parse_bases(node)
        is_mb = base_class == "MonoBehaviour"
        is_so = base_class == "ScriptableObject"

        line, _col, end_line, _end_col = _line_col(node)
        info = ClassInfo(
            name=class_name,
            namespace=namespace,
            base_class=base_class,
            interfaces=interfaces,
            class_line=line,
            class_end_line=end_line,
            is_monobehaviour=is_mb,
            is_scriptable_object=is_so,
        )

        body = node.child_by_field_name("body")
        if body is not None:
            self._walk_members(body, info)

        self.classes.append(info)

    def _parse_bases(self, class_node: TSNode) -> tuple[str | None, list[str]]:
        base_list = None
        for child in class_node.children:
            if child.type == "base_list":
                base_list = child
                break
        if base_list is None:
            return None, []
        names: list[str] = []
        for child in base_list.children:
            if child.type in {"identifier", "qualified_name", "generic_name"}:
                names.append(_text(child, self.source))
        if not names:
            return None, []
        base = names[0].split(".")[-1]
        interfaces = [n.split(".")[-1] for n in names[1:]]
        return base, interfaces

    def _walk_members(self, body: TSNode, info: ClassInfo) -> None:
        for child in body.children:
            if child.type == "class_declaration":
                # Nested class — visit separately (adds another ClassInfo).
                self._visit_class(child)
            elif child.type == "field_declaration":
                self._parse_field(child, info)
            elif child.type == "method_declaration":
                self._parse_method(child, info)

    def _parse_field(self, node: TSNode, info: ClassInfo) -> None:
        modifiers, attrs = self._collect_modifiers_and_attrs(node)
        is_public = "public" in modifiers
        has_serialize_attr = any(a == "SerializeField" for a in attrs)

        # field_declaration wraps a variable_declaration; the type lives there.
        var_decl = None
        for child in node.children:
            if child.type == "variable_declaration":
                var_decl = child
                break
        if var_decl is None:
            return

        type_node = var_decl.child_by_field_name("type")
        type_name = _text(type_node, self.source) if type_node else "unknown"

        for var in var_decl.children:
            if var.type != "variable_declarator":
                continue
            name_n = var.child_by_field_name("name")
            if name_n is None:
                continue
            field_name = _text(name_n, self.source)
            default = self._extract_default(var)
            is_serialized = is_public or has_serialize_attr
            f_line, f_col, _el, _ec = _line_col(name_n)
            # Always record the field's declared type so the visitor can
            # resolve `_x.Method()` later — even for non-serialized fields.
            self._field_types[field_name] = type_name
            if not is_serialized:
                continue
            info.fields.append(
                FieldInfo(
                    name=field_name,
                    type_name=type_name,
                    is_serialized=is_serialized,
                    is_public=is_public,
                    default_literal=default,
                    line=f_line,
                    col=f_col,
                )
            )

    def _extract_default(self, declarator: TSNode) -> str | None:
        # variable_declarator := name ('=' value)?
        found_eq = False
        for child in declarator.children:
            if found_eq:
                return _text(child, self.source).strip()
            if child.type == "=":
                found_eq = True
        return None

    def _parse_method(self, node: TSNode, info: ClassInfo) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        method_name = _text(name_node, self.source)
        is_lifecycle = method_name in LIFECYCLE_METHODS and info.is_monobehaviour
        m_line, m_col, m_end, _ec = _line_col(node)
        info.methods.append(
            MethodInfo(
                name=method_name,
                is_lifecycle=is_lifecycle,
                line=m_line,
                col=m_col,
                end_line=m_end,
            )
        )

        body = node.child_by_field_name("body")
        if body is not None:
            self._collect_calls(body, info, method_name)

    def _collect_calls(
        self,
        node: TSNode,
        info: ClassInfo,
        containing_method: str,
    ) -> None:
        if node.type == "invocation_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node is not None:
                # 1. Generic calls: GetComponent<T>, FindObjectOfType<T>, etc.
                generic_target = self._extract_generic_call_target(fn_node)
                if generic_target is not None:
                    method, type_arg = generic_target
                    if method in ("GetComponent", "TryGetComponent"):
                        info.get_component_types.append(type_arg)
                        info.get_component_calls.append(
                            self._make_call_site(node, info, containing_method, method, type_arg)
                        )
                    elif method in ("FindObjectOfType", "FindObjectsOfType"):
                        info.find_object_of_type_types.append(type_arg)
                        info.find_object_calls.append(
                            self._make_call_site(node, info, containing_method, method, type_arg)
                        )
                else:
                    # 2. Member-access calls on stored fields: `_foo.Bar(...)`.
                    receiver, member = self._extract_member_call(fn_node)
                    if receiver is not None and member is not None:
                        target_type = self._field_types.get(receiver)
                        if target_type is not None:
                            info.field_method_calls.append(
                                self._make_call_site(
                                    node,
                                    info,
                                    containing_method,
                                    member,
                                    target_type,
                                )
                            )
        for child in node.children:
            self._collect_calls(child, info, containing_method)

    def _make_call_site(
        self,
        node: TSNode,
        info: ClassInfo,
        containing_method: str,
        method: str,
        target: str,
    ) -> CallSite:
        line, col, end_line, end_col = _line_col(node)
        return CallSite(
            method=method,
            target=target,
            line=line,
            col=col,
            end_line=end_line,
            end_col=end_col,
            snippet=_snippet(node, self.source),
            containing_method=containing_method,
            containing_class=info.name,
        )

    def _extract_member_call(self, fn_node: TSNode) -> tuple[str | None, str | None]:
        """For ``receiver.Method(...)``, return (receiver, method) or (None, None).

        Only unwraps one level of member access — ``this._x.Y()`` returns
        (None, None) which is fine; the builder can only resolve simple
        field-scoped receivers anyway.
        """
        if fn_node.type != "member_access_expression":
            return None, None
        receiver_node = fn_node.child_by_field_name("expression")
        name_node = fn_node.child_by_field_name("name")
        if receiver_node is None or name_node is None:
            return None, None
        if receiver_node.type != "identifier":
            return None, None
        return _text(receiver_node, self.source), _text(name_node, self.source)

    def _extract_generic_call_target(self, fn_node: TSNode) -> tuple[str, str] | None:
        target = fn_node
        if target.type == "member_access_expression":
            name = target.child_by_field_name("name")
            if name is not None:
                target = name
        if target.type != "generic_name":
            return None
        # generic_name := identifier type_argument_list
        method_name = None
        type_args = None
        for child in target.children:
            if child.type == "identifier":
                method_name = _text(child, self.source)
            elif child.type == "type_argument_list":
                type_args = child
        if method_name is None or type_args is None:
            return None
        # pick first non-punctuation type argument
        for c in type_args.children:
            if c.type not in {"<", ">", ","}:
                return method_name, _text(c, self.source).split(".")[-1]
        return None

    def _collect_modifiers_and_attrs(self, node: TSNode) -> tuple[set[str], list[str]]:
        modifiers: set[str] = set()
        attrs: list[str] = []
        for child in node.children:
            if child.type == "modifier":
                modifiers.add(_text(child, self.source))
            elif child.type == "attribute_list":
                for a in child.children:
                    if a.type == "attribute":
                        name = a.child_by_field_name("name")
                        if name is not None:
                            attrs.append(_text(name, self.source).split(".")[-1])
        return modifiers, attrs
