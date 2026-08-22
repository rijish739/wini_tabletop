Here is the comprehensive specification document for the MiniLM Exemplar Classifier. It integrates the previous categories with newly added varieties that capture the anxiety, procedural fixation, and physical-world interactions typical of a 10th-standard student.

---

# MiniLM Exemplar Corpus: 10th Standard Mathematics Learner Utterances

## Executive Summary

This document outlines the training categories for the MiniLM Exemplar Classifier, capturing the natural, messy, and often emotionally charged language of 10th-standard students. The classifier is designed to decouple a student's surface emotion from their underlying cognitive state, allowing the Pedagogy Policy Engine to respond with the correct mix of empathy, pedagogical rigor, and physical or visual grounding.

---

> **Important Rules for Concept ID Tagging (applies to ALL sections below):**
>
> 1. Every example table includes a `concept_id` column. This field maps the utterance to a curriculum concept from the RAG store (`rag_store/concepts.json`).
> 2. **`INHERIT_CURRENT_CONCEPT`**: For generic statements where the student does not explicitly name a mathematical concept (e.g., "what is this diagram", "this is so boring", "ok what next"), do **not** force the Concept Resolver to pick a concept. Instead, assign the label `INHERIT_CURRENT_CONCEPT`. At runtime, when the model outputs this label, the system simply looks at the Learner State (the `current_concept_id` in the turn schema) and carries it forward.
> 3. **RAG-sourced concept IDs only**: The concept tagging of all examples must be retrieved strictly from the RAG store (`rag_store/concepts.json` and `rag_store/vector.faiss`). Do not invent or randomly add any concept IDs outside of this defined list. Valid concept IDs follow the pattern `<doc_id>__<concept>` (e.g., `jemh108__intro_trigonometry`).
> 4. A specific `concept_id` from the RAG store should **only** be assigned when the utterance explicitly and unambiguously names a mathematical concept that maps to a known entry in `concepts.json`.

> **Important: Utterance Style Guidelines**
>
> All student utterances in this corpus are written to reflect **real student language**, not synthetic or grammatically perfect text. This means:
> - Grammatical errors, missing articles, dropped punctuation
> - Layman terms instead of technical vocabulary (e.g., "that graph thing" instead of "graphical representation")
> - Abbreviations and shorthand ("cant", "dont", "n all", "etc", "pls")
> - Run-on sentences, casual tone, emotional outbursts
> - Hinglish or Indian English phrasing patterns
>
> MiniLM (sentence-transformers/all-MiniLM-L6-v2) is a semantic similarity model — it captures meaning, not grammar. Training with noisy, natural utterances improves production robustness against real student input.

---

## 1. Representation & Sensemaking Requests

These utterances indicate the student is trying to process the concept but is struggling with the specific format (e.g., algebra vs. geometry) in which it is presented.

| Student Utterance | concept_id | MiniLM Labels | HOPE / State Signals | Target Policy Action |
| --- | --- | --- | --- | --- |
| "what is this diagram, i am not able to understand" | `INHERIT_CURRENT_CONCEPT` | `confusion`, `question`, `diagrammatic` | High `load_risk` | `REPRESENTATION_TRANSLATION` |
| "explain the equations, why is it like that?" | `INHERIT_CURRENT_CONCEPT` | `confusion`, `question`, `algebraic` | Moderate `load_risk` | `EXPLAIN` |
| "i understood the first point, but not able to understand what is this" | `INHERIT_CURRENT_CONCEPT` | `confusion`, `self_correction` | Partial mastery | `SOCRATIC_Q` |
| "i understood half half, can you explain in different way" | `INHERIT_CURRENT_CONCEPT` | `confusion`, `representation_shift` | High `productive_struggle` | `VISUAL_ANALOGY` |
| "i can solve the quadratic equation but parabola confuses me" | `jemh102__quadratic_zero_geometry` | `confusion`, `question`, `graphical` | Moderate `load_risk`, High `ki_score` opportunity | `REPRESENTATION_TRANSLATION` |
| "why distance formula has square root in it, i dont get it" | `jemh107__distance_formula` | `confusion`, `question`, `algebraic` | Moderate `load_risk` | `EXPLAIN` |
| "the factor tree looks different from prime factor" | `jemh101__fundamental_theorem_of_arithmetic` | `confusion`, `representation_shift` | High `ki_score` opportunity | `REPRESENTATION_TRANSLATION` |
| "i cant read the ogive curve properly, how to find median from it?" | `jemh113__median_grouped_data` | `confusion`, `question`, `graphical` | High `load_risk` | `VISUAL_ANALOGY` |
| "tangent diagram makes sense but perpendicular radius is what confuses me a lot" | `jemh110__tangent_radius_perpendicularity` | `confusion`, `self_correction`, `diagrammatic` | Partial mastery, High `ki_score` | `EXPLAIN` |

