from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "protocols" / "frozen-release-v1" / "PROTOCOL.md"


def test_frozen_protocol_commands_use_repository_root_paths() -> None:
    text = PROTOCOL.read_text(encoding="utf-8")

    assert "run from the repository root" in text
    assert "--data-dir data/hard_queries" in text
    assert "--freeze-config protocols/frozen-release-v1/freeze-config.json" in text
    assert "--release-dir releases/gpb-application-note-v1" in text
    assert "release_templates/" not in text
    assert "from `evaluation/`" not in text

    assert (ROOT / "data" / "hard_queries").is_dir()
    assert (ROOT / "protocols" / "frozen-release-v1" / "freeze-config.template.json").is_file()
    assert (ROOT / "scripts" / "validate_frozen_release.py").is_file()
