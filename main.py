from app.config.settings import load_settings
from app.history import init_history_database
from app.runtime import cleanup_expired_files, cleanup_pyinstaller_temp, ensure_runtime_layout
from app.sync import sync_local_rules


def main() -> None:
    ensure_runtime_layout()
    cleanup_pyinstaller_temp()
    settings = load_settings()
    cleanup_expired_files(settings.retention_days)
    init_history_database()
    sync_local_rules(settings.sync)

    from app.gui.main_window import run_app

    run_app()


if __name__ == "__main__":
    main()