**Explanation:** The system must recognize that the student is actively trying to learn but has hit a representation wall. The policy response should instantly shift the medium (e.g., from an equation to a visual asset) rather than just repeating the same text. Generic utterances (first 4 rows) use `INHERIT_CURRENT_CONCEPT`; concept-specific utterances (last 5 rows) receive verified `concept_id` values from the RAG store because the student explicitly names the mathematical concept.

---

## 2. Context, Analogy & Transfer Requests

These represent high-value learning signals where the student is attempting to map mathematical abstractions to the real world or a different mathematical domain.

| Student Utterance | concept_id | MiniLM Labels | HOPE / State Signals | Target Policy Action |
| --- | --- | --- | --- | --- |
| "can you explain this concept with cricket" | `INHERIT_CURRENT_CONCEPT` | `transfer_attempt`, `verbal_analogy` | High `kt_score` | `VISUAL_ANALOGY` (If grounded) |
| "where can i use this example" | `INHERIT_CURRENT_CONCEPT` | `curiosity`, `transfer_attempt` | High `kt_score` | `TRANSFER_PROBLEM` |
| "why we have to learn about prime number, why not other numbers" | `INHERIT_CURRENT_CONCEPT` | `curiosity`, `abstraction_attempt` | High `ct_score` | `SOCRATIC_COUNTEREXAMPLE` |
| "can you give me different example" | `INHERIT_CURRENT_CONCEPT` | `request_hint`, `example_request` | Active `hint_dependency` | `ANALOGOUS_EXAMPLE` |
| "finding zeroes of quadratic is same thing as finding roots of quadratic equation na?" | `jemh104__roots_of_quadratic_equation` | `transfer_attempt`, `curiosity` | High `kt_score`, High `ki_score` | `EXPLAIN` |
| "i want to use elimination method instead of substitution" | `jemh103__elimination_method` | `transfer_attempt`, `question` | Moderate `kt_score` | `REPRESENTATION_TRANSLATION` |
| "is AP like compound interest where things keep increasing or what?" | `jemh105__ap_definition_identification` | `transfer_attempt`, `verbal_analogy` | High `kt_score` | `SOCRATIC_COUNTEREXAMPLE` |
| "can I use the section formula to find the midpoint" | `jemh107__midpoint_formula` | `transfer_attempt`, `curiosity` | High `kt_score`, Moderate `ki_score` | `EXPLAIN` |
| "angle of elevation and depression feels like same thing only, what is the difference?" | `jemh109__angle_of_depression` | `confusion`, `transfer_attempt`, `abstraction_attempt` | Moderate `kt_score`, High `ct_score` | `SOCRATIC_COUNTEREXAMPLE` |

**Explanation:** These are moments of intellectual stretch. The classifier must flag high critical thinking (CT) or knowledge transfer (KT) potential. The policy engine should reward this curiosity with grounded, real-world applications or analogous examples from the curriculum graph. Generic utterances inherit the current concept; the 5 concept-specific utterances explicitly name mathematical concepts that map to verified entries in `concepts.json`.

---

## 3. Motivation, Resistance & System Gaming

Students frequently test boundaries, look for shortcuts, or express frustration when cognitive load is too high.

