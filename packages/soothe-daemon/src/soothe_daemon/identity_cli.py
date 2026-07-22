"""Identity service CLI commands. RFC-307 §CLI Commands.

Provides soothed identity subcommands for:
- User management (create-user, list-users, delete-user)
- AKSK management (create-aksk, list-aksk, revoke-aksk)
- Token management (list-tokens, revoke-token, revoke-all-tokens)
- External identity mapping (map-external, list-mappings, unmap-external)
- Service status (status)
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from soothe.identity import IdentityService

app = typer.Typer(
    name="identity",
    help="Identity service management - users, AKSK, tokens, external mappings",
)
console = Console()


def _get_jwt_key() -> str:
    """Get or generate JWT signing key."""
    key = os.environ.get("SOOTHE_JWT_KEY")
    if key:
        return key

    from soothe_sdk.paths import SOOTHE_HOME

    key_file = SOOTHE_HOME / ".jwt_key"

    if key_file.exists():
        return key_file.read_text().strip()

    # Generate new key
    import secrets

    key = secrets.token_urlsafe(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key)
    key_file.chmod(0o600)
    console.print(f"[yellow]Generated new JWT key at {key_file}[/yellow]")
    return key


def _get_identity_service() -> IdentityService:
    """Build IdentityService using the same backend as the daemon (unified persistence)."""
    from soothe.identity import IdentityService
    from soothe_sdk.paths import SOOTHE_DATA_DIR

    jwt_key = _get_jwt_key()

    # Prefer agent config so CLI matches daemon persistence.default_backend.
    try:
        from soothe.config import SootheConfig

        from soothe_daemon.config import default_soothe_config_path

        agent_path = default_soothe_config_path()
        if agent_path.exists():
            cfg = SootheConfig.from_yaml_file(str(agent_path))
            if cfg.persistence.default_backend == "postgresql":
                return IdentityService(
                    jwt_key=jwt_key,
                    enabled=True,
                    postgres_dsn=cfg.resolve_postgres_dsn_for_database("metadata"),
                )
    except Exception:
        pass

    return IdentityService(
        db_path=Path(SOOTHE_DATA_DIR) / "identity.db",
        jwt_key=jwt_key,
        enabled=True,
    )


def _require_enabled() -> None:
    """Check if identity service is enabled in config."""
    from soothe_daemon.config import SootheDaemonConfig, default_daemon_config_path

    config_path = default_daemon_config_path()
    if config_path.exists():
        config = SootheDaemonConfig.from_yaml_file(config_path)
        if not config.identity.enabled:
            console.print("[red]Error: Identity service is disabled[/red]")
            console.print("Enable in daemon config: identity.enabled = true")
            raise typer.Exit(1)


# ============================================================================
# User Commands
# ============================================================================


@app.command("create-user")
def create_user(
    user: Annotated[str, typer.Option("--user", "-u", help="User identifier")],
    metadata: Annotated[str | None, typer.Option("--metadata", "-m", help="JSON metadata")] = None,
) -> None:
    """Create a new user.

    RFC-307 §CLI Commands.
    """
    _require_enabled()

    meta_dict = None
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except json.JSONDecodeError:
            console.print("[red]Error: Invalid JSON metadata[/red]")
            raise typer.Exit(1)

    identity = _get_identity_service()
    user_obj = identity.create_user(user, meta_dict)

    console.print(f"[green]User created:[/green] {user_obj.user_id}")
    console.print(f"  created_at: {user_obj.created_at.isoformat()}")


@app.command("list-users")
def list_users() -> None:
    """List all users.

    RFC-307 §CLI Commands.
    """
    _require_enabled()

    identity = _get_identity_service()
    users = identity.list_users()

    if not users:
        console.print("[yellow]No users found[/yellow]")
        return

    table = Table(title="Users")
    table.add_column("user_id")
    table.add_column("created_at")
    table.add_column("metadata")

    for u in users:
        meta_str = json.dumps(u.metadata) if u.metadata else "-"
        table.add_row(u.user_id, u.created_at.isoformat(), meta_str)

    console.print(table)


@app.command("delete-user")
def delete_user(
    user: Annotated[str, typer.Option("--user", "-u", help="User to delete")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Delete user and revoke all credentials.

    RFC-307 §CLI Commands.

    Warning: This also revokes all AKSK pairs and tokens for the user.
    """
    _require_enabled()

    if not force:
        confirm = typer.confirm(
            f"Delete user '{user}' and revoke all credentials?",
            default=False,
        )
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    identity = _get_identity_service()
    try:
        identity.delete_user(user)
        console.print(f"[green]User deleted:[/green] {user}")
        console.print("  All AKSK pairs and tokens revoked")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


# ============================================================================
# AKSK Commands
# ============================================================================


