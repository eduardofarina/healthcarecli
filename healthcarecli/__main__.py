"""Allows `python -m healthcarecli` to work — used by the npm shim."""

from healthcarecli.cli import app

if __name__ == "__main__":
    app()
