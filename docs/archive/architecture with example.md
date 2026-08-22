1) Cognitive Input Processor
1. Component Explanation & Architecture

What it is:
This is the front-end text normalization and signal-preservation layer. It is supposed to clean input while preserving whether the student is asking a question, attempting an answer, explaining, expressing confusion, shifting topic, or making a transfer attempt. The architecture explicitly says not to collapse the utterance into one label too early.

Architecture:
Input comes from the chat/UI layer, output goes to the cognitive analyzer. Its job is to preserve multiple simultaneous signals from one utterance so later stages can reason over them. The build plan indicates this layer already exists in heuristic form and is meant to be upgraded by a semantic classifier protocol.

2. Purpose & Impact (Why & How)

Why it is required:
Student utterances are ambiguous and multi-purpose. A single message can contain a question, a tentative answer, and a misconception clue at once. If you flatten that into one intent label, you destroy pedagogy-relevant information.

How it helps:
It preserves evidence before the system commits to a pedagogical move. That is mechanically useful because later stages need to decide whether to explain, probe, hint, or redirect based on the mix of signals.

Building a Better Model:
Compared with a standard intent router, this improves recall of learning signals. It is the right first move in a tutor architecture because it prevents premature compression of student evidence.

3. Real-World Example

A student says: “I think it is because resistance is high, but why does current reduce?” The processor should preserve both “answer attempt” and “question/confusion,” not force a single label. That is exactly the kind of mixed utterance the document calls out.
2) Cognitive Analyzer Layer
1. Component Explanation & Architecture

What it is:
This is the central perception layer that estimates confusion, confidence, curiosity, misconception likelihood, transfer attempt, abstraction attempt, self-correction, explanation quality, and cognitive load. The architecture says it is the central replacement for the intent router.

Architecture:
Input comes from the cognitive input processor. Output is a structured “Student Cognitive Update,” not a single intent. In the newer implementation notes, this layer is feature-flagged and can be backed by Gemini 2.5 Flash, with local MiniLM-based components retired from the runtime path.

2. Purpose & Impact (Why & How)

Why it is required:
The system needs to infer the student’s mental activity before deciding what to teach next. A learning system cannot behave like a standard FAQ bot because educational value depends on the learner’s state, not just the topic.

How it helps:
It converts raw language into continuous state variables that later stages can act on. This is much better than a hard intent label because confusion, curiosity, and transfer attempt can coexist.

Building a Better Model:
This is the core conceptual upgrade from “router-first” to “student-model-first.” It is the backbone that makes the rest of the architecture meaningful.

3. Real-World Example

If a student says, “I can solve the equation, but I still do not understand why the graph bends like that,” the analyzer should infer moderate-to-high mastery on equations, low graph understanding, and a representation gap. The architecture explicitly uses this kind of example.
3) Concept Resolver
1. Component Explanation & Architecture

What it is:
This maps student utterances to curriculum concepts. It resolves concept names using semantic similarity and prefers foundational concepts when the query is ambiguous.

Architecture:
Input is the utterance plus the current concept context. Output is a concept ID, confidence, secondary concepts, and a reason. The doc also states that concept resolution must operate in text space using concept-card fields, not graph embeddings.

2. Purpose & Impact (Why & How)

Why it is required:
A tutor must know what mathematical idea the student is talking about, especially when the student uses vague or indirect references. Without concept resolution, the rest of the system cannot retrieve the correct prerequisites, examples, or misconception interventions.

How it helps:
It grounds later retrieval in the curriculum structure rather than in surface keywords. That is what keeps the tutor from hallucinating topic switches. The build report explicitly says the resolver can output INHERIT_CURRENT_CONCEPT to prevent hallucinated topic switches.

Building a Better Model:
It turns a chat system into a curriculum-indexed tutor. That is necessary for any meaningful pedagogy-first design.

3. Real-World Example