| Student Utterance | concept_id | MiniLM Labels | HOPE / State Signals | Target Policy Action |
| --- | --- | --- | --- | --- |
| "this is so boring" | `INHERIT_CURRENT_CONCEPT` | `frustration`, `disengagement` | Low `productive_struggle` | `ENCOURAGE` / `METACOGNITIVE_REFLECT` |
| "what is the point of learning this topic, it is so difficult..." | `INHERIT_CURRENT_CONCEPT` | `frustration`, `confusion` | High `load_risk` | `ENCOURAGE`, then lower ZPD |
| "can you tell me easy shortcut to learn faster..." | `INHERIT_CURRENT_CONCEPT` | `frustration`, `shortcut_seeking` | Low `productive_struggle` | `METACOGNITIVE_REFLECT` |
| "teach only questions which comes in exam" | `INHERIT_CURRENT_CONCEPT` | `frustration`, `topic_shift` | Surface engagement | `REVIEW` |
| "i hate coordinate geometry, when will i ever use distance formula in life" | `jemh107__distance_formula` | `frustration`, `disengagement` | Low `productive_struggle`, High `load_risk` | `ENCOURAGE` + `TRANSFER_PROBLEM` |
| "probability is just guessing only, why we need formula for that" | `jemh114__theoretical_probability_formula` | `frustration`, `curiosity` | Low `productive_struggle`, Moderate `ct_score` | `SOCRATIC_COUNTEREXAMPLE` |
| "surface area n all are too long, just give me the answer, please, i wont tell anyone" | `jemh112__surface_area_combined_solids` | `frustration`, `shortcut_seeking` | Low `productive_struggle`, High `load_risk` | `METACOGNITIVE_REFLECT` |
| "why we need 3 different methods to find mean of grouped data, one is enough na" | `jemh113__mean_grouped_data` | `frustration`, `curiosity`, `abstraction_attempt` | Moderate `ct_score` | `EXPLAIN` |
| "AP is so repetitive, just tell nth term formula and lets move on pls" | `jemh105__nth_term_formula` | `frustration`, `shortcut_seeking`, `topic_shift` | Low `productive_struggle` | `SOCRATIC_Q` |

**Explanation:** The system must not capitulate by giving away answers. It must log the affective state (frustration), validate the difficulty, and pivot to a more engaging or slightly easier task to rebuild momentum without breaking pedagogical rules. Generic utterances are affective/motivational with no specific concept; the 5 concept-specific utterances name mathematical concepts verified in the RAG store.

---

## 4. Flow & Prerequisite Management

These utterances dictate the pace of the curriculum and how the system handles missing foundational knowledge.

| Student Utterance | concept_id | MiniLM Labels | HOPE / State Signals | Target Policy Action |
| --- | --- | --- | --- | --- |
| "ok what next" | `INHERIT_CURRENT_CONCEPT` | `topic_shift`, `ready_for_next` | Mastery threshold met | `TRANSFER_PROBLEM` |
| "but i dont know the old concept you are asking, can you just continue" | `INHERIT_CURRENT_CONCEPT` | `frustration`, `confusion` | Prerequisite weakness | `BRIDGE_RECAP` |
| "i finished quadratic equations, can we do AP now?" | `jemh105__ap_definition_identification` | `topic_shift`, `ready_for_next` | Mastery threshold met | `TRANSFER_PROBLEM` |
| "you are asking BPT but i dont remember similar figures from before" | `jemh106__basic_proportionality_theorem` | `confusion`, `frustration` | Prerequisite weakness (`jemh106__similar_figures`) | `BRIDGE_RECAP` |
| "i already know substitution method, skip to elimination pls" | `jemh103__elimination_method` | `topic_shift`, `ready_for_next` | High `confidence` | `QUIZ` |
| "before all this, i want to understand sin cos etc" | `jemh108__fundamental_trig_ratios` | `self_monitoring`, `topic_shift` | Prerequisite awareness | `REVIEW` |
| "i didnt understand zeroes of polynomials only, after that teach me quadratic equation" | `jemh102__zero_of_polynomial` | `self_monitoring`, `confusion` | Prerequisite weakness | `BRIDGE_RECAP` |

**Explanation:** When a student hits a prerequisite wall, they often want to skip it. The classifier identifies the gap, and the policy engine strictly enforces the bridge gate, often disguised as a low-stakes diagnostic probe to prevent session abandonment. The 5 concept-specific utterances explicitly reference mathematical topics that map to verified concept IDs.

---

## 5. Self-Doubt & Math Anxiety (New)

10th standard is a high-pressure year. Students often articulate cognitive overload as personal failure.

