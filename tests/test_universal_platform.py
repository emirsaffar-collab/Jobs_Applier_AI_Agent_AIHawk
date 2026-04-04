"""Tests for UniversalPlatform ATS detection and helper logic."""
import pytest

from src.automation.platforms.universal import _detect_ats, _check_confirmation
from src.automation.platforms.base import BasePlatform, ApplyResult


class TestAtsDetection:
    def test_greenhouse(self):
        assert _detect_ats("https://boards.greenhouse.io/acme/jobs/12345") == "greenhouse"
        assert _detect_ats("https://acme.greenhouse.io/jobs/engineer") == "greenhouse"

    def test_lever(self):
        assert _detect_ats("https://jobs.lever.co/acme/abc-123") == "lever"
        assert _detect_ats("https://lever.co/acme") == "lever"

    def test_workday(self):
        assert _detect_ats("https://acme.myworkdayjobs.com/en-US/careers/job/123") == "workday"
        assert _detect_ats("https://acme.workday.com/jobs") == "workday"

    def test_smartrecruiters(self):
        assert _detect_ats("https://jobs.smartrecruiters.com/acme/1234") == "smartrecruiters"

    def test_icims(self):
        assert _detect_ats("https://careers.icims.com/jobs/1234") == "icims"

    def test_generic_fallback(self):
        assert _detect_ats("https://careers.example.com/jobs/engineer") == "generic"
        assert _detect_ats("https://apply.company.io/job/12345") == "generic"


class TestSalaryFilter:
    def test_no_filter_passes_all(self):
        assert BasePlatform._salary_matches("any description", {"min": 0}) is True
        assert BasePlatform._salary_matches("any description", {}) is True

    def test_no_salary_in_description_passes(self):
        assert BasePlatform._salary_matches("Great culture!", {"min": 60000}) is True

    def test_salary_above_min_passes(self):
        desc = "The role pays $90,000 annually."
        assert BasePlatform._salary_matches(desc, {"min": 80000}) is True

    def test_salary_below_min_fails(self):
        desc = "Compensation is $50k per year."
        assert BasePlatform._salary_matches(desc, {"min": 80000}) is False

    def test_salary_k_suffix(self):
        desc = "Salary: 120K USD"
        assert BasePlatform._salary_matches(desc, {"min": 100000}) is True
        assert BasePlatform._salary_matches(desc, {"min": 150000}) is False

    def test_salary_range_uses_max(self):
        # Range "80,000 - 100,000" → max found is 100,000 ≥ 90,000
        desc = "Pay range: $80,000 – $100,000"
        assert BasePlatform._salary_matches(desc, {"min": 90000}) is True


class TestApplyResultConfirmed:
    def test_default_confirmed_false(self):
        r = ApplyResult(success=True)
        assert r.confirmed is False

    def test_confirmed_true(self):
        r = ApplyResult(success=True, confirmed=True)
        assert r.confirmed is True