If a student says they are “substituting one variable and sign change while solving a pair,” the resolver should map that to substitution method and related pair-of-linear-equations concepts, exactly like the sample output in the doc.
4) Learner State Model
1. Component Explanation & Architecture

What it is:
This is the authoritative memory of the student. It stores per-concept mastery, misconception status, representation coverage, hint dependency, cold recall, transfer readiness, confidence trend, and session-level no-repeat state. Global fields include engagement, mood proxy, cognitive load, frustration risk, persistence, response latency pattern, and rolling HOPE scores.

Architecture:
It receives inferred signals from the analyzer and evidence-based updates from write-back APIs such as apply_bridge_result and apply_probe_result. The docs emphasize that state changes are driven by evidence, not inference alone.

2. Purpose & Impact (Why & How)

Why it is required:
A mastery score alone is not enough. Two students can both show “0.8 mastery” while one still holds a dangerous misconception. The model therefore stores misconception state and representation coverage separately.

How it helps:
It supports persistent, longitudinal adaptation. It also lets the tutor decide whether to bridge prerequisites, review a misconception, or move forward. The write-back APIs convert the system from a stateless responder into a closed-loop teaching machine.

Building a Better Model:
This is the most important part of the architecture. Everything else is subordinate to keeping a truthful student state.

3. Real-World Example

A student may repeatedly solve quadratic equations correctly but still fail on graph interpretation. The state model can reflect “equation mastery high, graph representation missing, transfer readiness low,” which is pedagogically actionable. The doc gives this exact style of example.
5) Curriculum Knowledge Graph
1. Component Explanation & Architecture

What it is:
This is the curriculum structure: concepts, prerequisites, representations, misconceptions, applications, transfer links, integration links, CT probes, metacognitive prompts, and difficulty. It is implemented in rag_store/concepts.json and graph.json.

Architecture:
The graph feeds retrieval and pedagogy decisions. It anchors the tutoring system to NCERT-aligned content and determines what can be taught next. The build plan shows this is the central data substrate and is already done.

2. Purpose & Impact (Why & How)

Why it is required:
Tutoring requires prerequisite structure. The architecture needs to know what the student must know before a given topic, what misconceptions are common, and what representations support learning.

How it helps:
It makes retrieval pedagogically meaningful, not just semantically relevant. You are not retrieving “any relevant chunk,” but the right explanation, bridge, example, or counterexample for the learner’s state.

Building a Better Model:
This is what stops the system from becoming a generic RAG bot. It gives the tutor structure, sequence, and intervention logic.

3. Real-World Example

For a concept like quadratic roots, the graph can include prerequisites, solved examples, misconception nodes like sign errors, and CT probes like “what happens if the discriminant is negative?” That is far more useful than plain paragraph retrieval.
6) Pedagogical Decision Engine / Policy
1. Component Explanation & Architecture

What it is:
This selects the tutor action: explain, quiz, hint, counterexample, transfer, review, encourage, or related actions. The doc describes a rule-based engine with a neural shadow policy running alongside it.

Architecture:
It consumes learner state and cognitive signals, then chooses a pedagogical move. The shadow policy logs suggestions for offline optimization and is not yet authoritative.

2. Purpose & Impact (Why & How)

Why it is required:
The tutor must decide not just what to say, but what teaching move is best now. Pedagogy is a control problem, not just a generation problem.

How it helps:
The policy turns learner signals into action selection. This is how the system decides between a worked example and a misconception probe, or between a bridge recap and a forward move.

Building a Better Model:
This is the bridge from perception to intervention. Without it, state tracking remains inert.

3. Real-World Example

If a student shows high curiosity but low confidence, the policy might choose encourage plus scaffolded explanation. If a misconception is suspected, it should choose probe-before-correct instead of immediate correction.
7) Retrieval Layer
1. Component Explanation & Architecture

What it is:
This retrieves NCERT-grounded evidence, schema methods, worked examples, bridge recaps, and misconception support using learner-state-aware ranking and a provenance manifest. The architecture explicitly says retrieval is gated by bridge logic and cohesion checks.