| Student Utterance | concept_id | MiniLM Labels | HOPE / State Signals | Target Policy Action |
| --- | --- | --- | --- | --- |
| "I am so dumb, I will never get trigonometry." | `jemh108__intro_trigonometry` | `low_confidence`, `frustration` | High `load_risk` | `ENCOURAGE` + Lower ZPD |
| "Everyone else in my class understands this except me." | `INHERIT_CURRENT_CONCEPT` | `low_confidence`, `disengagement` | Low `confidence` metric | `METACOGNITIVE_REFLECT` |
| "I keep making the same mistake, just skip this." | `INHERIT_CURRENT_CONCEPT` | `frustration`, `self_monitoring` | Recurring Misconception | `MISCONCEPTION_PROBE` (visual) |
| "I am going to fail the board exams." | `INHERIT_CURRENT_CONCEPT` | `anxiety`, `low_confidence` | High `load_risk` | `ENCOURAGE` + `ISOMORPHIC_PRACTICE` (easy win) |
| "i will never understand discriminant and nature of roots, its too much for me" | `jemh104__discriminant_nature_of_roots` | `low_confidence`, `frustration`, `confusion` | High `load_risk` | `ENCOURAGE` + `VISUAL_ANALOGY` |
| "proof by contradiction is impossible for me, i cant think like that backwards" | `jemh101__proof_by_contradiction_method` | `low_confidence`, `frustration` | High `load_risk` | `ENCOURAGE` + `WORKED_EXAMPLE` |
| "i always mess up cumulative frequency table, i feel so stupid" | `jemh113__cumulative_frequency` | `low_confidence`, `frustration`, `self_monitoring` | High `load_risk`, Recurring error | `ENCOURAGE` + `ISOMORPHIC_PRACTICE` |
| "coordinate geometry i will learn later now please let me go" | `jemh107__cartesian_coordinate_system` | `low_confidence`, `disengagement` | Low `confidence`, High `load_risk` | `ENCOURAGE` + Lower ZPD |
| "i tried this formula 5 times, i cant understand this section formula" | `jemh107__section_formula` | `frustration`, `low_confidence`, `self_monitoring` | Recurring Misconception, High `load_risk` | `MISCONCEPTION_PROBE` |

**Explanation:** The classifier must detect when cognitive overload turns into anxiety. The pedagogical response must first be affective (encouragement) and then structural—engineering an "easy win" by temporarily dropping the difficulty (ZPD) to rebuild the student's confidence. Generic utterances inherit the current concept; the 5 concept-specific utterances explicitly name mathematical topics from the RAG store.

---

## 6. Procedural Fixation & Board Exam Pressure (New)

Students often prioritize rote memorization over conceptual understanding to optimize for exams.

| Student Utterance | concept_id | MiniLM Labels | HOPE / State Signals | Target Policy Action |
| --- | --- | --- | --- | --- |
| "Just tell me the final formula, I don't need the story." | `INHERIT_CURRENT_CONCEPT` | `shortcut_seeking`, `hint_dependency` | Low `productive_struggle` | `SOCRATIC_Q` |
| "Do I need to write all these steps in the exam?" | `INHERIT_CURRENT_CONCEPT` | `procedural_focus`, `curiosity` | Surface engagement | `EXPLAIN` (focusing on method) |
| "Is this proof important for the boards?" | `INHERIT_CURRENT_CONCEPT` | `topic_shift`, `anxiety` | Moderate `load_risk` | `EXPLAIN` + `WORKED_EXAMPLE` |
| "I memorized the steps, can we move on?" | `INHERIT_CURRENT_CONCEPT` | `procedural_focus`, `ready_for_next` | Low `ki_score` (Knowledge Integration) | `TRANSFER_PROBLEM` (Near transfer) |
| "i memorized quadratic formula, i dont need to know where it comes from" | `jemh104__quadratic_formula` | `procedural_focus`, `shortcut_seeking` | Low `ki_score`, Low `ct_score` | `SOCRATIC_Q` |
| "for sum of n terms of AP, do i use n/2 times 2a+(n-1)d or n/2 times a+l, which one" | `jemh105__sum_n_terms_formula` | `procedural_focus`, `question` | Surface engagement | `EXPLAIN` (focusing on method) |
| "is proving root 2 irrational going to come in boards for sure?" | `jemh101__proving_irrationality_root_n` | `procedural_focus`, `anxiety` | Moderate `load_risk` | `EXPLAIN` + `WORKED_EXAMPLE` |
| "i know sin 30 is half and cos 60 is half, i learned the table by heart thats enough na" | `jemh108__trig_ratios_specific_angles` | `procedural_focus`, `answer_attempt` | Low `ki_score` | `TRANSFER_PROBLEM` (Near transfer) |
| "area of sector just multiply theta by pi r square divided by 360, right? done?" | `jemh111__area_of_sector` | `procedural_focus`, `question` | Low `ki_score`, Surface engagement | `SOCRATIC_Q` |

