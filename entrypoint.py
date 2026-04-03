"""
Root entry point for AIHawk Jobs Applier.

Decides whether to start the web server or the CLI based on command-line
arguments:

    python entrypoint.py              → interactive CLI menu
    python entrypoint.py serve        → start web server
    python entrypoint.py generate-resume …
    python entrypoint.py generate-tailored …
    python entrypoint.py generate-cover-letter …

The original ``main.py`` is preserved as a fallback for the legacy
interactive CLI workflow.
"""
import sys

if __name__ == "__main__":
    # If the first argument is a known web-server command, delegate to uvicorn.
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        from app.config import settings
        import uvicorn
        uvicorn.run(
            "app.main:app",
            host=settings.host,
            port=settings.port,
            reload=settings.reload,
        )
    else:
        # Delegate everything else to the CLI.
        from cli.main import cli
        cli()