Architecture:
Inputs: concept, learner state, policy action, and HOPE signals. Outputs: evidence bundles for response generation, with provenance attached. The build plan says the retrieval layer is already implemented with a 7-term ranking scheme.

2. Purpose & Impact (Why & How)

Why it is required:
Retrieval ensures grounded answers and prevents the LLM from freelancing. The document explicitly constrains response generation to draft only from retrieved provenance.

How it helps:
It selects evidence that matches not just the concept, but the learner’s current weakness, prior misconceptions, and prerequisite gaps. This is much more useful than generic similarity search.

Building a Better Model:
It makes the system evidence-sensitive, which is essential for a tutor that must explain, diagnose, and verify.

3. Real-World Example

If the student is weak on Class-9 prerequisites, the retrieval layer prepends a bridge recap and diagnostic question before the Class-10 content. The document gives exactly that gating behavior.
8) Response Layer / Generation
1. Component Explanation & Architecture

What it is:
This is the final explanation/hint/question/correction/challenge output. The response generator is constrained to use only retrieved evidence rather than general model memory.

Architecture:
It receives the selected evidence bundle and the pedagogical action, then generates the actual student-facing response. The older report says local Qwen-2.5-3B-Instruct is used; later notes mention Gemini as a possible backend under feature flags.

2. Purpose & Impact (Why & How)

Why it is required:
A student-facing response is the visible output of the whole pipeline. If generation is unconstrained, the system becomes a hallucination engine.

How it helps:
By limiting the response to provenance-backed claims, the system is more faithful, more auditable, and easier to debug.

Building a Better Model:
This turns retrieval and pedagogy into actual learning output rather than background metadata.

3. Real-World Example

If a student is wrong about why current changes, the response should explain the retrieved rule, reference the relevant evidence, and ask a diagnostic follow-up rather than dumping a generic paragraph.
9) HOPE Metrics Suite
1. Component Explanation & Architecture

What it is:
HOPE is the document’s framework for high-order learning signals: Knowledge Integration, Knowledge Transfer, Critical Thinking, Persistence, and Cognitive Load. It is operationalized through ordinal heads over answer embeddings plus scalar features.

Architecture:
The HOPE detector consumes prompt, answer, rubric anchors, and scalar features, outputs ordinal scores, and folds them into rolling learner state. The build plan says these detectors are already wired into runtime and used by retrieval ranking.

2. Purpose & Impact (Why & How)

Why it is required:
The architecture wants to distinguish memorization from genuine understanding. That is a legitimate problem; rote correctness is not the same as transfer or integration.

How it helps:
It provides a signal beyond correctness: can the learner connect representations, transfer knowledge, or think critically? That directly improves pedagogy selection.

Building a Better Model:
This is the mechanism that tries to prevent the tutor from over-rewarding shallow recall.

3. Real-World Example

A student may give a correct formula-based answer but fail a transfer probe that asks for application in a new context. HOPE should score that as weak transfer even though the answer was “correct.” The doc explicitly builds for that distinction.
10) Probe-Before-Correct Loop
1. Component Explanation & Architecture

What it is:
This is the misconception-handling loop. The tutor first asks a diagnostic question, then updates status based on the answer, and only then reveals why the idea was wrong and what the correct idea is. The status machine includes active, weakening, resolved, and recurring.

Architecture:
The loop lives inside the learner-state and pedagogy machinery. It feeds retrieval and write-backs and prevents the tutor from correcting a mistake the student did not actually make.

2. Purpose & Impact (Why & How)

Why it is required:
Immediate correction is pedagogically weak because it skips diagnostic confirmation. The model wants to confirm the misconception, not merely assume it.

How it helps:
It promotes active recall, distinguishes actual misconception from uncertainty, and prioritizes recurring misconceptions in retrieval.