**Explanation:** The model must discriminate between genuine understanding and memorization. If a student demands just the formula, the policy engine must refuse to leak the answer and instead use Socratic questioning to force critical thinking (CT) or knowledge integration (KI). Generic utterances are about exam strategy; the 5 concept-specific utterances name verified concepts from the RAG store.

---

## 7. Skepticism & Teacher/Textbook Conflict (New)

Students frequently encounter friction between what a tutor presents and what they learned in school.

| Student Utterance | concept_id | MiniLM Labels | HOPE / State Signals | Target Policy Action |
| --- | --- | --- | --- | --- |
| "But my school teacher taught it in a completely different way." | `INHERIT_CURRENT_CONCEPT` | `conflict`, `confusion` | High `ki_score` opportunity | `REPRESENTATION_TRANSLATION` |
| "The textbook answer at the back is different from this." | `INHERIT_CURRENT_CONCEPT` | `skepticism`, `confusion` | Active `misconception` check | `EXPLAIN` (Step-by-step verification) |
| "Are you sure this is right? It looks wrong." | `INHERIT_CURRENT_CONCEPT` | `skepticism`, `self_correction` | Moderate `ct_score` | `WORKED_EXAMPLE` |
| "my teacher said sum of zeroes is b/a not minus b/a, who is correct?" | `jemh102__quadratic_coefficients` | `conflict`, `confusion`, `misconception_clue` | Active `misconception` (`sum_is_b_over_a`) | `MISCONCEPTION_PROBE` |
| "textbook says quadratic can have no real roots, but sir said every quadratic has two roots, which is it" | `jemh104__discriminant_nature_of_roots` | `conflict`, `skepticism` | Active `misconception` (`quadratic_always_has_two_real_zeroes`), High `ct_score` | `SOCRATIC_COUNTEREXAMPLE` |
| "my coaching sir solves linear equations differently from substitution, which method is correct one?" | `jemh103__substitution_method` | `conflict`, `confusion`, `question` | High `ki_score` opportunity | `REPRESENTATION_TRANSLATION` |
| "i think HCF should be the bigger number not smaller one, are you wrong here?" | `jemh101__prime_factorization_hcf_lcm` | `skepticism`, `misconception_clue` | Active `misconception` check | `EXPLAIN` (Step-by-step verification) |
| "NCERT book uses different diagram for angle of elevation problem, yours looks wrong to me" | `jemh109__angle_of_elevation` | `skepticism`, `confusion`, `diagrammatic` | Moderate `ct_score` | `WORKED_EXAMPLE` |

**Explanation:** Skepticism is a strong learning opportunity. The classifier tags this as an opportunity for integration. The policy engine should validate the student's observation and use representation translation to prove how both methods (the teacher's and the system's) lead to the same mathematical truth. The 5 concept-specific utterances reference verified concepts and, in two cases, expose known misconceptions from the RAG store's misconception taxonomy.

---

## 8. Vague Troubleshooting & Inarticulate Confusion (New)

When cognitive load is maxed out, students lose the ability to articulate exactly what is wrong.

