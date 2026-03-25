"""PaperScout subagent plugin.

ArXiv paper recommendation agent that delivers personalized daily paper
recommendations by analyzing your Zotero library and ranking newly published
papers by relevance.

Installation:
    pip install soothe[paperscout]

Configuration (config.yml):
    subagents:
      paperscout:
        enabled: true
        model: "openai:gpt-4o-mini"
        config:
          arxiv_categories:
            - cs.AI
            - cs.CV
            - cs.LG
          max_papers: 25
          smtp:
            host: "${SMTP_HOST}"
            port: 587
            user: "${SMTP_USER}"
            password: "${SMTP_PASSWORD}"
          zotero:
            api_key: "${ZOTERO_API_KEY}"
            library_id: "${ZOTERO_LIBRARY_ID}"

Usage:
    soothe run "Find recent papers on transformer architectures" --subagent paperscout
"""

from __future__ import annotations

import logging
from typing import Any

from soothe_sdk import plugin, subagent

from .implementation import create_paperscout_subagent
from .state import PaperScoutConfig

__all__ = [
    "PaperScoutPlugin",
    "create_paperscout_subagent",
]

logger = logging.getLogger(__name__)


@plugin(
    name="paperscout",
    version="1.0.0",
    description="ArXiv paper recommendation agent using Zotero library analysis",
    dependencies=[
        "langgraph>=0.2.0",
        "arxiv>=2.0.0",
        "sentence-transformers>=2.2.0",
        "pyzotero>=1.5.0",
        "scikit-learn>=1.0.0",
        "numpy>=1.20.0",
    ],
    trust_level="standard",  # Community plugin
)
class PaperScoutPlugin:
    """PaperScout community plugin for ArXiv paper recommendations.

    This plugin provides a subagent that:
    - Fetches papers from ArXiv based on configurable categories
    - Analyzes your Zotero library to understand research interests
    - Ranks papers by relevance using sentence embeddings
    - Sends daily email digests with TLDR summaries
    - Discovers code repositories via PapersWithCode
    """

    async def on_load(self, context: Any) -> None:
        """Validate dependencies and initialize plugin.

        Args:
            context: Plugin context with config, logger, and utilities.

        Raises:
            PluginError: If required dependencies are not installed.
        """
        context.logger.info("Loading PaperScout plugin...")

        # Validate dependencies
        missing_deps = []

        try:
            import arxiv  # noqa: F401
        except ImportError:
            missing_deps.append("arxiv>=2.0.0")

        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            missing_deps.append("sentence-transformers>=2.2.0")

        try:
            from pyzotero import zotero  # noqa: F401
        except ImportError:
            missing_deps.append("pyzotero>=1.5.0")

        try:
            import sklearn  # noqa: F401
        except ImportError:
            missing_deps.append("scikit-learn>=1.0.0")

        if missing_deps:
            from soothe.plugin.exceptions import PluginError

            msg = (
                f"Missing required dependencies: {', '.join(missing_deps)}. "
                "Install with: pip install soothe[paperscout]"
            )
            raise PluginError(msg, plugin_name="paperscout")

        context.logger.info("PaperScout plugin loaded successfully")

    @subagent(
        name="paperscout",
        description=(
            "ArXiv paper recommendation agent that delivers personalized daily "
            "paper recommendations by analyzing your Zotero library and ranking "
            "newly published papers by relevance. Use for research paper discovery "
            "and automated literature monitoring."
        ),
        model="openai:gpt-4o-mini",  # For TLDR generation
    )
    async def create_paperscout(
        self,
        model: Any,
        config: Any,
        context: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create PaperScout subagent.

        Args:
            model: Resolved model (BaseChatModel or string).
            config: Soothe configuration.
            context: Plugin context.
            **kwargs: Additional configuration (store, user_id, etc.).

        Returns:
            Subagent dict with name, description, and runnable.
        """
        from soothe.backends.persistence import get_persistence_backend

        # Get PaperScout configuration
        paperscout_config = None
        if hasattr(config, "subagents") and "paperscout" in config.subagents:
            subagent_config = config.subagents["paperscout"]
            if subagent_config.enabled and subagent_config.config:
                paperscout_config = PaperScoutConfig(**subagent_config.config)

        if not paperscout_config:
            # Use default configuration
            paperscout_config = PaperScoutConfig()

        # Get persistence store
        store = kwargs.get("store")
        if not store:
            # Create default store
            store = get_persistence_backend(config)

        # Get user ID
        user_id = kwargs.get("user_id", "default")

        # Create subagent
        subagent_dict = create_paperscout_subagent(
            config=paperscout_config,
            store=store,
            user_id=user_id,
        )

        context.logger.info(
            f"Created PaperScout subagent for user {user_id} "
            f"(categories: {paperscout_config.arxiv_categories}, "
            f"max_papers: {paperscout_config.max_papers})"
        )

        return subagent_dict

    def get_subagents(self) -> list[Any]:
        """Get list of subagent factory functions.

        Returns:
            List containing the create_paperscout method.
        """
        return [self.create_paperscout]
