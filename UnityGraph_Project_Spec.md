

**UNITYGRAPH**

*Autonomous Unity Developer System*

Complete Three-Layer Project Specification

| LAYER 1 *Knowledge Graph* | LAYER 2 *Injection Engine* | LAYER 3 *Behavior Model* |
| :---: | :---: | :---: |

*Architecture delegated to Claude Code per layer*

Version 1.0  —  April 2026

# **0\.  Project Overview**

## **0.1  The Vision**

UnityGraph is a three-layer system that makes Claude Code a fully competent Unity developer. Today, Claude Code cannot see Unity scenes, prefabs, Inspector values, or component relationships. A developer must manually bridge this gap by pasting screenshots and explaining what is in the scene. UnityGraph eliminates that bottleneck entirely.

The end state of three layers: a developer opens Claude Code in their Unity project, asks a question or gives a task, and Claude Code reasons correctly about the entire project — scenes, scripts, prefabs, animations, and runtime relationships — with no human intervention required.

## **0.2  The Core Problem Statement**

Claude Code, without any scene context, produces incorrect Unity code because it cannot see:

* Which components are attached to which GameObjects

* Inspector-overridden values that contradict code defaults

* Co-component dependencies (what else lives on the same object)

* UnityEvent connections between objects across the scene

* Prefab variant inheritance chains

* Animation state machine transitions and trigger conditions

When a developer adds a screenshot and manually explains the scene, Claude Code immediately performs dramatically better. The problem is not model capability. It is missing context. UnityGraph automates that context supply.

## **0.3  System Philosophy**

| Principle | Meaning |
| ----- | ----- |
| Claude Code is the architect | For each layer, Claude Code decides the internal architecture, file structure, class design, and implementation patterns. This document defines WHAT each layer must do, not HOW. |
| Layers are independent | Each layer is a standalone Python package. They connect through well-defined interfaces: graph.json, MCP tools, and the behavior log. |
| Research emerges from operation | The system generates its own research evidence as it runs. Every Claude Code session that uses the system produces data for the PhD. |
| Ship, then refine | Each layer ships as a working product before the next layer begins. Layer 1 is complete before Layer 2 is designed. |

## **0.4  How the Three Layers Connect**

The layers form a pipeline. Each layer consumes the output of the layer below it and provides input to the layer above it.

| Unity Project (raw files)     |     v \[ LAYER 1: Knowledge Graph Builder \]     Reads: .unity, .prefab, .cs, .controller, .shadergraph     Outputs: graph-out/graph.json     |     v \[ LAYER 2: Context Injection Engine \]     Reads: graph.json \+ developer task     Outputs: structured context block injected into Claude Code prompt     |     v \[ LAYER 3: Behavior Model \]     Reads: Claude Code outputs \+ ground truth \+ Layer 2 injection decisions     Outputs: failure pattern map \-\> makes Layer 2 smarter over time     |     v Claude Code: now sees the full project, codes correctly, no human bridging required |
| :---- |

| L1 | The Knowledge Graph *Giving Claude Code eyes on the Unity project* |
| :---: | :---- |

## **1.1  What Layer 1 Does**

Layer 1 reads a Unity project folder and produces a single file: graph.json. This file is a complete semantic map of the project — every script, every scene, every prefab, every component attachment, every Inspector value, every event connection. It is the ground truth that all other layers depend on.

Layer 1 runs as a command-line tool from outside the Unity project. It does not require Unity Editor to be open. It does not install any Unity package. It simply reads files.

## **1.2  What Claude Code Will Decide**

| Architecture delegated to Claude Code Internal folder and module structure of the Python package Whether to use a class-based or functional design for each parser How to handle large projects efficiently (streaming, chunking, caching strategy) The exact JSON schema for graph.json (structure of nodes and edges) Error handling and partial-parse recovery when Unity YAML is malformed Testing framework and test fixtures CLI interface design and argument parsing |
| :---- |

## **1.3  Artifacts to Parse**

Layer 1 must parse the following Unity artifact types. The parsing depth for each is defined below.