| Student Utterance | concept_id | MiniLM Labels | HOPE / State Signals | Target Policy Action |
| --- | --- | --- | --- | --- |
| "It's not working." | `INHERIT_CURRENT_CONCEPT` | `confusion`, `low_confidence` | High `load_risk` | `SOCRATIC_Q` (Targeted narrowing) |
| "I did exactly what you said but it's still wrong." | `INHERIT_CURRENT_CONCEPT` | `frustration`, `confusion` | Active `misconception` | `MISCONCEPTION_PROBE` |
| "The graph looks weird." | `INHERIT_CURRENT_CONCEPT` | `confusion`, `graphical` | Moderate `load_risk` | `VISUAL_ANALOGY` |
| "I don't know what I don't know." | `INHERIT_CURRENT_CONCEPT` | `confusion`, `cognitive_overload` | High `load_risk` | `BRIDGE_RECAP` or lower ZPD |
| "i keep getting negative area for the sector, something is wrong somewhere" | `jemh111__area_of_sector` | `confusion`, `frustration` | Active `misconception`, Moderate `load_risk` | `MISCONCEPTION_PROBE` |
| "my factorization of the quadratic is not giving right roots, idk what im doing wrong" | `jemh104__solving_by_factorization` | `confusion`, `frustration` | Active `misconception` | `WORKED_EXAMPLE` |
| "the simultaneous equations give me x = 0 and y = 0, that cant be right na?" | `jemh103__pair_linear_equations_intro` | `confusion`, `self_correction` | Moderate `ct_score` | `SOCRATIC_Q` |
| "i drew the tangent to circle but the angle doesnt look like 90 degrees at all" | `jemh110__tangent_radius_perpendicularity` | `confusion`, `skepticism`, `diagrammatic` | Moderate `load_risk`, Active `misconception` | `VISUAL_ANALOGY` |
| "i put values in probability formula but answer is coming more than 1, how is that possible" | `jemh114__probability_range` | `confusion`, `frustration` | Active `misconception`, High `load_risk` | `MISCONCEPTION_PROBE` |

**Explanation:** The system cannot rely on the student to self-diagnose. Vague inputs must trigger diagnostic protocols. The policy engine uses Socratic questions or misconception probes to isolate the specific failure point before attempting to explain. The 5 concept-specific utterances name the mathematical area where the confusion lies, allowing the Concept Resolver to assign a verified `concept_id`.

---

## 9. Task-Based Grounding (New)

For robotic tutors and embodied AI, interactions must bridge the digital concept and the physical reality.

| Student Utterance | concept_id | MiniLM Labels | HOPE / State Signals | Target Policy Action |
| --- | --- | --- | --- | --- |
| "Can you show me how this graph looks using the blocks?" | `INHERIT_CURRENT_CONCEPT` | `request_representation`, `physical` | High `ki_score` | `REPRESENTATION_TRANSLATION` (Physical) |
| "The explaination moved too fast, I missed the step." | `INHERIT_CURRENT_CONCEPT` | `confusion`, `environmental_feedback` | Moderate `load_risk` | `WORKED_EXAMPLE` (Re-run physical action) |
| "I forgot one step in this, do I have to restart the whole math problem?" | `INHERIT_CURRENT_CONCEPT` | `frustration`, `environmental_feedback` | Low `productive_struggle` | `ENCOURAGE` + `RESUME_STATE` |
| "can you show parabola shape of quadratic using rope or blocks or something" | `jemh102__quadratic_zero_geometry` | `request_representation`, `physical`, `graphical` | High `ki_score` | `REPRESENTATION_TRANSLATION` (Physical) |
| "i want to measure angle of elevation to the top of that building outside, can we try?" | `jemh109__angle_of_elevation` | `transfer_attempt`, `physical`, `curiosity` | High `kt_score` | `TRANSFER_PROBLEM` |
| "can you cut the circle sector out of paper so i can see segment area properly" | `jemh111__area_of_segment` | `request_representation`, `physical` | High `ki_score` | `REPRESENTATION_TRANSLATION` (Physical) |
| "i made cone and cylinder with clay, can you show combined volume with these only" | `jemh112__volume_combined_solids` | `request_representation`, `physical`, `curiosity` | High `ki_score`, High `kt_score` | `REPRESENTATION_TRANSLATION` (Physical) |
| "can we use a spinner or dice to test if probability formula actually works or not" | `jemh114__theoretical_probability_formula` | `transfer_attempt`, `physical`, `curiosity` | High `kt_score`, High `ct_score` | `TRANSFER_PROBLEM` |

