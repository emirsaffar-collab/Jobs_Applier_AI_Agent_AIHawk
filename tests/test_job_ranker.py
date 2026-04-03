"""Tests for JobRanker score parsing."""
import pytest

from src.automation.job_ranker import JobRanker


class TestJobRankerParse:
    def test_parse_valid_json(self):
        response = '{"score": 8, "keywords": "python, django", "reason": "Good match"}'
        result = JobRanker._parse(response)
        assert result["score"] == 8
        assert "python" in result["keywords"]
        assert result["reason"] == "Good match"

    def test_parse_json_with_markdown_fences(self):
        response = '```json\n{"score": 7, "keywords": "java", "reason": "Decent fit"}\n```'
        result = JobRanker._parse(response)
        assert result["score"] == 7

    def test_parse_score_clamped_to_range(self):
        result = JobRanker._parse('{"score": 15, "keywords": "", "reason": ""}')
        assert result["score"] == 10  # clamped to max

        result = JobRanker._parse('{"score": 0, "keywords": "", "reason": ""}')
        assert result["score"] == 1  # clamped to min (max(1, 0))

    def test_parse_fallback_regex(self):
        response = "Score: 6\nKeywords: react, typescript\nReason: Moderate match"
        result = JobRanker._parse(response)
        assert result["score"] == 6
        assert "react" in result["keywords"]

    def test_parse_no_score_returns_zero(self):
        response = "I don't know how to score this."
        result = JobRanker._parse(response)
        assert result["score"] == 0

    def test_parse_empty_string(self):
        result = JobRanker._parse("")
        assert result["score"] == 0
        assert result["keywords"] == ""
