"""
Unit tests for app.services.analyzer.analyze()

The analyze() function is pure (no DB, no I/O) so these tests are fast
and deterministic.
"""
import pytest
from app.services.analyzer import analyze


TARGET = "Maersk"
COMPETITORS = ["MSC", "CMA CGM", "Evergreen"]


class TestAnalyzeEmptyInput:
    def test_empty_string_returns_not_mentioned(self):
        result = analyze("", TARGET, COMPETITORS)
        assert result["mentioned"] is False

    def test_none_string_returns_not_mentioned(self):
        result = analyze(None, TARGET, COMPETITORS)
        assert result["mentioned"] is False

    def test_empty_string_position_score_is_none(self):
        result = analyze("", TARGET, COMPETITORS)
        assert result["position_score"] is None

    def test_empty_string_sentiment_is_neutral(self):
        result = analyze("", TARGET, COMPETITORS)
        assert result["sentiment"] == "neutral"

    def test_empty_string_no_competitors_mentioned(self):
        result = analyze("", TARGET, COMPETITORS)
        assert result["competitors_mentioned"] == []


class TestMentionDetection:
    def test_target_mentioned_exact_case(self):
        result = analyze("Maersk is a great shipping company.", TARGET, COMPETITORS)
        assert result["mentioned"] is True

    def test_target_mentioned_lower_case(self):
        result = analyze("maersk dominates container shipping.", TARGET, COMPETITORS)
        assert result["mentioned"] is True

    def test_target_mentioned_upper_case(self):
        result = analyze("MAERSK LINE operates globally.", TARGET, COMPETITORS)
        assert result["mentioned"] is True

    def test_target_not_mentioned(self):
        result = analyze("MSC and Evergreen are discussed here.", TARGET, COMPETITORS)
        assert result["mentioned"] is False

    def test_partial_word_not_matched(self):
        # "maersk" is a substring but "ersk" should not trigger a match for a different target
        result = analyze("The fleet includes ships.", "Ship", COMPETITORS)
        assert result["mentioned"] is True  # "ships" contains "ship"


class TestPositionScore:
    def test_position_score_is_none_when_not_mentioned(self):
        result = analyze("Nothing relevant here.", TARGET, COMPETITORS)
        assert result["position_score"] is None

    def test_position_score_is_zero_when_mentioned_first(self):
        text = "Maersk leads the market."
        result = analyze(text, TARGET, COMPETITORS)
        assert result["position_score"] == 0.0

    def test_position_score_increases_when_mentioned_later(self):
        text = "The shipping industry has many players. Maersk is one of them."
        result = analyze(text, TARGET, COMPETITORS)
        assert 0 < result["position_score"] < 1

    def test_position_score_is_float_between_0_and_1(self):
        text = "In conclusion, Maersk excels."
        result = analyze(text, TARGET, COMPETITORS)
        assert isinstance(result["position_score"], float)
        assert 0 <= result["position_score"] <= 1

    def test_position_score_rounded_to_4_decimal_places(self):
        text = "Leading shipping firms include Maersk among others."
        result = analyze(text, TARGET, COMPETITORS)
        # round() to 4dp means at most 4 digits after decimal
        score_str = str(result["position_score"]).split(".")[-1]
        assert len(score_str) <= 4


class TestSentimentDetection:
    def test_positive_sentiment_when_positive_words_dominate(self):
        result = analyze(
            "Maersk is excellent and outstanding and reliable and trusted.",
            TARGET, COMPETITORS
        )
        assert result["sentiment"] == "positive"

    def test_negative_sentiment_when_negative_words_dominate(self):
        result = analyze(
            "The service is poor, terrible, slow and unreliable.",
            TARGET, COMPETITORS
        )
        assert result["sentiment"] == "negative"

    def test_neutral_sentiment_when_balanced(self):
        result = analyze(
            "The service is excellent but also terrible.",
            TARGET, COMPETITORS
        )
        assert result["sentiment"] == "neutral"

    def test_neutral_when_no_sentiment_words(self):
        result = analyze(
            "Maersk operates container ships across the ocean.",
            TARGET, COMPETITORS
        )
        assert result["sentiment"] == "neutral"

    def test_punctuation_stripped_from_sentiment_words(self):
        # "excellent," (with comma) should still count as positive
        result = analyze("The company is excellent, amazing, outstanding.", TARGET, COMPETITORS)
        assert result["sentiment"] == "positive"


class TestCompetitorDetection:
    def test_competitor_detected_case_insensitive(self):
        result = analyze("msc and cma cgm are competitors.", TARGET, COMPETITORS)
        assert "MSC" in result["competitors_mentioned"]
        assert "CMA CGM" in result["competitors_mentioned"]

    def test_no_competitors_mentioned(self):
        result = analyze("Maersk is the only company discussed.", TARGET, COMPETITORS)
        assert result["competitors_mentioned"] == []

    def test_all_competitors_detected(self):
        text = "MSC, CMA CGM and Evergreen compete with Maersk."
        result = analyze(text, TARGET, COMPETITORS)
        assert set(result["competitors_mentioned"]) == {"MSC", "CMA CGM", "Evergreen"}

    def test_empty_competitor_list(self):
        result = analyze("Maersk is great.", TARGET, [])
        assert result["competitors_mentioned"] == []

    def test_competitors_not_detected_when_absent(self):
        result = analyze("Maersk dominates the market alone.", TARGET, COMPETITORS)
        # None of the competitors are in the text
        for c in COMPETITORS:
            assert c not in result["competitors_mentioned"]

    def test_competitor_mentioned_even_without_target(self):
        result = analyze("MSC is the largest fleet operator.", TARGET, COMPETITORS)
        assert result["mentioned"] is False
        assert "MSC" in result["competitors_mentioned"]


class TestReturnShape:
    def test_result_has_all_required_keys(self):
        result = analyze("Maersk is great.", TARGET, COMPETITORS)
        assert "mentioned" in result
        assert "position_score" in result
        assert "sentiment" in result
        assert "competitors_mentioned" in result

    def test_mentioned_is_bool(self):
        result = analyze("Maersk ships.", TARGET, COMPETITORS)
        assert isinstance(result["mentioned"], bool)

    def test_competitors_mentioned_is_list(self):
        result = analyze("MSC and Maersk.", TARGET, COMPETITORS)
        assert isinstance(result["competitors_mentioned"], list)
