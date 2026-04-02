from pp_agent.cli._legacy_main_impl import main

try:
    from pp_agent.cli._legacy_main_impl import app
except ImportError:  # pragma: no cover
    app = None

__all__ = ["app", "main"]

if __name__ == "__main__":
    main()
