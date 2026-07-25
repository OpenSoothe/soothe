"""Self-contained config loader for soothe host examples.

Mirrors the fj-ai bootstrap pattern: load ``~/.soothe/config``, fall back to
monorepo develop config, then apply SQLite-friendly defaults for one-shot runs
outside the daemon.
"""

from __future__ import annotations

from pathlib import Path

from soothe.config import SOOTHE_HOME, SootheConfig


def apply_example_defaults(config: SootheConfig) -> SootheConfig:
    """Force SQLite persistence and disable autopilot for standalone examples.

    Autopilot requires daemon goal dispatch. These examples run StrangeLoop
    directly through ``SootheRunner.astream`` (interactive / one-shot mode).
    """
    durability = config.agent.protocols.durability.model_copy(
        update={"backend": "sqlite", "checkpointer": "sqlite"}
    )
    protocols = config.agent.protocols.model_copy(update={"durability": durability})
    autopilot = config.agent.autopilot.model_copy(update={"enabled": False})
    agent = config.agent.model_copy(update={"protocols": protocols, "autopilot": autopilot})
    persistence = config.persistence.model_copy(update={"default_backend": "sqlite"})
    return config.model_copy(update={"agent": agent, "persistence": persistence})


def _load_from_dir(config_dir: Path) -> SootheConfig | None:
    """Load nano.yml (+ optional soothe.yml overlay) from a config directory."""
    nano = config_dir / "nano.yml"
    if not nano.is_file():
        return None
    soothe = config_dir / "soothe.yml"
    if soothe.is_file():
        return SootheConfig.from_split_yaml_files(
            nano_path=str(nano),
            soothe_path=str(soothe),
        )
    return SootheConfig.from_yaml_file(str(nano))


def load_soothe_example_config() -> SootheConfig:
    """Load host config from ``SOOTHE_HOME``, monorepo develop, or defaults."""
    home_config = Path(SOOTHE_HOME).expanduser() / "config"
    loaded = _load_from_dir(home_config)
    if loaded is not None:
        return apply_example_defaults(loaded)

    # examples/_shared/config.py → package root = parents[2], monorepo = parents[4]
    here = Path(__file__).resolve()
    candidates = [here.parents[2]]
    if len(here.parents) > 4:
        candidates.append(here.parents[4])
    for root in candidates:
        loaded = _load_from_dir(root / "config" / "develop")
        if loaded is not None:
            return apply_example_defaults(loaded)
        # Template overlay next to develop nano when soothe.yml is absent.
        nano = root / "config" / "develop" / "nano.yml"
        soothe_template = root / "config" / "soothe.template.yml"
        if nano.is_file() and soothe_template.is_file():
            return apply_example_defaults(
                SootheConfig.from_split_yaml_files(
                    nano_path=str(nano),
                    soothe_path=str(soothe_template),
                )
            )

    return apply_example_defaults(SootheConfig())
