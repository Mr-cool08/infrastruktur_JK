"""Uppdatera den fristående Traefik-stacken utan ett separat down-steg."""

from pathlib import Path
import subprocess

PROJECT_DIR = Path(__file__).resolve().parent


def update():
    subprocess.run(["git", "pull", "--ff-only"], cwd=PROJECT_DIR, check=True)
    subprocess.run(["docker", "compose", "pull"], cwd=PROJECT_DIR, check=True)
    subprocess.run(["docker", "compose", "up", "-d"], cwd=PROJECT_DIR, check=True)
    print("Traefik update completed successfully.")


if __name__ == "__main__":
    update()