| Artifact | Extension | What to Extract |
| ----- | ----- | ----- |
| C\# Scripts | .cs | Class name, base class, interfaces, fields with \[SerializeField\], public fields, methods, MonoBehaviour lifecycle hooks (Awake/Start/Update/etc), method calls, event subscriptions, coroutines, GetComponent calls, FindObjectOfType calls |
| Unity Scenes | .unity | GameObject names and IDs, component list per GameObject, component field values as set in Inspector, parent-child hierarchy, active/inactive state, tag and layer, scene name |
| Prefab Files | .prefab | Same as scenes plus: which prefab this is a variant of, which fields are overridden from the base prefab, nested prefab references |
| Animator Controllers | .controller | All animation states, entry and exit states, transitions between states (conditions, triggers, thresholds), parameter names and types |
| Shader Graphs | .shadergraph | Input ports, output ports, keyword definitions, sub-graph references |
| Script Execution Order | ProjectSettings | Script execution order overrides (which scripts run before others) |

## **1.4  The Graph Schema (Requirements)**

Claude Code will design the exact schema. The following defines the required semantic content — what must be expressible, not the exact field names.

### **Node Types Required**

* **Script — represents a .cs file / class**

  * Name, file path, type (MonoBehaviour / ScriptableObject / plain class / interface)

  * List of lifecycle methods present

  * List of serialized fields with their type and default value

* **GameObject — represents an object in a scene or prefab**

  * Name, scene or prefab origin, active state, tag, layer

* **Component — represents a Unity built-in component (Rigidbody, Collider, etc.)**

  * Type name, Inspector values as key-value pairs

* **AnimState — represents a state in an AnimatorController**

* **Scene — represents a .unity scene file**

* **Prefab — represents a .prefab asset**

### **Edge Types Required**

* **attached\_to — Script or Component is attached to a GameObject**

* **co\_exists\_with — two components live on the same GameObject**

* **calls — method in Script A calls method in Script B**

* **subscribes\_to — Script subscribes to a UnityEvent on another object**

* **depends\_on — Script calls GetComponent\<T\> expecting T to exist**

* **inherits — class inheritance**

* **instantiates — script calls Instantiate with a prefab reference**

* **is\_variant\_of — prefab variant relationship**

* **overrides — prefab variant overrides a field from base prefab**

* **transitions\_to — animation state machine transition**

* **loads\_scene — script calls SceneManager.LoadScene**

## **1.5  CLI Interface (Requirements)**

The tool must be callable from the command line inside any Unity project folder. Claude Code will design the exact CLI structure. The following capabilities are required:

| unitygraph build .                   \# build graph from current folder unitygraph build ./Assets            \# build graph from specific subfolder unitygraph build . \--update          \# only re-process changed files unitygraph build . \--output ./out    \# custom output directory unitygraph query 'PlayerController'  \# query the graph from terminal unitygraph serve ./graph-out/graph.json  \# start MCP server |
| :---- |

## **1.6  MCP Server Interface (Requirements)**

Layer 1 must ship with an MCP server that exposes the graph as queryable tools for Claude Code. Claude Code will design the server implementation. The following tools must be exposed:

| MCP Tool | Input | Returns |
| ----- | ----- | ----- |
| get\_components | gameobject\_name: string | List of all components attached to that GameObject, including both scripts and Unity built-ins |
| get\_inspector\_values | component\_name: string, gameobject\_name: string | All Inspector-set field values for that component on that object |
| get\_scene\_graph | scene\_name: string | Full GameObject hierarchy for the scene as a nested structure |
| find\_script\_usages | script\_name: string | All GameObjects that have this script attached, across all scenes and prefabs |
| get\_event\_connections | gameobject\_name: string | All UnityEvent connections from or to this object |
| get\_prefab\_chain | prefab\_name: string | The full variant inheritance chain for this prefab |
| get\_neighbors | node\_id: string, hops: int | All graph nodes within N hops of the given node |
| shortest\_path | from: string, to: string | The shortest path through the graph between two nodes |
| query\_graph | natural\_language\_query: string | Relevant subgraph for the query, token-budget aware |

## **1.7  Integration into Claude Code (How It Connects)**

Three files connect Layer 1 to Claude Code. None of them require modifying the Unity project source:

### **CLAUDE.md (placed in Unity project root)**

| \#\# UnityGraph Knowledge System This project has a live knowledge graph at graph-out/graph.json. BEFORE answering any question about this project: 1\. Call get\_components() for any GameObject mentioned in the task 2\. Call get\_inspector\_values() for components you plan to modify 3\. Call get\_event\_connections() if the task involves UI, triggers, or events 4\. Never assume a script's behavior from code alone 5\. Inspector values override code defaults \- always check the graph first The graph is ground truth for scene structure. Code is ground truth for logic. Use both. |
| :---- |

