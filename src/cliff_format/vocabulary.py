"""The closed tag vocabularies of CLIFF 1.1.

Every value in this module is normative and comes from the specification
(§12 for `type` / `emotion` / `status`, §13 for the glossary's term-level
subset) and from the reference tables in `cliff/references/`:

* `references/content-types.md` — 26 `type` tags,
* `references/emotion-tags.md` — 23 `emotion` tags,
* `references/status-tags.md` — the 4-value XLIFF 2.x state model.

`cliff/tools/check_examples.py` and the reference validator in `cliff-test`
read the same tables; the drift-guard test in this package compares this module
against the specification text so the copies cannot silently diverge.

Tag values are lowercase kebab-case (`tag-name`, specification §5.5) and their
spelling is *not* relaxed by CLIFF 1.1: `status: Final` is a vocabulary error,
not an alias. The tolerant parser (Appendix C.2.3) may remove quotes around a
tag, and it may case-fold a tag whose lowercase spelling is in this set, but it
never guesses a word that is not here.
"""

from __future__ import annotations

# --- §12.1 type tags -------------------------------------------------------

TYPE_TAGS = frozenset(
    {
        "noun",
        "verb",
        "adjective",
        "adverb",
        "pronoun",
        "numeral",
        "preposition",
        "conjunction",
        "particle",
        "interjection",
        "proper-noun",
        "noun-phrase",
        "verb-phrase",
        "adjective-phrase",
        "adverb-phrase",
        "fixed-phrase",
        "idiom",
        "sentence",
        "description",
        "narration",
        "dialogue",
        "monologue",
        "prompt",
        "label",
        "subtitle",
        "accessibility-cue",
    }
)

# --- §12.2 emotion tags ----------------------------------------------------

EMOTION_TAGS = frozenset(
    {
        "neutral",
        "objective",
        "mechanical",
        "joyful",
        "sad",
        "angry",
        "fearful",
        "surprised",
        "curious",
        "disgusted",
        "anxious",
        "calm",
        "playful",
        "serious",
        "urgent",
        "romantic",
        "hopeful",
        "grateful",
        "formal",
        "informal",
        "polite",
        "rude",
        "nostalgic",
    }
)

# --- §12.3 status tags ----------------------------------------------------

STATUS_TAGS = frozenset({"initial", "translated", "reviewed", "final"})

# --- §13 variant values ---------------------------------------------------

VARIANT_TAGS = frozenset({"standard", "glossary"})

# --- §13.2.1 term-level subset for `variant: glossary` --------------------

GLOSSARY_TYPES = frozenset(
    {
        "noun",
        "verb",
        "adjective",
        "adverb",
        "pronoun",
        "numeral",
        "preposition",
        "conjunction",
        "particle",
        "interjection",
        "proper-noun",
        "noun-phrase",
        "verb-phrase",
        "adjective-phrase",
        "adverb-phrase",
        "fixed-phrase",
        "idiom",
    }
)

# --- §12.2 speech types, whose default emotion is `neutral` ---------------

SPEECH_TYPES = frozenset({"dialogue", "monologue", "idiom"})


def canonical_case(text: str, allowed: frozenset[str]) -> str | None:
    """Return the lowercase spelling of ``text`` when it is only a casing slip.

    ``"Final"`` returns ``"final"`` because the lowercase spelling is in the
    vocabulary; ``"Nown"`` returns ``None`` because no case-folding makes it a
    valid tag. The tolerant parser uses this to decide whether a differently
    cased tag is a repair or an error — it never guesses a *word*, only a
    spelling of a word the vocabulary already defines.
    """
    lowered = text.lower()
    return lowered if lowered in allowed else None


#: The vocabulary each tag-typed field validates against. Keys match the field
#: names in the data model so a validator can look the set up by name.
TAGS_BY_KEY: dict[str, frozenset[str]] = {
    "variant": VARIANT_TAGS,
    "type": TYPE_TAGS,
    "status": STATUS_TAGS,
}