@app.command("create-aksk")
def create_aksk(
    user: Annotated[str, typer.Option("--user", "-u", help="User identifier")],
    expiry_days: Annotated[
        int | None,
        typer.Option("--expiry-days", "-e", help="AKSK expiry days (None = never)"),
    ] = None,
) -> None:
    """Create AKSK pair for user.

    RFC-307 §CLI Commands.

    WARNING: Save the secret_key securely. It cannot be retrieved later.
    """
    _require_enabled()

    identity = _get_identity_service()
    try:
        aksk = identity.create_aksk(user, expiry_days)

        console.print(f"[green]AKSK created for user:[/green] {user}")
        console.print(f"  aksk_id:       {aksk.aksk_id}")
        console.print(f"  access_key:    {aksk.access_key}")
        console.print("  secret_key:    [bold yellow]SK-...[/bold yellow] (shown below)")
        console.print()
        console.print(
            f"[bold yellow]  secret_key:    {aksk.access_key.replace('AK-', 'SK-')}[/bold yellow]"
        )
        console.print()

        if aksk.expires_at:
            console.print(f"  expires_at:    {aksk.expires_at.isoformat()}")
        else:
            console.print("  expires_at:    never")

        console.print()
        console.print(
            "[bold red]WARNING: Save the secret_key securely. It cannot be retrieved later.[/bold red]"
        )

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command("list-aksk")
def list_aksk(
    user: Annotated[str, typer.Option("--user", "-u", help="User identifier")],
) -> None:
    """List AKSK pairs for user.

    RFC-307 §CLI Commands.
    """
    _require_enabled()

    identity = _get_identity_service()
    aksks = identity.list_aksk(user)

    if not aksks:
        console.print(f"[yellow]No AKSK pairs found for user: {user}[/yellow]")
        return

    table = Table(title=f"AKSK pairs for user: {user}")
    table.add_column("aksk_id")
    table.add_column("access_key")
    table.add_column("created_at")
    table.add_column("expires_at")
    table.add_column("status")

    for a in aksks:
        status = (
            "revoked"
            if a.revoked
            else ("expired" if a.expires_at and datetime.now(UTC) > a.expires_at else "active")
        )
        status_color = "red" if status in ("revoked", "expired") else "green"

        expires_str = a.expires_at.isoformat() if a.expires_at else "never"

        table.add_row(
            a.aksk_id[:8] + "...",
            a.access_key,
            a.created_at.isoformat(),
            expires_str,
            f"[{status_color}]{status}[/{status_color}]",
        )

    console.print(table)