### **.mcp.json (placed in Unity project root)**

| {   "mcpServers": {     "unitygraph": {       "type": "stdio",       "command": "python",       "args": \["-m", "unitygraph.serve", "graph-out/graph.json"\]     }   } } |
| :---- |

## **1.8  Research Contribution of Layer 1**

Layer 1 is the empirical foundation of the PhD. The research question it answers:

| Research Question L1 What is the minimal graph schema that captures enough Unity-specific semantics to make LLM tasks correct, and how does this schema differ structurally from a standard code dependency graph? |
| :---- |

The evidence Layer 1 produces: a comparison between LLM performance on Unity tasks with code-only context vs. graph-augmented context. Every query Claude Code makes through the MCP server is a data point.

## **1.9  Layer 1 Success Criteria**

* graph.json is produced for any valid Unity project without error

* MCP server starts and all 9 tools respond correctly

* Claude Code resolves a bug it previously failed on using only MCP tool calls (no screenshot)

* Graph build time under 60 seconds for a project with 50+ scripts and 5+ scenes

* Incremental update (--update flag) processes only changed files

| L2 | The Injection Engine *Getting the right context to Claude Code at the right time* |
| :---: | :---- |

## **2.1  What Layer 2 Does**

Layer 1 builds a complete graph. Layer 2 solves the next problem: the full graph is too large to put in a prompt. Claude Code has a context window. You cannot dump everything into it. Layer 2 decides what part of the graph is relevant to a specific task, retrieves that subgraph, and formats it as a structured context block that Claude Code can use.

Layer 2 is the intelligence between the knowledge base and the LLM. It is what transforms a static data file into a dynamic, task-aware context supply system.

## **2.2  What Claude Code Will Decide**

| Architecture delegated to Claude Code Entity extraction strategy: how to identify which graph nodes are relevant to a task description Retrieval algorithm: BFS vs DFS vs semantic similarity vs task-type heuristics Context formatting: how to serialize a subgraph into a prompt-friendly string Token budget management: how to trim context when it exceeds limits Ranking: when multiple subgraphs are candidates, which to prioritize Caching: whether to cache subgraphs for repeated similar tasks Confidence scoring: how to communicate uncertainty about retrieved context |
| :---- |

## **2.3  The Task-Context Matching Problem**

Given a developer task, Layer 2 must determine: which nodes and edges in the graph are relevant to this task? This is non-trivial. The same script may be relevant to many different tasks for different reasons.

### **Three Retrieval Strategies (all must be supported)**

| Strategy | When to Use | How It Works |
| ----- | ----- | ----- |
| Entity-hop | Task mentions specific GameObjects, scripts, or components by name | Extract named entities from the task text. Retrieve all graph nodes within N hops of those entities. N is configurable. |
| Task-type | Task type is recognizable (bug fix, new feature, refactor, explain) | Map task type to a predefined set of relevant edge types. A collision bug always needs: Rigidbody, Collider, trigger/collision scripts, co-components. |
| Full neighborhood | Task is ambiguous or involves an unknown area of the project | Return the subgraph of god nodes (highest degree nodes) plus the 1-hop neighborhood of the mentioned script. |

## **2.4  Context Formatting (Requirements)**

The output of Layer 2 is a structured text block injected into Claude Code’s prompt. Claude Code will design the exact format. The following content is required in all context blocks:

| \=== UNITYGRAPH CONTEXT \=== TASK-RELEVANT SCENE DATA \------------------------ GameObject: Player   Components: \[PlayerController, Rigidbody, CapsuleCollider, HealthSystem, AudioSource\]   PlayerController Inspector values:     \_speed: 5.0  (code default: 5.0)     \_jumpForce: 8.0  (code default: 8.0)     \_maxHealth: 100  (code default: 100\) COMPONENT RELATIONSHIPS \----------------------- PlayerController.Update() \-\> Rigidbody.AddForce()  \[depends\_on\] PlayerController subscribes to HealthSystem.OnDeath  \[subscribes\_to\] Button\_Attack.onClick \-\> CombatManager.TriggerAttack()  \[event\_connection\] PREFAB CHAIN \------------ Player (scene instance) \<- PlayerBase.prefab   Override: \_maxHealth \= 75 (base was 100\) LIFECYCLE NOTES \--------------- HealthSystem runs before PlayerController (Script Execution Order) EnemySpawner.Awake() calls FindObjectOfType\<GameManager\>() GRAPH CONFIDENCE: HIGH (all data EXTRACTED from scene files) TOKEN USAGE: 340 tokens \========================= |
| :---- |

