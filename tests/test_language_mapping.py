"""Tests for the Lokutor <-> Pipecat language mapping."""

from __future__ import annotations

from pipecat.transcriptions.language import Language

from pipecat_lokutor.tts import (
    LOKUTOR_LANGUAGES,
    language_to_lokutor_language,
    lokutor_language_to_language,
)


def test_lokutor_supports_32_languages():
    assert len(LOKUTOR_LANGUAGES) == 32


def test_base_languages_map_to_iso_codes():
    assert language_to_lokutor_language(Language.EN) == "en"
    assert language_to_lokutor_language(Language.DE) == "de"
    assert language_to_lokutor_language(Language.JA) == "ja"
    assert language_to_lokutor_language(Language.VI) == "vi"


def test_regional_variant_normalizes_to_base_code():
    # Language.EN_US.value == "en-US" -> Lokutor keys on "en"
    assert language_to_lokutor_language(Language.EN_US) == "en"


def test_unsupported_language_returns_none():
    # Thai is a valid Pipecat language but not (yet) a Lokutor one.
    assert language_to_lokutor_language(Language.TH) is None


def test_none_language_returns_none():
    assert language_to_lokutor_language(None) is None


def test_reverse_mapping_roundtrips():
    assert lokutor_language_to_language("de") == Language.DE
    assert lokutor_language_to_language("en") == Language.EN
    assert lokutor_language_to_language("zz") is None


def test_every_lokutor_code_has_a_pipecat_language():
    # Guards against a Lokutor code that Pipecat can't represent, which would
    # silently drop the language on the reverse path.
    for code in LOKUTOR_LANGUAGES:
        assert lokutor_language_to_language(code) is not None, code
