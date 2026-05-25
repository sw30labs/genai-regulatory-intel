"""Tests for configuration loading."""

import yaml

from regitel.config import RegitelConfig, StorageConfig, load_config


class TestRegitelConfig:
    def test_defaults(self):
        cfg = RegitelConfig()
        assert cfg.llm.base_url is None
        assert cfg.llm.api_key == "${OPENAI_API_KEY}"
        assert cfg.llm.model == "${OPENAI_MODEL}"
        assert cfg.llm.temperature is None
        assert cfg.llm.max_tokens == 4096
        assert cfg.research.search_provider == "openai"
        assert cfg.research.max_queries_per_jurisdiction == 8
        assert cfg.research.validator_batch_size == 4
        assert cfg.research.quality_gate_reflection is True

    def test_embedding_defaults(self):
        cfg = RegitelConfig()
        assert cfg.embedding.model == "all-MiniLM-L6-v2"

    def test_all_jurisdictions(self):
        cfg = RegitelConfig()
        jids = cfg.all_jurisdictions
        assert "eu" in jids
        assert "usa" in jids
        assert len(jids) > 10


class TestStorageConfig:
    def test_resolve_paths(self):
        sc = StorageConfig(database="~/test/db.sqlite")
        resolved = sc.resolve_paths()
        assert "~" not in resolved.database
        assert resolved.database.endswith("test/db.sqlite")


class TestLoadConfig:
    def test_load_missing_file_uses_defaults(self):
        cfg = load_config("/nonexistent/path.yaml")
        assert isinstance(cfg, RegitelConfig)

    def test_load_yaml_file(self, tmp_path):
        config_data = {
            "llm": {
                "api_key": "test-key",
                "model": "gpt-5.5",
                "temperature": 0.5,
            },
            "storage": {
                "database": str(tmp_path / "test.db"),
            },
        }
        cfg_file = tmp_path / "test_config.yaml"
        cfg_file.write_text(yaml.dump(config_data))

        cfg = load_config(str(cfg_file))
        assert cfg.llm.base_url is None
        assert cfg.llm.api_key == "test-key"
        assert cfg.llm.model == "gpt-5.5"
        assert cfg.llm.temperature == 0.5

    def test_env_var_resolution(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TEST_MODEL", "gpt-5.5")
        monkeypatch.setenv("TEST_API_KEY", "secret")
        config_data = {
            "llm": {
                "api_key": "${TEST_API_KEY}",
                "model": "${TEST_MODEL}",
            },
        }
        cfg_file = tmp_path / "env_config.yaml"
        cfg_file.write_text(yaml.dump(config_data))

        cfg = load_config(str(cfg_file))
        assert cfg.llm.api_key == "secret"
        assert cfg.llm.model == "gpt-5.5"
