"""PaperScout workflow nodes using LangGraph.

Implements a 5-node workflow:
profile_analysis → data_collection → relevance_assessment → content_generation → communication

Each node uses Soothe's PersistStore for state persistence and emits events for observability.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import arxiv
from pyzotero import zotero

from soothe_sdk import PersistStore
from soothe_community.paperscout.email import construct_email_content, send_email
from soothe_community.paperscout.events import (
    PaperScoutEmailSentEvent,
    PaperScoutErrorEvent,
    PaperScoutPaperFoundEvent,
    PaperScoutStepEvent,
)
from soothe_community.paperscout.models import ArxivPaper, ZoteroPaper
from soothe_community.paperscout.reranker import PaperReranker
from soothe_community.paperscout.state import AgentState

logger = logging.getLogger(__name__)


def _emit_step_event(step: str, status: str) -> None:
    """Emit a workflow step event."""
    _event = PaperScoutStepEvent(step=step, status=status)  # noqa: F841
    # Event will be picked up by the event system
    logger.info(f"[{step}] {status}")


def _emit_paper_found_event(paper_title: str, arxiv_id: str, score: float) -> None:
    """Emit a paper found event."""
    _event = PaperScoutPaperFoundEvent(  # noqa: F841
        paper_title=paper_title,
        arxiv_id=arxiv_id,
        score=score,
    )
    logger.info(f"Found paper: {paper_title} (score: {score:.2f})")


def _emit_error_event(error_message: str, step: str) -> None:
    """Emit an error event."""
    _event = PaperScoutErrorEvent(error_message=error_message, step=step)  # noqa: F841
    logger.error(f"Error in {step}: {error_message}")


def _emit_email_sent_event(recipient: str, papers_count: int) -> None:
    """Emit an email sent event."""
    _event = PaperScoutEmailSentEvent(recipient=recipient, papers_count=papers_count)  # noqa: F841
    logger.info(f"Email sent to {recipient} with {papers_count} papers")


def make_nodes(store: PersistStore, user_id: str) -> dict[str, Callable]:
    """Create node functions with injected storage and user_id.

    Args:
        store: PersistStore for caching and state.
        user_id: User identifier for storage keys.

    Returns:
        Dict mapping node names to functions.
    """

    def profile_analysis_node(state: AgentState) -> dict[str, Any]:
        """Validate user profile and configuration."""
        _emit_step_event("profile_analysis", "Validating configuration")

        config = state["config"]
        errors = []

        # Validate Zotero configuration
        if not config.zotero:
            errors.append("Zotero configuration is required")
        else:
            if not config.zotero.api_key:
                errors.append("Zotero API key is required")
            if not config.zotero.library_id:
                errors.append("Zotero library ID is required")

        # Validate SMTP if sending emails
        if config.send_email and not config.smtp:
            errors.append("SMTP configuration is required when send_email=True")

        if errors:
            for error in errors:
                _emit_error_event(error, "profile_analysis")
                state["errors"].append(error)
            return {
                "errors": state["errors"],
            }

        _emit_step_event("profile_analysis", "Configuration validated")
        state["info"].append("Profile validated successfully")
        return {"info": state["info"]}

    def data_collection_node(state: AgentState) -> dict[str, Any]:
        """Collect papers from ArXiv and Zotero."""
        _emit_step_event("data_collection", "Fetching papers")

        config = state["config"]

        try:
            # Calculate date range
            end_date = date.today()
            start_date = end_date - timedelta(days=config.lookback_days)

            # Fetch ArXiv papers
            _emit_step_event("data_collection", f"Querying ArXiv ({start_date} to {end_date})")
            arxiv_papers = []

            for category in config.arxiv_categories:
                search = arxiv.Search(
                    query=f"cat:{category}",
                    max_results=config.max_papers_queried // len(config.arxiv_categories),
                    sort_by=arxiv.SortCriterion.SubmittedDate,
                )

                for result in search.results():
                    # Filter by date range
                    if result.published.date() < start_date:
                        continue

                    paper = ArxivPaper(
                        title=result.title,
                        summary=result.summary,
                        authors=[author.name for author in result.authors],
                        arxiv_id=result.entry_id.split("/")[-1],
                        pdf_url=result.pdf_url,
                        published_date=result.published,
                    )
                    arxiv_papers.append(paper)

            _emit_step_event("data_collection", f"Found {len(arxiv_papers)} papers from ArXiv")

            # Check for already emailed papers
            emailed_key = f"paperscout:emailed:{user_id}"
            emailed_papers = store.get(emailed_key) or set()
            new_papers = [p for p in arxiv_papers if p.arxiv_id not in emailed_papers]

            _emit_step_event(
                "data_collection",
                f"{len(new_papers)} new papers (filtered {len(arxiv_papers) - len(new_papers)} already sent)",
            )

            # Fetch Zotero corpus
            _emit_step_event("data_collection", "Fetching Zotero library")
            zotero_papers = []

            if config.zotero:
                try:
                    zot = zotero.Zotero(
                        config.zotero.library_id,
                        config.zotero.library_type,
                        config.zotero.api_key,
                    )

                    # Try to get cached corpus first
                    cache_key = f"paperscout:zotero:{user_id}"
                    cached = store.get(cache_key)

                    if (
                        cached and (datetime.now() - cached.get("timestamp", datetime.min)).total_seconds() < 86400
                    ):  # 24 hours
                        _emit_step_event("data_collection", "Using cached Zotero library")
                        zotero_papers = [ZoteroPaper(**p) for p in cached.get("papers", [])]
                    else:
                        # Fetch from API
                        items = zot.everything(zot.top())
                        for item in items:
                            data = item.get("data", {})
                            paper = ZoteroPaper(
                                zotero_item_key=item.get("key", ""),
                                title=data.get("title", ""),
                                authors=[creator.get("name", "") for creator in data.get("creators", [])],
                                abstract=data.get("abstractNote", ""),
                                url=data.get("url"),
                                tags=[tag.get("tag", "") for tag in data.get("tags", [])],
                                date_added=datetime.strptime(data.get("dateAdded", ""), "%Y-%m-%dT%H:%M:%SZ")
                                if data.get("dateAdded")
                                else None,
                                collection_paths=[],
                            )
                            zotero_papers.append(paper)

                        # Cache for 24 hours
                        store.set(
                            cache_key,
                            {
                                "papers": [p.model_dump() for p in zotero_papers],
                                "timestamp": datetime.now(),
                            },
                        )

                    _emit_step_event("data_collection", f"Loaded {len(zotero_papers)} papers from Zotero")

                except Exception as e:
                    _emit_error_event(f"Failed to fetch Zotero library: {e}", "data_collection")
                    state["errors"].append(f"Zotero error: {e}")

            state["discovered_papers"] = new_papers
            state["zotero_papers"] = zotero_papers
            state["info"].append(f"Collected {len(new_papers)} new papers from ArXiv")

            return {
                "discovered_papers": new_papers,
                "zotero_papers": zotero_papers,
                "info": state["info"],
            }

        except Exception as e:
            _emit_error_event(str(e), "data_collection")
            state["errors"].append(str(e))
            return {"errors": state["errors"]}

    def relevance_assessment_node(state: AgentState) -> dict[str, Any]:
        """Rank papers by relevance to user's corpus."""
        _emit_step_event("relevance_assessment", "Ranking papers")

        config = state["config"]
        papers = state["discovered_papers"]
        corpus = state["zotero_papers"]

        if not papers:
            _emit_step_event("relevance_assessment", "No papers to rank")
            state["info"].append("No papers to rank")
            return {"info": state["info"]}

        try:
            # Use reranker to score papers
            reranker = PaperReranker(papers=papers, corpus=corpus)
            scored_papers = reranker.rerank()

            # Take top N papers
            top_papers = scored_papers[: config.max_papers]

            # Emit paper found events
            for scored_paper in top_papers:
                _emit_paper_found_event(
                    scored_paper.paper.title,
                    scored_paper.paper.arxiv_id,
                    scored_paper.score,
                )

            _emit_step_event(
                "relevance_assessment", f"Ranked {len(scored_papers)} papers, selected top {len(top_papers)}"
            )

            state["scored_papers"] = top_papers
            state["info"].append(f"Ranked papers by relevance, selected top {len(top_papers)}")

            return {
                "scored_papers": top_papers,
                "info": state["info"],
            }

        except Exception as e:
            _emit_error_event(str(e), "relevance_assessment")
            state["errors"].append(str(e))
            return {"errors": state["errors"]}

    def content_generation_node(state: AgentState) -> dict[str, Any]:
        """Generate TLDR summaries and email content."""
        _emit_step_event("content_generation", "Generating content")

        config = state["config"]
        scored_papers = state["scored_papers"]

        if not scored_papers:
            if config.send_empty:
                # Generate empty email
                email_content = construct_email_content([])
                state["email_content"] = email_content
                state["info"].append("Generated empty digest")
                return {"email_content": email_content, "info": state["info"]}
            _emit_step_event("content_generation", "No papers, skipping email")
            state["info"].append("No papers to include in digest")
            return {"info": state["info"]}

        try:
            # Generate TLDRs (placeholder - would use LLM in production)
            # For now, use paper summaries
            for scored_paper in scored_papers:
                if not scored_paper.paper.tldr:
                    # Use first 200 chars of summary as TLDR
                    scored_paper.paper.tldr = scored_paper.paper.summary[:200] + "..."

            # Construct email
            email_content = construct_email_content(scored_papers)

            _emit_step_event("content_generation", f"Generated digest with {len(scored_papers)} papers")

            state["email_content"] = email_content
            state["info"].append(f"Generated email content with {len(scored_papers)} papers")

            return {
                "email_content": email_content,
                "info": state["info"],
            }

        except Exception as e:
            _emit_error_event(str(e), "content_generation")
            state["errors"].append(str(e))
            return {"errors": state["errors"]}

    def communication_node(state: AgentState) -> dict[str, Any]:
        """Send email notification."""
        _emit_step_event("communication", "Sending notification")

        config = state["config"]
        email_content = state.get("email_content")

        if not email_content:
            _emit_step_event("communication", "No email content, skipping")
            state["info"].append("No email to send")
            return {"info": state["info"]}

        if not config.send_email:
            _emit_step_event("communication", "Email disabled, skipping")
            state["info"].append("Email notifications disabled")
            return {"info": state["info"]}

        if not config.smtp:
            _emit_error_event("SMTP configuration missing", "communication")
            state["errors"].append("SMTP configuration missing")
            return {"errors": state["errors"]}

        try:
            # Send email
            recipient = config.recipient_email or config.smtp.user
            success = send_email(email_content, config.smtp, recipient)

            if success:
                _emit_email_sent_event(recipient, len(email_content.papers))

                # Record notification
                notification_key = f"paperscout:notifications:{user_id}:{date.today().isoformat()}"
                store.set(
                    notification_key,
                    {
                        "date": date.today().isoformat(),
                        "papers_count": len(email_content.papers),
                        "recipient": recipient,
                        "arxiv_ids": [p.arxiv_id for p in email_content.papers],
                        "sent_at": datetime.now().isoformat(),
                    },
                )

                # Mark papers as emailed
                emailed_key = f"paperscout:emailed:{user_id}"
                emailed_papers = store.get(emailed_key) or set()
                for paper in email_content.papers:
                    emailed_papers.add(paper.arxiv_id)
                store.set(emailed_key, emailed_papers)

                state["info"].append(f"Email sent to {recipient} with {len(email_content.papers)} papers")
                return {"info": state["info"]}
            _emit_error_event("Failed to send email", "communication")
            state["errors"].append("Failed to send email")
            return {"errors": state["errors"]}

        except Exception as e:
            _emit_error_event(str(e), "communication")
            state["errors"].append(str(e))
            return {"errors": state["errors"]}

    return {
        "profile_analysis": profile_analysis_node,
        "data_collection": data_collection_node,
        "relevance_assessment": relevance_assessment_node,
        "content_generation": content_generation_node,
        "communication": communication_node,
    }


__all__ = ["make_nodes"]
