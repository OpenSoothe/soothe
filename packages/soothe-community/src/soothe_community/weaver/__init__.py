"""Weaver subagent plugin -- generative agent framework with skill harmonization (RFC-0005).

Community plugin for Soothe that composes skills from Skillify, resolves
conflicts/overlaps/gaps, and generates Soothe-compatible SubAgent packages
that can be loaded dynamically at startup or executed inline during the session.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from soothe_sdk import plugin, subagent

from .analyzer import RequirementAnalyzer
from .composer import AgentComposer
from .events import (
    WeaverAnalysisCompletedEvent,
    WeaverAnalysisStartedEvent,
    WeaverCompletedEvent,
    WeaverDispatchedEvent,
    WeaverExecuteCompletedEvent,
    WeaverExecuteStartedEvent,
    WeaverGenerateCompletedEvent,
    WeaverGenerateStartedEvent,
    WeaverHarmonizeCompletedEvent,
    WeaverHarmonizeStartedEvent,
    WeaverRegistryUpdatedEvent,
    WeaverReuseHitEvent,
    WeaverReuseMissEvent,
    WeaverSkillifyPendingEvent,
    WeaverValidateCompletedEvent,
    WeaverValidateStartedEvent,
)
from .generator import AgentGenerator
from .registry import GeneratedAgentRegistry
from .reuse import ReuseIndex

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent
    from langchain_core.language_models import BaseChatModel

    from .models import (
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


def _emit_progress(event: dict[str, Any]) -> None:
    from soothe.utils.progress import emit_progress

    emit_progress(event, logger)


class WeaverState(dict):
    """State for the Weaver LangGraph."""

    messages: Annotated[list, add_messages]


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
    """Build and compile the Weaver LangGraph."""

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

        for tool in manifest.tools:
            _check_policy(action="tool_call", tool_name=tool, tool_args={"path": "*"})
        _check_policy(action="subagent_spawn", tool_name=manifest.name, tool_args={"goal": capability.description})

    async def _analyze_and_route(state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get("messages", [])
        task_text = ""
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "human":
                task_text = msg.content if hasattr(msg, "content") else str(msg)
                break
        if not task_text and messages:
            last = messages[-1]
            task_text = last.content if hasattr(last, "content") else str(last)

        _emit_progress(WeaverDispatchedEvent(task=task_text[:200]).to_dict())

        _emit_progress(WeaverAnalysisStartedEvent(task_preview=task_text[:200]).to_dict())
        capability = await analyzer.analyze(task_text)
        _emit_progress(
            WeaverAnalysisCompletedEvent(
                capabilities=capability.required_capabilities,
                constraints=capability.constraints,
            ).to_dict()
        )

        reuse_candidate = await reuse_index.find_reusable(capability)

        if reuse_candidate:
            _emit_progress(
                WeaverReuseHitEvent(
                    agent_name=reuse_candidate.manifest.name,
                    confidence=round(reuse_candidate.confidence, 3),
                ).to_dict()
            )
            return await _execute_existing(reuse_candidate, task_text)

        best_conf = 0.0
        _emit_progress(WeaverReuseMissEvent(best_confidence=round(best_conf, 3)).to_dict())

        # Fetch skills (with indexing-not-ready tolerance)
        from soothe_community.skillify.models import SkillBundle

        skill_bundle = SkillBundle(query=capability.description)
        if skillify_retriever:
            if hasattr(skillify_retriever, "is_ready") and not skillify_retriever.is_ready:
                _emit_progress(WeaverSkillifyPendingEvent().to_dict())
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

        _emit_progress(
            WeaverHarmonizeStartedEvent(
                skill_count=len(skill_bundle.results),
            ).to_dict()
        )
        blueprint = await composer.compose(capability, skill_bundle)
        _emit_progress(
            WeaverHarmonizeCompletedEvent(
                retained=len(blueprint.harmonized.skills),
                dropped=len(blueprint.harmonized.dropped_skills),
                bridge_length=len(blueprint.harmonized.bridge_instructions),
            ).to_dict()
        )

        _check_policy(action="subagent_spawn", tool_name="weaver.generate", tool_args={"goal": capability.description})
        _emit_progress(WeaverGenerateStartedEvent(agent_name=blueprint.agent_name).to_dict())
        output_dir = registry.base_dir / blueprint.agent_name
        manifest = await generator.generate(blueprint, output_dir)
        _emit_progress(
            WeaverGenerateCompletedEvent(
                agent_name=manifest.name,
                path=str(output_dir),
            ).to_dict()
        )

        _emit_progress(WeaverValidateStartedEvent(agent_name=manifest.name).to_dict())
        await _validate_package(manifest, output_dir, capability)
        _emit_progress(WeaverValidateCompletedEvent(agent_name=manifest.name).to_dict())

        _check_policy(action="subagent_spawn", tool_name="weaver.register", tool_args={"agent_name": manifest.name})
        registry.register(manifest, output_dir)
        await reuse_index.index_agent(manifest, str(output_dir))
        _emit_progress(
            WeaverRegistryUpdatedEvent(
                agent_name=manifest.name,
                version=manifest.version,
            ).to_dict()
        )

        return await _execute_generated(manifest, output_dir, task_text, model)

    async def _execute_existing(candidate: ReuseCandidate, task: str) -> dict[str, Any]:
        agent_dir = Path(candidate.path)
        return await _execute_generated(candidate.manifest, agent_dir, task, model)

    async def _execute_generated(
        manifest: AgentManifest,
        agent_dir: Path,
        task: str,
        llm: BaseChatModel,
    ) -> dict[str, Any]:
        _emit_progress(
            WeaverExecuteStartedEvent(
                agent_name=manifest.name,
                task_preview=task[:200],
            ).to_dict()
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
            WeaverExecuteCompletedEvent(
                agent_name=manifest.name,
                result_length=len(result_text),
            ).to_dict()
        )

        _emit_progress(
            WeaverCompletedEvent(
                duration_ms=0,
                agent_name=manifest.name,
            ).to_dict()
        )

        return {"messages": [AIMessage(content=result_text)]}

    def run_sync(state: dict[str, Any]) -> dict[str, Any]:
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

    graph = StateGraph(WeaverState)
    graph.add_node("weave", run_sync)
    graph.add_edge(START, "weave")
    graph.add_edge("weave", END)
    return graph.compile()


def _resolve_dependencies(cfg: Any, _collection: str) -> tuple[Any, Any]:
    """Resolve VectorStore and Embeddings for the reuse index."""
    vs = cfg.create_vector_store_for_role("weaver_reuse")
    embeddings = cfg.create_embedding_model()
    return vs, embeddings


@plugin(
    name="weaver",
    version="1.0.0",
    description="Generative agent framework with skill harmonization",
    dependencies=[
        "langgraph>=0.2.0",
    ],
    trust_level="standard",
)
class WeaverPlugin:
    """Weaver community plugin for generative agent creation."""

    def __init__(self) -> None:
        self._reuse_index: ReuseIndex | None = None

    async def on_load(self, context: Any) -> None:
        """Verify Skillify is available and trigger event registration."""
        import soothe_community.weaver.events  # noqa: F401

        try:
            from soothe_community.skillify.models import SkillBundle  # noqa: F401

            context.logger.info("Weaver plugin loaded (Skillify available)")
        except ImportError:
            from soothe.plugin.exceptions import PluginError

            raise PluginError(
                "Weaver requires Skillify plugin. Install soothe-community with skillify support.",
                plugin_name="weaver",
            )

    async def on_unload(self) -> None:
        """Close the reuse index."""
        if self._reuse_index is not None:
            try:
                await self._reuse_index.close()
            except Exception:
                pass
            self._reuse_index = None

    @subagent(
        name="weaver",
        description=WEAVER_DESCRIPTION,
        model="openai:gpt-4o-mini",
    )
    async def create_weaver(
        self,
        model: str | BaseChatModel | None,
        config: Any,
        context: Any,
        **_kwargs: Any,
    ) -> CompiledSubAgent:
        """Create a Weaver subagent.

        Args:
            model: LLM model for analysis, composition, and generation.
            config: SootheConfig instance.
            context: Plugin context with weaver-specific config.
            **_kwargs: Additional config (ignored).

        Returns:
            CompiledSubAgent dict.
        """
        from langchain.chat_models import init_chat_model

        from soothe.config import SOOTHE_HOME, SootheConfig
        from soothe.core.config_driven import ConfigDrivenPolicy

        cfg: SootheConfig = config if isinstance(config, SootheConfig) else SootheConfig()

        if model is None:
            msg = "Weaver subagent requires a model."
            raise ValueError(msg)
        if isinstance(model, str):
            if isinstance(cfg, SootheConfig) and ":" in model:
                provider_name = model.split(":", 1)[0]
                provider_names = [p.name for p in cfg.providers] if cfg.providers else []
                if provider_name in provider_names:
                    cache_key = model
                    if cache_key in cfg._model_cache:
                        resolved_model = cfg._model_cache[cache_key]
                    else:
                        _, _, model_name = model.partition(":")
                        provider_type, kwargs = cfg._provider_kwargs(provider_name)
                        init_str = f"{provider_type}:{model_name}" if provider_name else model
                        resolved_model: BaseChatModel = init_chat_model(init_str, **kwargs)
                        cfg._model_cache[cache_key] = resolved_model
                else:
                    model_kwargs: dict[str, Any] = {}
                    base_url = os.environ.get("OPENAI_BASE_URL")
                    if base_url:
                        model_kwargs["base_url"] = base_url
                        model_kwargs["use_responses_api"] = False
                    resolved_model: BaseChatModel = init_chat_model(model, **model_kwargs)
            else:
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
        self._reuse_index = ReuseIndex(
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

        # Try to create skillify retriever from plugin config
        skillify_retriever = None
        skillify_cfg = cfg.skillify if hasattr(cfg, "skillify") else None
        if skillify_cfg and getattr(skillify_cfg, "enabled", False):
            try:
                from soothe_community.skillify.retriever import SkillRetriever

                vs = cfg.create_vector_store_for_role("skillify")
                skill_embeddings = cfg.create_embedding_model()
                skillify_retriever = SkillRetriever(vector_store=vs, embeddings=skill_embeddings)
            except Exception:
                logger.debug("Failed to create Skillify retriever for Weaver", exc_info=True)

        runnable = _build_weaver_graph(
            analyzer=analyzer_inst,
            reuse_index=self._reuse_index,
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
        spec["_weaver_reuse_index"] = self._reuse_index  # type: ignore[typeddict-unknown-key]
        return spec

    def get_subagents(self) -> list[Any]:
        """Get list of subagent factory functions."""
        return [self.create_weaver]
