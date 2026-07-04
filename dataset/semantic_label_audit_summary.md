# Semantic Label Audit Summary

- Dataset rows checked: 10000
- Total audit flags: 41748
- Rows with at least one flag: 9942
- Rows with no flags: 58

## Flags by issue type
- assigned_label_unsupported: 20933
- obvious_missing_label: 18456
- assigned_action_unsupported: 1854
- semantic_contradiction: 505

## Flags by field
- miniLM_labels: 35766
- hope_signals: 4089
- target_policy_action: 1893

## Top label/action flags
- miniLM_labels / verbal_analogy / obvious_missing_label: 2667
- miniLM_labels / confusion / assigned_label_unsupported: 2637
- miniLM_labels / procedural_focus / obvious_missing_label: 1793
- miniLM_labels / question / obvious_missing_label: 1779
- miniLM_labels / misconception_clue / obvious_missing_label: 1731
- miniLM_labels / frustration / assigned_label_unsupported: 1463
- miniLM_labels / recurring_error / obvious_missing_label: 1445
- miniLM_labels / low_confidence / assigned_label_unsupported: 1377
- miniLM_labels / request_representation / obvious_missing_label: 1272
- miniLM_labels / diagrammatic / obvious_missing_label: 1192
- miniLM_labels / skepticism / assigned_label_unsupported: 1014
- miniLM_labels / physical / assigned_label_unsupported: 1012
- miniLM_labels / curiosity / assigned_label_unsupported: 999
- miniLM_labels / anxiety / obvious_missing_label: 995
- miniLM_labels / shortcut_seeking / assigned_label_unsupported: 987
- miniLM_labels / high_confidence / obvious_missing_label: 909
- miniLM_labels / disengagement / assigned_label_unsupported: 806
- miniLM_labels / request_representation / assigned_label_unsupported: 774
- miniLM_labels / low_confidence / obvious_missing_label: 698
- miniLM_labels / transfer_attempt / assigned_label_unsupported: 691
- hope_signals / Low productive_struggle / assigned_label_unsupported: 672
- miniLM_labels / procedural_focus / assigned_label_unsupported: 656
- miniLM_labels / topic_shift / assigned_label_unsupported: 623
- miniLM_labels / cognitive_overload / obvious_missing_label: 585
- miniLM_labels / cognitive_overload / assigned_label_unsupported: 570
- miniLM_labels / self_monitoring / assigned_label_unsupported: 494
- miniLM_labels / physical / obvious_missing_label: 473
- hope_signals / Surface engagement / assigned_label_unsupported: 429
- hope_signals / High ki_score opportunity / assigned_label_unsupported: 418
- miniLM_labels / skepticism / obvious_missing_label: 418

## High-confidence semantic contradictions examples
- Row 28 | hope_signals=Low productive_struggle | Hope signal conflicts with miniLM/utterance cues. Utterance: "the formula an = a + (n-1)d is fine but how to know what is 'a' and 'd' from a story problem? give me an example with like ages"
- Row 55 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "all these formulas, it's just numbers. can you tell me why we need to learn this in real life?"
- Row 170 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "is this even useful in real life? i dont get why we are learning this."
- Row 219 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "this is just words and words, my brain is not getting it. show me some picture na, or a small animation."
- Row 251 | hope_signals=Surface engagement | Hope signal conflicts with miniLM/utterance cues. Utterance: "what is the use of all this in real life? can you give me one example, like where this concept is used for something practical?"
- Row 308 | hope_signals=Low productive_struggle | Hope signal conflicts with miniLM/utterance cues. Utterance: "This whole chapter is too theoretical. can u give me a more practical example or something I can relate to daily life?"
- Row 327 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "why is this even useful? like in real life, where would i use these coordinate geometry formulas?"
- Row 414 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "why are we even learning this? can u give me like one real-world example?"
- Row 448 | hope_signals=Low productive_struggle | Hope signal conflicts with miniLM/utterance cues. Utterance: "all this math is too abstract for me. can you show me where i would actually use this in real life, like with a picture or a video?"
- Row 467 | hope_signals=Surface engagement | Hope signal conflicts with miniLM/utterance cues. Utterance: "this is too much reading, do you have like a short video or animation to explain this part?"
- Row 514 | hope_signals=Low productive_struggle | Hope signal conflicts with miniLM/utterance cues. Utterance: "it's all theory theory. can you give a real life example of this concept? like how it's used daily?"
- Row 536 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "this is so much theory, where is the practical part? can u show me a real life connection?"
- Row 544 | hope_signals=Surface engagement | Hope signal conflicts with miniLM/utterance cues. Utterance: "why are we even studying this? is there any real life use case? like a proper example please na."
- Row 604 | hope_signals=Low productive_struggle | Hope signal conflicts with miniLM/utterance cues. Utterance: "this whole explanation is too theoretical, can you show it like a practical problem happening in front of me?"
- Row 700 | hope_signals=Low productive_struggle | Hope signal conflicts with miniLM/utterance cues. Utterance: "all this theory na, can u give me like a real life example where we use this?"
- Row 747 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "too many words here, can u show me an animation or a short clip instead of all this text?"
- Row 805 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "all these rules are just words. can you show me a word problem solved with this concept, like a real one?"
- Row 813 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "Is there like a bigger picture of why we are learning all this? It feels like just rules na."
- Row 825 | hope_signals=Surface engagement | Hope signal conflicts with miniLM/utterance cues. Utterance: "where do we even use this in real life? give me an example like a story problem."
- Row 862 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "all this text explanation is making me sleepy. can you show me a picture or something?"
- Row 878 | miniLM_labels=disengagement | Utterance contains cues that oppose this assigned label. Utterance: "this is just text on screen na, can u show like an animation or a video for this concept, it's easier to grasp that way."
- Row 957 | hope_signals=Low productive_struggle | Hope signal conflicts with miniLM/utterance cues. Utterance: "all this theory, can u just tell me where we use this in real life? a practical example please."
- Row 1039 | hope_signals=Low productive_struggle | Hope signal conflicts with miniLM/utterance cues. Utterance: "this new topic, modelling and all, what is it really about? can you tell me in one line what mathematical modelling is?"
- Row 1058 | hope_signals=Low productive_struggle | Hope signal conflicts with miniLM/utterance cues. Utterance: "all this theory, where do we use it in real life? can you tell me a practical example na, so I can connect to it."
- Row 1165 | hope_signals=Low productive_struggle | Hope signal conflicts with miniLM/utterance cues. Utterance: "this whole topic na, where will it be useful later? in which class or job?"