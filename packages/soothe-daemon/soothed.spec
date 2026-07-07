# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for soothe-daemon (macOS, --onedir)."""

import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH).resolve()
SRC = ROOT / "src"
SOOTHE_SRC = ROOT.parent / "soothe" / "src"
SDK_SRC = ROOT.parent / "soothe-sdk" / "src"

a = Analysis(
    [str(ROOT / "pyinstaller_entry.py")],
    pathex=[str(SRC), str(SOOTHE_SRC), str(SDK_SRC)],
    binaries=[],
    datas=[
        # Prompt XML fragments loaded via pathlib.Path.read_text()
        (str(SOOTHE_SRC / "soothe" / "core" / "prompts" / "fragments"), "soothe/core/prompts/fragments"),
        # Memu memory config (YAML + prompts)
        (str(SOOTHE_SRC / "soothe" / "backends" / "memory" / "memu" / "config"), "soothe/backends/memory/memu/config"),
        # Built-in skills (SKILL.md files)
        (str(SOOTHE_SRC / "soothe" / "skills" / "builtin_skills"), "soothe/skills/builtin_skills"),
        # SQL migration scripts loaded via pathlib at runtime
        (str(SOOTHE_SRC / "soothe" / "core" / "persistence" / "sql"), "soothe/core/persistence/sql"),
    ],
    hiddenimports=[
        # ── Channel modules (dynamically loaded by registry.py) ──
        "soothe_daemon.channels.dingtalk",
        "soothe_daemon.channels.discord",
        "soothe_daemon.channels.email",
        "soothe_daemon.channels.feishu",
        "soothe_daemon.channels.http_rest",
        "soothe_daemon.channels.matrix",
        "soothe_daemon.channels.mochat",
        "soothe_daemon.channels.msteams",
        "soothe_daemon.channels.platform_helpers",
        "soothe_daemon.channels.qq",
        "soothe_daemon.channels.signal",
        "soothe_daemon.channels.slack",
        "soothe_daemon.channels.telegram",
        "soothe_daemon.channels.websocket",
        "soothe_daemon.channels.wecom",
        "soothe_daemon.channels.weixin",
        "soothe_daemon.channels.whatsapp",
        # ── Health checks (deferred imports in HealthChecker) ──
        "soothe_daemon.health.checks.config_check",
        "soothe_daemon.health.checks.daemon_check",
        "soothe_daemon.health.checks.protocols_check",
        "soothe_daemon.health.checks.vector_stores_check",
        "soothe_daemon.health.checks.providers_check",
        "soothe_daemon.health.checks.mcp_check",
        "soothe_daemon.health.checks.embedding_warmup_check",
        "soothe_daemon.health.checks.external_apis_check",
        "soothe_daemon.health.checks.observability_check",
        "soothe_daemon.persistence.health_check",
        # ── Backend modules (dynamically loaded by protocols_check) ──
        "soothe.backends.memory.memu_adapter",
        "soothe.backends.durability.postgresql",
        "soothe.backends.durability.sqlite",
        "soothe.backends.vector_store.pgvector",
        "soothe.backends.vector_store.weaviate",
        "soothe.backends.vector_store.sqlite_vec",
        # ── Middleware (lazy-loaded via __getattr__) ──
        "soothe.middleware._builder",
        "soothe.middleware._utils",
        "soothe.middleware.code_interpreter",
        "soothe.middleware.execution_hints",
        "soothe.middleware.file_lock",
        "soothe.middleware.filesystem",
        "soothe.middleware.llm_rate_limit",
        "soothe.middleware.mcp_tool_search",
        "soothe.middleware.per_turn_model",
        "soothe.middleware.policy",
        "soothe.middleware.system_prompt",
        "soothe.middleware.workspace_context",
        # ── Workspace (lazy-loaded via __getattr__) ──
        "soothe.core.workspace.resolution",
        "soothe.core.workspace.loop_workspace",
        "soothe.core.workspace.stream_resolution",
        "soothe.core.workspace.runtime_resolution",
        "soothe.core.workspace.normalized_backend",
        "soothe.core.workspace.framework_filesystem",
        "soothe.core.workspace.virtual_home",
        "soothe.core.workspace.context",
        "soothe.core.workspace.core_resolution",
        "soothe.core.workspace.migration",
        # ── Core (lazy-loaded via __getattr__) ──
        "soothe.core.agent",
        "soothe.core.runner",
        "soothe.core.security",
        "soothe.core.prompts",
        "soothe.core.events.internal_bus",
        "soothe.core.events.internal_events",
        # ── Subagent plugins (discovered by discovery.py) ──
        "soothe.subagents.explore",
        "soothe.subagents.plan",
        "soothe.subagents.deep_research",
        # ── Toolkit plugins (discovered by discovery.py) ──
        "soothe.toolkits.execution",
        "soothe.toolkits.file_ops",
        "soothe.toolkits.data",
        "soothe.toolkits.datetime",
        "soothe.toolkits.wizsearch",
        "soothe.toolkits.http_requests",
        "soothe.toolkits.image",
        "soothe.toolkits.audio",
        "soothe.toolkits.video",
        # ── SDK ──
        "soothe_sdk._upstream_warnings",
        # ── Native extensions & key deps ──
        "psycopg",
        "psycopg.pq",
        "psycopg_pool",
        "sqlite_vec",
        "Crypto",
        "Crypto.Cipher",
        "Crypto.Hash",
        "cryptography",
        "cryptography.hazmat",
        "aiohttp",
        "uvloop",
        "multiprocessing",
        "multiprocessing.spawn",
        # ── LangChain ecosystem ──
        "langchain",
        "langchain_core",
        "langchain_openai",
        "langchain_community",
        "langchain_experimental",
        "langgraph",
        "langgraph.checkpoint",
        "langchain_community.tools.file_management",
        # ── Optional third-party (probed via find_spec) ──
        "langfuse",
        "sentence_transformers",
        "websockets",
        "discord",
        "jwt",
        "wecom_aibot_sdk",
        "lark_oapi",
        # ── Python stdlib sometimes missed ──
        "encodings",
        "codecs",
        "email.mime",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "torchvision",
        "torchaudio",
        "tensorflow",
        "keras",
        "jax",
        "jaxlib",
        "triton",
        "onnxruntime",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        "scipy",
        "sklearn",
        "tkinter",
        "_tkinter",
        "test",
        "tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Collect all submodules for packages with complex import trees
for pkg in [
    "soothe_daemon",
    "soothe",
    "soothe_sdk",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_community",
    "langgraph",
    "pydantic",
    "pydantic_settings",
]:
    try:
        a.hiddenimports += collect_submodules(pkg)  # noqa: F821
    except Exception:
        pass

# Collect data files for packages that ship JSON schemas or metadata
for pkg in ["langchain_core", "pydantic", "pydantic_core"]:
    try:
        a.datas += collect_data_files(pkg)  # noqa: F821
    except Exception:
        pass

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="soothed",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="soothed",
)