Building a Better Model:
This is a real improvement over “answer then correct” tutoring, because it preserves diagnostic integrity.

3. Real-World Example

If a student says “quadratic always has two real roots,” the system should ask a diagnostic question first rather than immediately lecturing. The build plan reports that the loop held in a test run.
11) Prior-Knowledge Gating / Class-9 Bridges
1. Component Explanation & Architecture

What it is:
This adds prerequisite recap nodes for Class-9 material when a Class-10 concept depends on it. Bridges are tracked like normal concepts and can be activated if mastery is below threshold.

Architecture:
When a Class-10 concept is resolved, the system checks prerequisite mastery. If below threshold, it prepends a recap and diagnostic question. If the learner is advanced, the bridge is skipped.

2. Purpose & Impact (Why & How)

Why it is required:
Students often fail because prerequisite knowledge is missing, not because the target topic is hard. This is a real educational bottleneck.

How it helps:
It prevents silent prerequisite failure and makes the tutor adaptive to readiness. It also allows cold-start probing for foundational knowledge.

Building a Better Model:
This is a major improvement over flat-content tutoring because it encodes learning dependencies explicitly.

3. Real-World Example

If a student is working on a Class-10 algebra topic but has weak Class-9 congruence or linear-equation foundations, the system inserts a short recap before proceeding.
12) Scaffolded, Fading Hint Chains
1. Component Explanation & Architecture

What it is:
Every practice item has a 3-step hint chain: conceptual nudge, method/formula recall, partial first step. No hint may state the final answer. The tutor escalates by exactly one level on request.

Architecture:
Hints are retrieved alongside questions and are part of the pedagogy engine’s action space. If the chain is exhausted, the system switches to an analogous worked example rather than leaking the solution.

2. Purpose & Impact (Why & How)

Why it is required:
Students need help, but not answer leakage. A progressive hint ladder preserves productive struggle.

How it helps:
It supports self-discovery and prevents the tutor from collapsing into answer-giving mode.

Building a Better Model:
This improves learning efficiency and keeps the tutor’s help calibrated.

3. Real-World Example

A student stuck on a quadratic factorization step gets a nudge about the structure first, then formula recall, then the initial setup, rather than being shown the full factorization immediately.
13) Problem Schemas & Isomorphic Practice
1. Component Explanation & Architecture

What it is:
Problems are abstracted into schemas, and the tutor can retrieve an analogous worked example with the same mathematical structure but different surface details. The architecture also supports generating fresh practice items by changing isomorphic variables.

Architecture:
Schema nodes live in the knowledge graph and are used by retrieval and practice generation.

2. Purpose & Impact (Why & How)

Why it is required:
Procedural mastery is often about recognizing structure, not memorizing exact numbers.

How it helps:
Isomorphic practice improves transfer across surface variants and helps the student see underlying structure.

Building a Better Model:
This is superior to re-explaining the concept repeatedly because it trains generalization.

3. Real-World Example

A speed-distance word problem and a different numeric version of the same schema are treated as the same mathematical structure. The student practices the pattern, not the exact sentence.
14) Metacognitive Prompts
1. Component Explanation & Architecture

What it is:
After success or struggle, the tutor asks the learner to reflect on their steps or difficulty. The architecture says this feeds cognitive load estimation and reinforces retention.

Architecture:
These prompts come after problem attempts and are part of the pedagogical loop, not a separate feature. The graph stores them as metacognitive prompts.

2. Purpose & Impact (Why & How)

Why it is required:
Self-explanation is a known learning amplifier. It helps the system learn how the student thinks, not just whether they got the answer.

How it helps:
It strengthens retention, reveals uncertainty, and provides a better signal for persistence and cognitive load.

Building a Better Model:
This is one of the cleaner additions because it converts student reflection into state evidence.

3. Real-World Example

After solving a problem, the student is asked to explain the steps in their own words. That response becomes useful both pedagogically and diagnostically.