## **2.5  UnityBench: The Evaluation Dataset**

Layer 2 requires an evaluation dataset to measure whether injection improves Claude Code performance. This dataset is also the primary research output — the first paper.

### **Dataset Structure**

UnityBench consists of Unity tasks organized into three tiers of increasing context-dependence:

| Tier | Name | Description | N Tasks |
| ----- | ----- | ----- | ----- |
| 1 | Isolated Script | Task solvable from code alone. No scene context needed. Establishes baseline. | 40 |
| 2 | Cross-Artifact | Task requires knowing scene structure. Code alone is insufficient. Core evaluation tier. | 60 |
| 3 | Full Project | Task requires understanding architectural patterns across multiple scenes and systems. | 20 |

### **Three Experimental Conditions**

| Condition | What Claude Code Receives | Expected Performance |
| ----- | ----- | ----- |
| Baseline | Code only. No scene data. | High on Tier 1, low on Tier 2 and 3\. |
| Manual Visual | Code \+ developer-written screenshot description. Human-in-the-loop. | High across all tiers. Upper bound. |
| UnityGraph Injection | Code \+ Layer 2 auto-generated context block. | Target: matches Manual Visual on Tier 2 and 3\. |

### **Evaluation Metrics**

* Runtime Correctness — does the generated code compile and run correctly in Play Mode (automated via Unity Test Runner)

* Component Awareness Score — does the solution correctly account for other components on the same GameObject

* Lifecycle Correctness — does the solution respect Unity’s execution order and avoid order-dependent bugs

* Inspector Awareness — does the solution correctly use Inspector-set values rather than code defaults

* Token Efficiency — how many tokens of context were injected vs how much was actually used

## **2.6  Research Contribution of Layer 2**

| Research Question L2 Which graph retrieval strategies produce the best LLM performance on Unity tasks, and at what token cost? Does automated graph injection match human-supplied visual context? |
| :---- |

Layer 2 produces the first full paper: UnityBench, the dataset and benchmark for LLM performance on Unity-specific code tasks. This paper proves the scene-code gap empirically and demonstrates that structured graph injection closes it.

## **2.7  Layer 2 Success Criteria**

* All three retrieval strategies implemented and selectable

* Context blocks generated in under 2 seconds for any task

* Claude Code performance on Tier 2 tasks improves by at least 30% over baseline condition

* UnityBench dataset: 120 tasks with ground truth, across at least 3 different Unity projects

* Token usage of injected context does not exceed 1500 tokens for standard tasks

| L3 | The Behavior Model *Learning how Claude Code thinks in Unity* |
| :---: | :---- |

## **3.1  What Layer 3 Does**

Layers 1 and 2 are passive systems. They build a graph and they retrieve from it. Layer 3 is active. It watches what Claude Code does, records what assumptions Claude Code makes that turn out to be wrong, and uses those observations to make Layer 2 smarter over time.

This is the novel layer. No existing research system does this for a domain-specific coding context. The insight is simple: Claude Code has learnable, predictable blind spots specific to Unity C\#. Layer 3 maps those blind spots and preemptively injects the context that counteracts them.

## **3.2  What Claude Code Will Decide**

| Architecture delegated to Claude Code How to intercept and log Claude Code outputs during active sessions What data structure to use for the failure pattern map The comparison algorithm for output-vs-ground-truth delta extraction How to represent a 'failure pattern' (task type \+ missing context type \+ fix) When a pattern has enough evidence to be promoted to an active injection rule How patterns decay or are invalidated as the project evolves The interface between Layer 3 pattern map and Layer 2 retrieval strategy selection |
| :---- |

## **3.3  The Observation Loop**

Layer 3 operates on a simple three-step loop that runs every time Claude Code works on a Unity task:

| STEP 1: OBSERVE   Claude Code receives task \+ Layer 2 context injection   Claude Code produces output (code changes, explanation, or fix)   Layer 3 logs: { task\_text, injected\_context, claude\_output, timestamp } STEP 2: COMPARE   Developer accepts or rejects Claude Code output   If rejected / corrected: Layer 3 records the delta     What did Claude Code assume that was wrong?     What scene data would have prevented the error?     Which Layer 2 context type was missing?   If accepted: Layer 3 records what context was most used STEP 3: UPDATE   Layer 3 adds an entry to the failure pattern map:     { pattern: 'collision\_bug \+ no\_rigidbody\_check',       missing\_context: 'parent\_component\_data',       fix: 'always inject 2-hop parent context for collision tasks',       confidence: 0.73,       evidence\_count: 12 }   Next time Layer 2 handles a collision task:     Layer 3 says: also inject parent component data     Layer 2 follows the rule |
| :---- |

