# UnityGraph

Autonomous Unity developer system for Claude Code. Three layers that give Claude Code full context about a Unity project so it can reason correctly about scenes, prefabs, Inspector values, and component relationships — without a human bridging the gap.

- **Layer 1** — Knowledge Graph Builder + MCP server
- **Layer 2** — Context Injection Engine (UnityBench benchmark)
- **Layer 3** — Behavior Model (failure pattern map → adaptive injection)

## Status

Under active development. See [`UnityGraph_Project_Spec.md`](UnityGraph_Project_Spec.md) for the full specification and [`UnityGraph_Development_Plan.md`](UnityGraph_Development_Plan.md) for the iteration plan.

Currently at: **Iteration 0 — bootstrap**.

## Install (dev)

```bash
pip install -e ".[dev]"
unitygraph --help
```

## Layout

```
src/unitygraph/     # package source
fixtures/           # test Unity projects
tests/              # pytest suite
evals/              # UnityBench + result runners (added in I5)
```

## License

Layer 1 is MIT. Layers 2 and 3 ship under a separate commercial license once released.
