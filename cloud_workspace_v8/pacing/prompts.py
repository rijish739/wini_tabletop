"""Prompt fragments used by the paced voice response layer."""

PACING_CONTRACT = """PACING CONTRACT:
- Speak at most {max_words} words and {max_sentences} sentence(s).
- Teach only one atomic idea.
- Do not complete the whole topic now.
- Use a warm, concrete, no-lecture voice.
- If a micro-check is requested, make it natural and short.
- The micro-check is for pacing, not grading.
"""
