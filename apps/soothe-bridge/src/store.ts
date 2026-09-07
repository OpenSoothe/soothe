/**
 * Bridge ID-mapping store.
 *
 * Persists bots (and their Soothe loop binding) so a bridge restart doesn't
 * orphan loops or lose conversation history. Per the integration doc (§7.4)
 * this is a lightweight SQLite store, local to the bridge process.
 *
 * Backend: node:sqlite (built into Node ≥22.5, stable in ≥24) — no native
 * module rebuilds under Electron.
 */

import { mkdirSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

export interface BotRecord {
  id: string;
  name: string;
  avatar?: string;
  color?: string;
  loopId?: string;
  createdAt: string;
}

/** Resolve the bridge data directory: $SOOTHE_BRIDGE_DATA_DIR, else $SOOTHE_HOME/bridge, else ~/.soothe/bridge. */
export function bridgeDataDir(): string {
  const override = process.env.SOOTHE_BRIDGE_DATA_DIR?.trim();
  if (override) return override;
  const home = process.env.SOOTHE_HOME?.trim() || path.join(process.env.HOME ?? "", ".soothe");
  return path.join(home, "bridge");
}

export class BridgeStore {
  private db: DatabaseSync;

  constructor(dataDir: string) {
    mkdirSync(dataDir, { recursive: true });
    this.db = new DatabaseSync(path.join(dataDir, "bridge.db"));
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS bots (
        bot_id     TEXT PRIMARY KEY,
        loop_id    TEXT,
        name       TEXT NOT NULL,
        avatar     TEXT,
        color      TEXT,
        created_at TEXT NOT NULL
      )
    `);
  }

  loadBots(): BotRecord[] {
    const rows = this.db
      .prepare(
        "SELECT bot_id, loop_id, name, avatar, color, created_at FROM bots ORDER BY created_at",
      )
      .all() as Record<string, unknown>[];
    return rows.map(r => ({
      id: String(r.bot_id),
      name: String(r.name),
      avatar: r.avatar === null || r.avatar === undefined ? undefined : String(r.avatar),
      color: r.color === null || r.color === undefined ? undefined : String(r.color),
      loopId: r.loop_id === null || r.loop_id === undefined ? undefined : String(r.loop_id),
      createdAt: String(r.created_at),
    }));
  }

  upsertBot(bot: BotRecord): void {
    this.db
      .prepare(
        `
      INSERT INTO bots (bot_id, loop_id, name, avatar, color, created_at)
      VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(bot_id) DO UPDATE SET
        loop_id = excluded.loop_id,
        name = excluded.name,
        avatar = excluded.avatar,
        color = excluded.color
    `,
      )
      .run(
        bot.id,
        bot.loopId ?? null,
        bot.name,
        bot.avatar ?? null,
        bot.color ?? null,
        bot.createdAt,
      );
  }

  setBotLoop(botId: string, loopId: string): void {
    this.db.prepare("UPDATE bots SET loop_id = ? WHERE bot_id = ?").run(loopId, botId);
  }

  deleteBot(botId: string): void {
    this.db.prepare("DELETE FROM bots WHERE bot_id = ?").run(botId);
  }

  close(): void {
    this.db.close();
  }
}
