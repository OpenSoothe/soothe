"""Vulture whitelist for soothe-sdk protocol method parameters.

These names are interface contract parameters in abstract/protocol methods
whose bodies are ``...`` (ellipsis). Vulture flags them as unused because
the body doesn't reference them, but they define the callable signature.
"""


# core_agent.py — astream / execution_astream / execute_stream parameters
execution_scope  # noqa: F841
input_arg  # noqa: F841
stream_mode  # noqa: F841
subgraphs  # noqa: F841

# durability.py — DurabilityStore protocol parameters
thread_id  # noqa: F841
thread_filter  # noqa: F841

# identity.py — IdentityService protocol parameters
expiry_days  # noqa: F841
aksk_id  # noqa: F841
access_key  # noqa: F841
refresh_token  # noqa: F841
jti  # noqa: F841
active_only  # noqa: F841
channel  # noqa: F841
sender_id  # noqa: F841

# memory.py — MemoryStore protocol parameters
limit  # noqa: F841
item_id  # noqa: F841

# operation_security.py — OperationSecurity protocol parameters
request  # noqa: F841

# policy.py — PolicyProtocol parameters
child_name  # noqa: F841
parent_permissions  # noqa: F841

# vector_store.py — VectorStore protocol parameters
distance  # noqa: F841
vector_size  # noqa: F841
vectors  # noqa: F841
payloads  # noqa: F841
vector  # noqa: F841
filters  # noqa: F841
record_id  # noqa: F841