**Explanation:** In an embodied learning environment, the classifier must recognize physical inputs as valid mathematical inquiries. The policy engine must map physical actions (moving a block, robot speed) to the corresponding mathematical representation (an equation changing, a graphical shift), enforcing task-based continual learning. The 5 concept-specific utterances explicitly name mathematical concepts from the RAG store that the student wants to ground physically.

---

## 10. Generic & Context-Dependent Utterances — Summary of `INHERIT_CURRENT_CONCEPT` Rule

This section consolidates the `INHERIT_CURRENT_CONCEPT` rule and provides additional examples of utterances that are inherently context-dependent and must not be force-tagged to a specific concept.

**Rules (also documented in `model_dataset_architecture_report.md` §4.1):**

1. **`INHERIT_CURRENT_CONCEPT`** is a first-class label in the concept space. When the Concept Resolver model outputs this label for a generic text, the system simply looks at the Learner State (the `current_concept_id` in the turn schema) and carries it forward. No concept resolution is performed.
2. The `concept_id` tagging of all examples must be retrieved strictly from the RAG store (`rag_store/concepts.json` and `rag_store/vector.faiss`). Do not invent or randomly add any concept IDs outside of this defined list.
3. A specific `concept_id` should only be assigned when the student **explicitly names** a mathematical concept that unambiguously maps to an entry in `concepts.json` (e.g., "trigonometry" → `jemh108__intro_trigonometry`).

| Student Utterance | concept_id | MiniLM Labels | HOPE / State Signals | Target Policy Action |
| --- | --- | --- | --- | --- |
| "what is this diagram, i am not able to understand" | `INHERIT_CURRENT_CONCEPT` | `confusion`, `question` | High `load_risk` | `REPRESENTATION_TRANSLATION` |
| "explain the equations, why is it like that?" | `INHERIT_CURRENT_CONCEPT` | `confusion`, `question` | Moderate `load_risk` | `EXPLAIN` |
| "i understood the first point, but not able to understand what is this" | `INHERIT_CURRENT_CONCEPT` | `confusion`, `self_correction` | Partial mastery | `SOCRATIC_Q` |
| "i understood half half, can you explain in different way" | `INHERIT_CURRENT_CONCEPT` | `confusion`, `representation_shift` | High `productive_struggle` | `VISUAL_ANALOGY` |
| "why does the graph look like a U shape here" | `INHERIT_CURRENT_CONCEPT` | `question`, `graphical` | Moderate `load_risk` | `EXPLAIN` |
| "can we draw a table for this data instead" | `INHERIT_CURRENT_CONCEPT` | `request_representation`, `tabular` | Moderate `ki_score` | `REPRESENTATION_TRANSLATION` |
| "hmm okay, tell me more" | `INHERIT_CURRENT_CONCEPT` | `curiosity` | Active engagement | `EXPLAIN` |
| "wait wait, let me think for a sec" | `INHERIT_CURRENT_CONCEPT` | `self_monitoring` | `productive_struggle` | `ENCOURAGE` |
| "can you repeat that last part again" | `INHERIT_CURRENT_CONCEPT` | `confusion`, `question` | Moderate `load_risk` | `EXPLAIN` |
| "i think i got it wrong, let me try once more" | `INHERIT_CURRENT_CONCEPT` | `self_correction`, `self_monitoring` | `productive_struggle` | `ISOMORPHIC_PRACTICE` |
| "ok ok that makes sense now, whats next?" | `INHERIT_CURRENT_CONCEPT` | `ready_for_next`, `topic_shift` | Mastery threshold met | `TRANSFER_PROBLEM` |

---

## Appendix A: Concept ID Reference (from `rag_store/concepts.json`)

The following concept IDs are used in the examples above. All are verified entries from the RAG store:

