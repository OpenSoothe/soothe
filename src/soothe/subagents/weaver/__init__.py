"""Weaver subagent -- generative agent framework with skill harmonization (RFC-0005).

Composes skills from Skillify, resolves conflicts/overlaps/gaps, and generates
Soothe-compatible SubAgent packages that can be loaded dynamically at startup
or executed inline during the session.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from soothe.subagents.weaver.analyzer import RequirementAnalyzer
from soothe.subagents.weaver.composer import AgentComposer
from soothe.subagents.weaver.generator import AgentGenerator
from soothe.subagents.weaver.registry import GeneratedAgentRegistry
from soothe.subagents.weaver.reuse import ReuseIndex

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent
    from langchain_core.language_models import BaseChatModel

    from soothe.subagents.weaver.models import (
        AgentManifest,
        CapabilitySignature,
        ReuseCandidate,
    )

logger = logging.getLogger(__name__)

_MIN_CHUNK_TUPLE_LENGTH = 2

WEAVER_DESCRIPTION = (
    "Generative agent framework that creates task-specific subagents on the fly. "
    "Given a task that existing subagents cannot handle, Weaver analyses requirements, "
    "fetches relevant skills, resolves conflicts between skills from different sources, "
    "generates a new specialist agent, and executes it. Use when no existing subagent "
    "fits the user's specialized task."
)


# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------


def _emit_progress(event: dict[str, Any]) -> None:
    from soothe.utils.progress import emit_progress

    emit_progress(event, logger)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class WeaverState(dict):
    """State for the Weaver LangGraph."""

    messages: Annotated[list, add_messages]


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def _build_weaver_graph(
    analyzer: RequirementAnalyzer,
    reuse_index: ReuseIndex,
    composer: AgentComposer,
    generator: AgentGenerator,
    registry: GeneratedAgentRegistry,
    skillify_retriever: Any | None,
    model: BaseChatModel,
    policy: Any | None = None,
    policy_profile: str = "standard",
) -> Any:
    """Build and compile the Weaver LangGraph.

    Graph: analyze -> check_reuse -> [route]
             hit: load_existing -> execute
             miss: fetch_skills -> compose -> generate -> register -> execute
    """
    # -- Shared async helpers -----------------------------------------------

    def _check_policy(action: str, tool_name: str, tool_args: dict[str, Any] | None = None) -> None:
        if policy is None:
            return
        from soothe.protocols.policy import ActionRequest, PermissionSet, PolicyContext

        permissions = PermissionSet(frozenset())
        get_profile = getattr(policy, "get_profile", None)
        if callable(get_profile):
            profile = get_profile(policy_profile)
            if profile is not None:
                permissions = profile.permissions

        decision = policy.check(
            ActionRequest(action_type=action, tool_name=tool_name, tool_args=tool_args or {}),
            PolicyContext(active_permissions=permissions, thread_id=None),
        )
        if decision.verdict == "deny":
            msg = f"Policy denied {action}:{tool_name} - {decision.reason}"
            raise ValueError(msg)

    async def _validate_package(
        manifest: AgentManifest,
        output_dir: Path,
        capability: CapabilitySignature,
    ) -> None:
        if not manifest.name.strip():
            msg = "Generated manifest has empty name"
            raise ValueError(msg)
        if not manifest.system_prompt_file.strip():
            msg = "Generated manifest has empty system_prompt_file"
            raise ValueError(msg)
        prompt_path = output_dir / manifest.system_prompt_file
        if not prompt_path.is_file():
            msg = "Generated package missing system prompt file"
            raise ValueError(msg)
        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
        if not prompt_text:
            msg = "Generated system prompt is empty"
            raise ValueError(msg)

        # Validate tool usage against policy before registration.
        for tool in manifest.tools:
            _check_policy(action="tool_call", tool_name=tool, tool_args={"path": "*"})
        _check_policy(action="subagent_spawn", tool_name=manifest.name, tool_args={"goal": capability.description})

    async def _analyze_and_route(state: dict[str, Any]) -> dict[str, Any]:
        """Analyse request, check reuse, and either load or generate."""
        messages = state.get("messages", [])
        task_text = ""
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "human":
                task_text = msg.content if hasattr(msg, "content") else str(msg)
                break
        if not task_text and messages:
            last = messages[-1]
            task_text = last.content if hasattr(last, "content") else str(last)

        # Step 1: Analyse
        _emit_progress({"type": "soothe.weaver.analysis.started", "task_preview": task_text[:200]})
        capability = await analyzer.analyze(task_text)
        _emit_progress(
            {
                "type": "soothe.weaver.analysis.completed",
                "capabilities": capability.required_capabilities,
                "constraints": capability.constraints,
            }
        )

        # Step 2: Check reuse
        reuse_candidate = await reuse_index.find_reusable(capability)

        if reuse_candidate:
            _emit_progress(
                {
                    "type": "soothe.weaver.reuse.hit",
                    "agent_name": reuse_candidate.manifest.name,
                    "confidence": round(reuse_candidate.confidence, 3),
                }
            )
            return await _execute_existing(reuse_candidate, task_text)

        best_conf = 0.0
        _emit_progress({"type": "soothe.weaver.reuse.miss", "best_confidence": round(best_conf, 3)})

        # Step 3: Fetch skills (with indexing-not-ready tolerance)
        from soothe.subagents.skillify.models import SkillBundle

        skill_bundle = SkillBundle(query=capability.description)
        if skillify_retriever:
            if hasattr(skillify_retriever, "is_ready") and not skillify_retriever.is_ready:
                _emit_progress({"type": "soothe.weaver.skillify_pending"})
                ready_event = getattr(skillify_retriever, "_ready_event", None)
                if ready_event is not None:
                    try:
                        await asyncio.wait_for(ready_event.wait(), timeout=30.0)
                    except TimeoutError:
                        logger.warning("Skillify index not ready after 30s, proceeding best-effort")
            try:
                skill_bundle = await skillify_retriever.retrieve(capability.description)
                if skill_bundle.query.startswith("[Indexing in progress]"):
                    logger.warning("Skillify still indexing; Weaver proceeding with empty skills")
                    skill_bundle = SkillBundle(query=capability.description)
            except Exception:
                logger.warning("Skillify retrieval failed", exc_info=True)

        # Step 4: Compose (with harmonization)
        _emit_progress(
            {
                "type": "soothe.weaver.harmonize.started",
                "skill_count": len(skill_bundle.results),
            }
        )
        blueprint = await composer.compose(capability, skill_bundle)
        _emit_progress(
            {
                "type": "soothe.weaver.harmonize.completed",
                "retained": len(blueprint.harmonized.skills),
                "dropped": len(blueprint.harmonized.dropped_skills),
                "bridge_length": len(blueprint.harmonized.bridge_instructions),
            }
        )

        # Step 5: Generate
        _check_policy(action="subagent_spawn", tool_name="weaver.generate", tool_args={"goal": capability.description})
        _emit_progress({"type": "soothe.weaver.generate.started", "agent_name": blueprint.agent_name})
        output_dir = registry.base_dir / blueprint.agent_name
        manifest = await generator.generate(blueprint, output_dir)
        _emit_progress(
            {
                "type": "soothe.weaver.generate.completed",
                "agent_name": manifest.name,
                "path": str(output_dir),
            }
        )

        # Step 5.5: Validate package (hard-fail on validation/policy errors)
        _emit_progress({"type": "soothe.weaver.validate.started", "agent_name": manifest.name})
        await _validate_package(manifest, output_dir, capability)
        _emit_progress({"type": "soothe.weaver.validate.completed", "agent_name": manifest.name})

        # Step 6: Register and index
        _check_policy(action="subagent_spawn", tool_name="weaver.register", tool_args={"agent_name": manifest.name})
        registry.register(manifest, output_dir)
        await reuse_index.index_agent(manifest, str(output_dir))
        _emit_progress(
            {
                "type": "soothe.weaver.registry.updated",
                "agent_name": manifest.name,
                "version": manifest.version,
            }
        )

        # Step 7: Execute inline
        return await _execute_generated(manifest, output_dir, task_text, model)

    async def _execute_existing(candidate: ReuseCandidate, task: str) -> dict[str, Any]:
        """Execute an existing generated agent."""
        agent_dir = Path(candidate.path)
        return await _execute_generated(candidate.manifest, agent_dir, task, model)

    async def _execute_generated(
        manifest: AgentManifest,
        agent_dir: Path,
        task: str,
        llm: BaseChatModel,
    ) -> dict[str, Any]:
        """Instantiate and execute a generated SubAgent inline."""
        _emit_progress(
            {
                "type": "soothe.weaver.execute.started",
                "agent_name": manifest.name,
                "task_preview": task[:200],
            }
        )

        prompt_path = agent_dir / manifest.system_prompt_file
        system_prompt = ""
        if prompt_path.is_file():
            system_prompt = prompt_path.read_text(encoding="utf-8")

        try:
            from deepagents import create_deep_agent
            from langchain_core.messages import HumanMessage

            agent = create_deep_agent(
                model=llm,
                system_prompt=system_prompt,
            )

            result_text = ""
            async for chunk in agent.astream(
                {"messages": [HumanMessage(content=task)]},
                stream_mode=["messages"],
            ):
                if isinstance(chunk, tuple) and len(chunk) >= _MIN_CHUNK_TUPLE_LENGTH:
                    _, data = chunk[0] if len(chunk) == 1 else (chunk[0], chunk[1])
                    if isinstance(data, tuple) and len(data) >= 1:
                        msg = data[0]
                        if hasattr(msg, "content") and isinstance(msg.content, str):
                            result_text += msg.content

            if not result_text:
                result = await agent.ainvoke({"messages": [HumanMessage(content=task)]})
                result_chunks = [
                    str(msg.content)
                    for msg in result.get("messages", [])
                    if hasattr(msg, "content") and hasattr(msg, "type") and msg.type == "ai"
                ]
                result_text = "\n".join(result_chunks) or "Agent completed but produced no output."

        except Exception:
            logger.exception("Generated agent execution failed")
            result_text = f"Generated agent '{manifest.name}' encountered an error during execution."

        _emit_progress(
            {
                "type": "soothe.weaver.execute.completed",
                "agent_name": manifest.name,
                "result_length": len(result_text),
            }
        )

        return {"messages": [AIMessage(content=result_text)]}

    # -- Sync wrapper -------------------------------------------------------

    def run_sync(state: dict[str, Any]) -> dict[str, Any]:
        """Sync wrapper -- deepagents calls graph nodes in a thread pool."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(_analyze_and_route(state))
            finally:
                new_loop.close()
        else:
            return loop.run_until_complete(_analyze_and_route(state))

    # -- Build graph --------------------------------------------------------

    graph = StateGraph(WeaverState)
    graph.add_node("weave", run_sync)
    graph.add_edge(START, "weave")
    graph.add_edge("weave", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def create_weaver_subagent(
    model: str | BaseChatModel | None = None,
    *,
    config: Any | None = None,
    **_kwargs: Any,
) -> CompiledSubAgent:
    """Create a Weaver subagent (CompiledSubAgent).

    Args:
        model: LLM model string or instance for analysis, composition,
            and generation.
        config: ``SootheConfig`` instance for vector store, embedding model,
            and weaver-specific settings.
        **kwargs: Additional config (ignored for forward compat).

    Returns:
        ``CompiledSubAgent`` dict compatible with deepagents.
    """
    import os

    from langchain.chat_models import init_chat_model

    from soothe.config import SOOTHE_HOME, SootheConfig

    cfg: SootheConfig = config if isinstance(config, SootheConfig) else SootheConfig()
    from soothe.backends.policy.config_driven import ConfigDrivenPolicy

    if model is None:
        msg = (
            "Weaver subagent requires a model. Pass a model string "
            "(e.g. 'openai:gpt-4o-mini') or a BaseChatModel instance."
        )
        raise ValueError(msg)
    if isinstance(model, str):
        model_kwargs: dict[str, Any] = {}
        base_url = os.environ.get("OPENAI_BASE_URL")
        if base_url:
            model_kwargs["base_url"] = base_url
            model_kwargs["use_responses_api"] = False
        resolved_model: BaseChatModel = init_chat_model(model, **model_kwargs)
    else:
        resolved_model = model

    weaver_cfg = cfg.weaver if hasattr(cfg, "weaver") else None
    generated_agents_dir = getattr(weaver_cfg, "generated_agents_dir", "") or str(
        Path(SOOTHE_HOME) / "generated_agents"
    )
    reuse_threshold = getattr(weaver_cfg, "reuse_threshold", 0.85) if weaver_cfg else 0.85
    reuse_collection = (
        getattr(weaver_cfg, "reuse_collection", "soothe_weaver_reuse") if weaver_cfg else "soothe_weaver_reuse"
    )
    allowed_tools = getattr(weaver_cfg, "allowed_tool_groups", []) if weaver_cfg else []

    vector_store, embeddings = _resolve_dependencies(cfg, reuse_collection)

    analyzer_inst = RequirementAnalyzer(model=resolved_model)
    reuse_inst = ReuseIndex(
        vector_store=vector_store,
        embeddings=embeddings,
        threshold=reuse_threshold,
        collection=reuse_collection,
        embedding_dims=cfg.embedding_dims,
    )
    composer_inst = AgentComposer(
        model=resolved_model,
        allowed_tool_groups=allowed_tools,
    )
    generator_inst = AgentGenerator(model=resolved_model)
    registry_inst = GeneratedAgentRegistry(base_dir=Path(generated_agents_dir))

    skillify_retriever = _get_skillify_retriever(cfg)

    runnable = _build_weaver_graph(
        analyzer=analyzer_inst,
        reuse_index=reuse_inst,
        composer=composer_inst,
        generator=generator_inst,
        registry=registry_inst,
        skillify_retriever=skillify_retriever,
        model=resolved_model,
        policy=ConfigDrivenPolicy(),
        policy_profile=cfg.protocols.policy.profile,
    )

    spec: CompiledSubAgent = {
        "name": "weaver",
        "description": WEAVER_DESCRIPTION,
        "runnable": runnable,
    }
    spec["_weaver_reuse_index"] = reuse_inst  # type: ignore[typeddict-unknown-key]
    return spec


def _resolve_dependencies(cfg: Any, collection: str) -> tuple[Any, Any]:
    """Resolve VectorStore and Embeddings for the reuse index."""
    vector_store_config = cfg.resolve_vector_store_config()
    if cfg.vector_store_provider != "none":
        from soothe.backends.vector_store import create_vector_store

        vs = create_vector_store(
            cfg.vector_store_provider,
            collection,
            vector_store_config,
        )
    else:
        from soothe.backends.vector_store.in_memory import InMemoryVectorStore

        vs = InMemoryVectorStore(collection)

    embeddings = cfg.create_embedding_model()
    return vs, embeddings


def _get_skillify_retriever(cfg: Any) -> Any | None:
    """Try to get a SkillRetriever instance if Skillify is configured."""
    try:
        skillify_cfg = cfg.skillify if hasattr(cfg, "skillify") else None
        if skillify_cfg and getattr(skillify_cfg, "enabled", False):
            from soothe.backends.vector_store.in_memory import InMemoryVectorStore
            from soothe.subagents.skillify.retriever import SkillRetriever

            collection = getattr(skillify_cfg, "index_collection", "soothe_skillify")
            vector_store_config = cfg.resolve_vector_store_config()
            if cfg.vector_store_provider != "none":
                from soothe.backends.vector_store import create_vector_store

                vs = create_vector_store(cfg.vector_store_provider, collection, vector_store_config)
            else:
                vs = InMemoryVectorStore(collection)
            embeddings = cfg.create_embedding_model()
            return SkillRetriever(vector_store=vs, embeddings=embeddings)
    except Exception:
        logger.debug("Failed to create Skillify retriever for Weaver", exc_info=True)
    return None