@app.command("revoke-aksk")
def revoke_aksk(
    aksk_id: Annotated[str, typer.Option("--aksk-id", "-a", help="AKSK ID to revoke")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Revoke AKSK and all related tokens.

    RFC-307 §CLI Commands.
    """
    _require_enabled()

    if not force:
        confirm = typer.confirm(
            f"Revoke AKSK '{aksk_id}' and all related tokens?",
            default=False,
        )
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    identity = _get_identity_service()
    try:
        identity.revoke_aksk(aksk_id)
        console.print(f"[green]AKSK revoked:[/green] {aksk_id}")
        console.print("  All related tokens revoked")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Token Commands
# ============================================================================


@app.command("list-tokens")
def list_tokens(
    user: Annotated[str, typer.Option("--user", "-u", help="User identifier")],
    active_only: Annotated[
        bool, typer.Option("--active", "-a", help="Show only active tokens")
    ] = False,
) -> None:
    """List tokens for user.

    RFC-307 §CLI Commands.
    """
    _require_enabled()

    identity = _get_identity_service()
    tokens = identity.list_tokens(user, active_only)

    if not tokens:
        if active_only:
            console.print(f"[yellow]No active tokens for user: {user}[/yellow]")
        else:
            console.print(f"[yellow]No tokens found for user: {user}[/yellow]")
        return

    table = Table(title=f"Tokens for user: {user}" + (" (active only)" if active_only else ""))
    table.add_column("jti")
    table.add_column("type")
    table.add_column("aksk_id")
    table.add_column("issued_at")
    table.add_column("expires_at")
    table.add_column("status")

    for t in tokens:
        status = (
            "revoked"
            if t.revoked
            else ("expired" if datetime.now(UTC) > t.expires_at else "active")
        )
        status_color = "red" if status in ("revoked", "expired") else "green"

        table.add_row(
            t.jti[:8] + "...",
            t.token_type,
            t.aksk_id[:8] + "...",
            t.issued_at.isoformat(),
            t.expires_at.isoformat(),
            f"[{status_color}]{status}[/{status_color}]",
        )

    console.print(table)


@app.command("revoke-token")
def revoke_token(
    jti: Annotated[str, typer.Option("--jti", "-j", help="JWT ID to revoke")],
) -> None:
    """Revoke token by JTI.

    RFC-307 §CLI Commands.
    """
    _require_enabled()

    identity = _get_identity_service()
    try:
        identity.revoke_token(jti)
        console.print(f"[green]Token revoked:[/green] {jti}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command("revoke-all-tokens")
def revoke_all_tokens(
    user: Annotated[str, typer.Option("--user", "-u", help="User identifier")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Revoke all tokens for user.

    RFC-307 §CLI Commands.
    """
    _require_enabled()

    if not force:
        confirm = typer.confirm(
            f"Revoke all tokens for user '{user}'?",
            default=False,
        )
        if not confirm:
            console.print("[yellow]Cancelled[/yellow]")
            raise typer.Exit(0)

    identity = _get_identity_service()
    try:
        identity.revoke_all_tokens(user)
        console.print(f"[green]All tokens revoked for user:[/green] {user}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


# ============================================================================
# External Mapping Commands
# ============================================================================


@app.command("map-external")
def map_external(
    channel: Annotated[
        str, typer.Option("--channel", "-c", help="Channel name (telegram, feishu, etc.)")
    ],
    sender_id: Annotated[str, typer.Option("--sender-id", "-s", help="Platform sender ID")],
    user: Annotated[str, typer.Option("--user", "-u", help="Soothe user_id to map to")],
) -> None:
    """Map external channel sender to soothe user.

    RFC-307 §CLI Commands.

    Example: soothed identity map-external --channel telegram --sender-id 12345 --user alice
    """
    _require_enabled()

    identity = _get_identity_service()
    try:
        mapping = identity.map_external_identity(channel, sender_id, user)
        console.print("[green]External identity mapped:[/green]")
        console.print(f"  channel:    {mapping.channel}")
        console.print(f"  sender_id:  {mapping.sender_id}")
        console.print(f"  user_id:    {mapping.user_id}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command("list-mappings")
def list_mappings(
    channel: Annotated[
        str | None, typer.Option("--channel", "-c", help="Filter by channel")
    ] = None,
    user: Annotated[str | None, typer.Option("--user", "-u", help="Filter by user")] = None,
) -> None:
    """List external identity mappings.

    RFC-307 §CLI Commands.
    """
    _require_enabled()

    identity = _get_identity_service()
    mappings = identity.list_mappings(channel, user)

    if not mappings:
        console.print("[yellow]No mappings found[/yellow]")
        return

    title = "External Identity Mappings"
    if channel:
        title += f" (channel: {channel})"
    if user:
        title += f" (user: {user})"

    table = Table(title=title)
    table.add_column("channel")
    table.add_column("sender_id")
    table.add_column("user_id")
    table.add_column("created_at")

    for m in mappings:
        table.add_row(
            m.channel,
            m.sender_id,
            m.user_id,
            m.created_at.isoformat(),
        )

    console.print(table)


@app.command("unmap-external")
def unmap_external(
    channel: Annotated[str, typer.Option("--channel", "-c", help="Channel name")],
    sender_id: Annotated[str, typer.Option("--sender-id", "-s", help="Platform sender ID")],
) -> None:
    """Remove external identity mapping.

    RFC-307 §CLI Commands.
    """
    _require_enabled()

    identity = _get_identity_service()
    try:
        identity.unmap_external(channel, sender_id)
        console.print("[green]External mapping removed:[/green]")
        console.print(f"  channel:    {channel}")
        console.print(f"  sender_id:  {sender_id}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


# ============================================================================
# Status Command
# ============================================================================


@app.command("status")
def status() -> None:
    """Show identity service status.

    RFC-307 §CLI Commands.
    """
    from soothe_daemon.config import SootheDaemonConfig, default_daemon_config_path

    config_path = default_daemon_config_path()
    config = (
        SootheDaemonConfig.from_yaml_file(config_path)
        if config_path.exists()
        else SootheDaemonConfig()
    )

    console.print("[bold]Identity Service Status[/bold]")
    console.print()

    # Config status
    enabled = config.identity.enabled
    enabled_str = "[green]enabled[/green]" if enabled else "[yellow]disabled[/yellow]"
    console.print(f"  enabled:           {enabled_str}")

    if not enabled:
        console.print()
        console.print("[yellow]Identity service is disabled. Enable in daemon config:[/yellow]")
        console.print("  identity.enabled = true")
        return

    # Runtime status
    try:
        identity = _get_identity_service()
        status_obj = identity.get_status()

        console.print(f"  storage_backend:   {status_obj.storage_backend}")
        console.print(f"  jwt_key_source:    {status_obj.jwt_key_source}")
        console.print(f"  users_count:       {status_obj.users_count}")
        console.print(f"  active_aksk:       {status_obj.active_aksk_count}")
        console.print(f"  active_tokens:     {status_obj.active_tokens_count}")

    except Exception as e:
        console.print(f"  [red]Error getting status: {e}[/red]")


if __name__ == "__main__":
    app()
