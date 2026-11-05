from photoflow.cli import main


def test_migrate_cli(settings, monkeypatch, capsys):
    monkeypatch.setenv("PHOTOFLOW_NAS_ROOT", str(settings.nas_root))
    monkeypatch.setenv("PHOTOFLOW_DATA_DIR", str(settings.data_dir))
    assert main(["migrate"]) == 0
    assert settings.database_path.exists()
    assert "up to date" in capsys.readouterr().out


def test_invalid_config_does_not_print_private_path(monkeypatch, capsys):
    monkeypatch.setenv("PHOTOFLOW_NAS_ROOT", "/nonexistent/private-path")
    assert main(["migrate"]) == 1
    error = capsys.readouterr().err
    assert "Invalid configuration" in error
    assert "private-path" not in error
