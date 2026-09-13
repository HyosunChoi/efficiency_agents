from src.normalizer import build_creative_id, normalize_creative_name, normalize_media


def test_extension_is_stripped():
    assert normalize_creative_name("무글틴_1+1_0828.mp4") == "무글틴_1+1_0828"
    assert normalize_creative_name("무글틴_발색모음.jpg") == "무글틴_발색모음"


def test_whitespace_and_unicode_normalized():
    assert normalize_media("  싱글원_메타  ") == "싱글원_메타"
    assert normalize_creative_name("무글틴   1+1") == "무글틴 1+1"


def test_creative_id_format():
    creative_id = build_creative_id("싱글원_메타", "무글틴_1+1_0828")
    assert creative_id == "싱글원_메타__무글틴_1+1_0828"