## **3.4  The Failure Pattern Map**

The failure pattern map is the core data structure of Layer 3\. It is a persistent, growing database of observed Claude Code failure modes in Unity, each paired with the injection rule that prevents recurrence.

### **Pattern Schema (requirements)**

Claude Code will design the exact schema. The following fields are required per pattern entry:

| Field | Type | Description |
| ----- | ----- | ----- |
| pattern\_id | string | Unique identifier |
| task\_type | enum | bug\_fix / new\_feature / refactor / explain / test |
| trigger | string | The code pattern or task description feature that activates this rule |
| missing\_context\_type | enum | Which type of graph data was absent: parent\_component / inspector\_value / event\_connection / lifecycle\_order / prefab\_override / etc. |
| injection\_rule | string | What Layer 2 should additionally inject when this pattern activates |
| confidence | float 0-1 | Proportion of observations where this rule produced correct output |
| evidence\_count | int | Number of sessions that contributed to this pattern |
| last\_seen | datetime | When this pattern was last triggered |
| project\_scope | enum | Whether this pattern is project-specific or general Unity |

## **3.5  Known Claude Code Unity Blind Spots (Seed Patterns)**

Based on direct developer observation (the pilot study), the following failure patterns are known before Layer 3 begins running. These are pre-seeded into the pattern map as starting rules with low confidence, to be validated or invalidated by observation:

| Pattern Name | Trigger | Missing Context | Pre-seed Rule |
| ----- | ----- | ----- | ----- |
| Implicit Rigidbody | Script calls AddForce or velocity. Task involves physics. | Whether Rigidbody is on same object, parent, or missing entirely. | Always inject co-component and parent-component data for physics scripts. |
| Inspector Override Blindness | Script has \[SerializeField\] fields. Task involves tuning or values. | Inspector-set values that differ from code defaults. | Always inject Inspector values for all \[SerializeField\] fields on mentioned scripts. |
| Lifecycle Race | Two scripts both referenced. Task involves initialization or null refs. | Script Execution Order settings. | Always inject lifecycle order data when multiple scripts interact. |
| Coroutine Destroy | Script uses StartCoroutine. Task involves object lifecycle. | Whether object can be destroyed mid-coroutine. | Inject active-state and destruction-pattern data for coroutine scripts. |
| Event Connection Gap | Script references UI Button or custom UnityEvent. Task involves UI. | What is connected to that event in the scene. | Always inject full event connection map for any object with event fields. |
| Prefab Override Surprise | Script is on a prefab. Task involves a specific scene instance. | Whether scene instance overrides any prefab field values. | Inject prefab override data for any task involving a prefab-sourced object. |

## **3.6  The Feedback Interface**

Layer 3 requires a lightweight mechanism for developers to signal whether Claude Code output was correct or not. This is the observation signal. Claude Code will design the exact interface. The following modes must be supported:

* Explicit feedback — developer runs: unitygraph feedback \--correct or \--incorrect after each Claude Code session

* Implicit feedback — if Claude Code output is applied to the project and the graph changes as a result, Layer 3 infers acceptance

* Correction capture — if developer rewrites Claude Code output, Layer 3 diffs the original vs corrected and extracts the delta automatically

## **3.7  Research Contribution of Layer 3**

| Research Question L3 Can a behavioral model of LLM domain-specific priors, learned from observed failures, produce measurably better context injection than static retrieval strategies alone? Which failure patterns are universal across Unity projects vs project-specific? |
| :---- |

Layer 3 is the flagship research paper. The novel claim: an external behavioral model of an LLM, learned from observed failures in a specific domain, improves that LLM's performance measurably — without fine-tuning, without modifying the model, and without human intervention per task.

This is directly comparable to proactive agent research (ContextAgent, 2025\) and behavioral fingerprinting research (2025), but applied to a coding context with a domain-specific knowledge graph. No existing paper makes this claim for a game engine context.

## **3.8  Layer 3 Success Criteria**

* Observation loop captures output from all Claude Code Unity sessions automatically

* Failure pattern map populated with at least 10 distinct patterns after 50 sessions

