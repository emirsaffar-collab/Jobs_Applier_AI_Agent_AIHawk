"""Tests for ConfigValidator in main.py."""
import tempfile
from pathlib import Path

import pytest
import yaml

# Import after path setup
from main import ConfigValidator, ConfigError


def _write_yaml(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        yaml.dump(data, f)


def _valid_config() -> dict:
    return {
        "remote": True,
        "experience_level": {
            "internship": False,
            "entry": True,
            "associate": True,
            "mid_senior_level": True,
            "director": False,
            "executive": False,
        },
        "job_types": {
            "full_time": True,
            "contract": False,
            "part_time": False,
            "temporary": False,
            "internship": False,
            "other": False,
            "volunteer": False,
        },
        "date": {
            "all_time": False,
            "month": False,
            "week": True,
            "24_hours": False,
        },
        "positions": ["Software Engineer"],
        "locations": ["Berlin"],
        "location_blacklist": [],
        "distance": 25,
        "company_blacklist": [],
        "title_blacklist": [],
    }


class TestConfigValidator:
    def test_valid_config(self, tmp_path):
        path = tmp_path / "config.yaml"
        _write_yaml(path, _valid_config())
        result = ConfigValidator.validate_config(path)
        assert result["remote"] is True
        assert result["positions"] == ["Software Engineer"]

    def test_missing_required_key(self, tmp_path):
        cfg = _valid_config()
        del cfg["positions"]
        path = tmp_path / "config.yaml"
        _write_yaml(path, cfg)
        with pytest.raises(ConfigError, match="Missing required key 'positions'"):
            ConfigValidator.validate_config(path)

    def test_invalid_distance(self, tmp_path):
        cfg = _valid_config()
        cfg["distance"] = 42  # not in APPROVED_DISTANCES
        path = tmp_path / "config.yaml"
        _write_yaml(path, cfg)
        with pytest.raises(ConfigError, match="Invalid distance"):
            ConfigValidator.validate_config(path)

    def test_blacklist_defaults_to_empty(self, tmp_path):
        cfg = _valid_config()
        del cfg["company_blacklist"]
        del cfg["title_blacklist"]
        path = tmp_path / "config.yaml"
        _write_yaml(path, cfg)
        result = ConfigValidator.validate_config(path)
        assert result["company_blacklist"] == []
        assert result["title_blacklist"] == []

    def test_none_blacklist_becomes_empty(self, tmp_path):
        cfg = _valid_config()
        cfg["company_blacklist"] = None
        path = tmp_path / "config.yaml"
        _write_yaml(path, cfg)
        result = ConfigValidator.validate_config(path)
        assert result["company_blacklist"] == []

    def test_experience_level_non_bool(self, tmp_path):
        cfg = _valid_config()
        cfg["experience_level"]["entry"] = "yes"
        path = tmp_path / "config.yaml"
        _write_yaml(path, cfg)
        with pytest.raises(ConfigError, match="Experience level"):
            ConfigValidator.validate_config(path)

    def test_validate_email(self):
        assert ConfigValidator.validate_email("user@example.com") is True
        assert ConfigValidator.validate_email("not-an-email") is False
        assert ConfigValidator.validate_email("") is False

    def test_file_not_found(self):
        with pytest.raises(ConfigError, match="YAML file not found"):
            ConfigValidator.load_yaml(Path("/nonexistent/path.yaml"))