| concept_id | Name | Chapter |
| --- | --- | --- |
| `jemh101__fundamental_theorem_of_arithmetic` | Fundamental Theorem of Arithmetic | jemh101 |
| `jemh101__prime_factorization_hcf_lcm` | HCF and LCM using Prime Factorization | jemh101 |
| `jemh101__proof_by_contradiction_method` | Proof by Contradiction Method | jemh101 |
| `jemh101__proving_irrationality_root_n` | Proving Irrationality of √n | jemh101 |
| `jemh102__zero_of_polynomial` | Zero of a Polynomial | jemh102 |
| `jemh102__quadratic_zero_geometry` | Geometrical Meaning of Quadratic Zeroes | jemh102 |
| `jemh102__quadratic_coefficients` | Zeroes and Coefficients of a Quadratic | jemh102 |
| `jemh103__pair_linear_equations_intro` | Pair of Linear Equations in Two Variables | jemh103 |
| `jemh103__substitution_method` | Substitution Method for Solving | jemh103 |
| `jemh103__elimination_method` | Elimination Method for Solving | jemh103 |
| `jemh104__roots_of_quadratic_equation` | Roots of a Quadratic Equation | jemh104 |
| `jemh104__quadratic_formula` | The Quadratic Formula | jemh104 |
| `jemh104__discriminant_nature_of_roots` | Discriminant and Nature of Roots | jemh104 |
| `jemh104__solving_by_factorization` | Solving Quadratic Equations by Factorization | jemh104 |
| `jemh105__ap_definition_identification` | Arithmetic Progression Definition | jemh105 |
| `jemh105__nth_term_formula` | Nth Term of an AP | jemh105 |
| `jemh105__sum_n_terms_formula` | Sum of N Terms of an AP | jemh105 |
| `jemh106__basic_proportionality_theorem` | Basic Proportionality Theorem | jemh106 |
| `jemh107__cartesian_coordinate_system` | Cartesian Coordinate System | jemh107 |
| `jemh107__distance_formula` | Distance Formula | jemh107 |
| `jemh107__section_formula` | Section Formula | jemh107 |
| `jemh107__midpoint_formula` | Midpoint Formula | jemh107 |
| `jemh108__intro_trigonometry` | Introduction to Trigonometry | jemh108 |
| `jemh108__fundamental_trig_ratios` | Fundamental Trigonometric Ratios | jemh108 |
| `jemh108__trig_ratios_specific_angles` | Trig Ratios for Specific Angles | jemh108 |
| `jemh109__angle_of_elevation` | Angle of Elevation | jemh109 |
| `jemh109__angle_of_depression` | Angle of Depression | jemh109 |
| `jemh110__tangent_radius_perpendicularity` | Tangent ⊥ Radius at Contact | jemh110 |
| `jemh111__area_of_sector` | Area of a Sector | jemh111 |
| `jemh111__area_of_segment` | Area of a Segment | jemh111 |
| `jemh112__surface_area_combined_solids` | Surface Area of Combined Solids | jemh112 |
| `jemh112__volume_combined_solids` | Volume of Combined Solids | jemh112 |
| `jemh113__mean_grouped_data` | Mean of Grouped Data | jemh113 |
| `jemh113__cumulative_frequency` | Cumulative Frequency | jemh113 |
| `jemh113__median_grouped_data` | Median of Grouped Data | jemh113 |
| `jemh114__theoretical_probability_formula` | Theoretical Probability Formula | jemh114 |
| `jemh114__probability_range` | Range of Probability | jemh114 |

---

## Appendix B: MiniLM Robustness to Noisy Student Language

MiniLM (`sentence-transformers/all-MiniLM-L6-v2`) uses **contextual semantic embeddings**, not keyword or grammar matching. This means:

| Noise Type | Example | Impact on MiniLM | Rationale |
| --- | --- | --- | --- |
| Missing articles / prepositions | "i cant read ogive curve" vs "I cannot read the ogive curve" | **None** — same embedding neighborhood | Transformer attention captures meaning, not grammar |
| Spelling / typos | "cant", "dont", "pls" | **Minimal** — subword tokenizer handles common variants | WordPiece tokenizes "cant" → "can" + "##t", close to "can't" |
| Layman terms | "that U shape graph thing" vs "parabola" | **Low** — slight distance but still in correct cluster | Context words ("graph", "shape") preserve semantic intent |
| Abbreviations | "AP", "BPT", "sin cos etc" | **Low** — common math abbreviations in training corpus | Pre-training corpus includes educational text |
| Run-on / casual tone | "just give answer pls i wont tell anyone" | **None** — semantic meaning preserved | Sentence-level embeddings are invariant to style |

**Recommendation:** Include 20–30% noisy/informal variants per label in the exemplar bank to maximize recall against real student input. The semantic embedding space naturally clusters these near their clean counterparts.