* Claude Code performance on Tier 2 UnityBench tasks improves further (beyond Layer 2 baseline) after Layer 3 activates

* At least 3 of the 6 pre-seeded patterns confirmed with confidence \> 0.6 by observation

* Pattern map distinguishes project-specific patterns from general Unity patterns

# **4\.  Build Order and Layer Dependencies**

## **4.1  Strict Build Sequence**

Layers are built strictly in order. Layer N is not started until Layer N-1 meets its success criteria. This is not a timeline constraint — it is a dependency constraint. Each layer depends on the layer below being complete and working.

1. Layer 1 complete: graph.json builds correctly for a test Unity project. MCP server runs and all 9 tools respond.

2. Layer 1 integrated: Claude Code in a real Unity project uses MCP tools and solves a bug it previously failed on.

3. Layer 2 complete: injection pipeline running. Context blocks generated for tasks. UnityBench Tier 1 and Tier 2 evaluated.

4. Layer 2 validated: 30%+ improvement over baseline confirmed on Tier 2 tasks.

5. Layer 3 complete: observation loop running. Failure pattern map accumulating. Layer 2 injection influenced by Layer 3 rules.

6. Layer 3 validated: measurable further improvement over Layer 2 baseline confirmed.

## **4.2  What Stays Fixed vs What Evolves**

| Component | Fixed at Layer 1? | Evolves in Later Layers? |
| ----- | ----- | ----- |
| graph.json schema | Core structure fixed | New node/edge types added as needed |
| MCP tool interface | Fixed at Layer 1 | New tools may be added in Layer 2 |
| CLAUDE.md content | Template fixed at Layer 1 | Updated with Layer 2 and 3 instructions |
| UnityBench dataset | Not created in Layer 1 | Created in Layer 2, used in Layer 3 evaluation |
| Failure pattern map | Not created in Layer 1 or 2 | Created and grown in Layer 3 |
| Retrieval strategy | Not created in Layer 1 | Static in Layer 2, dynamic in Layer 3 |

# **5\.  Research Contribution Summary**

This section summarizes the academic contributions of the three-layer system as a whole.

| Layer | Research Claim | Evidence | Target Venue |
| ----- | ----- | ----- | ----- |
| L1 | Unity projects require a fundamentally different graph schema from standard code dependency graphs, due to the scene-code separation and Inspector-runtime duality. | Comparative schema analysis. Graph structure statistics across 10+ Unity projects. | MSR / FSE |
| L2 | Automated structured graph injection closes the performance gap between LLMs with code-only context and LLMs with human-supplied visual scene context, on Unity-specific tasks. | UnityBench: 120 tasks, 3 conditions, 3 metrics, automated evaluation via Unity Test Runner. | ASE / ICSE |
| L3 | An external behavioral model of an LLM's domain-specific prior assumptions, learned from observed failures, produces measurably better context injection than static retrieval strategies. | Ablation: Layer 2 static injection vs Layer 3 adaptive injection on same task set. Pattern map analysis. | ICSE / NeurIPS |

## **5.1  The Thesis Statement**

| Thesis The performance gap between LLMs on Unity development tasks is not a model capability problem. It is a structured context availability problem caused by the multi-artifact, scene-code-separated nature of game engine projects. We demonstrate this gap empirically (Layer 2), propose a knowledge graph system that closes it automatically (Layers 1 and 2), and show that a behavioral model of LLM domain-specific priors further improves performance beyond static injection (Layer 3\) — establishing a new paradigm for adaptive, LLM-aware context supply in specialized software engineering domains. |
| :---- |

# **6\.  Product Strategy**

Each layer ships as a RinvalAI product independently. Research validates the product. The product funds the research.

| Layer | Product | Distribution | Revenue Model |
| ----- | ----- | ----- | ----- |
| Layer 1 | unitygraph CLI \+ MCP server. Open source. | GitHub, PyPI. Graphify-style install. | Open source / credibility / citations |
| Layer 2 | Unity-aware Claude Code skill. Similar to graphify but Unity-specific. | Source code sale. One-time purchase. | One-time source code license |
| Layer 3 | Adaptive injection layer. Premium version of Layer 2\. | Source code sale. Higher price point. | One-time premium license |
| All 3 | Complete UnityGraph system. | Bundle sale. Includes all layers and UnityBench dataset. | Bundle license \+ commercial use rights |

*UnityGraph Project Specification v1.0  —  April 2026*