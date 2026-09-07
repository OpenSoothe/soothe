import { useCallback, useEffect, useRef, useState } from "react";
import { rpc, subscribeThreadEvents } from "./rpc";
import "./styles.css";

interface Bot {
  id: string;
  name: string;
  avatar?: string;
  color?: string;
  preview?: string;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  seq: number;
}

interface BootstrapResult {
  me: { id: string; name: string };
  spaces: { bots: Bot[] }[];
}

/** Deterministic avatar color from a name. */
function avatarColor(name: string): string {
  const colors = [
    "#12b7f5",
    "#e74c3c",
    "#2ecc71",
    "#f39c12",
    "#9b59b6",
    "#1abc9c",
    "#e67e22",
    "#3498db",
    "#e84393",
    "#00b894",
  ];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return colors[Math.abs(hash) % colors.length];
}

/** First 1–2 characters of a name for the avatar placeholder. */
function avatarLabel(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  return trimmed.slice(0, 2).toUpperCase();
}

export function App() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bots, setBots] = useState<Bot[]>([]);
  const [activeBot, setActiveBot] = useState<Bot | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newBotName, setNewBotName] = useState("");
  const [showNewBot, setShowNewBot] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Bootstrap on mount
  useEffect(() => {
    void (async () => {
      try {
        const health = await rpc<{ ok: boolean; version: string }>("health");
        if (!health.ok) throw new Error("Bridge not healthy");
        const boot = await rpc<BootstrapResult>("bootstrap", {});
        setBots(boot.spaces?.[0]?.bots ?? []);
        setReady(true);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  // Load messages when bot changes
  useEffect(() => {
    if (!activeBot) return;
    void (async () => {
      try {
        const page = await rpc<{ messages: Message[] }>("threads.messages", {
          botId: activeBot.id,
        });
        setMessages(page.messages ?? []);
      } catch {
        // ignore
      }
    })();
  }, [activeBot]);

  // Subscribe to events; each activity triggers a debounced history refetch
  useEffect(() => {
    if (!activeBot) return;
    const controller = new AbortController();
    let cancelled = false;
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;

    const refetch = async () => {
      try {
        const page = await rpc<{ messages: Message[] }>("threads.messages", {
          botId: activeBot.id,
        });
        if (!cancelled) setMessages(page.messages ?? []);
      } catch {
        // ignore
      }
    };

    void (async () => {
      try {
        for await (const _event of subscribeThreadEvents(activeBot.id, -1, controller.signal)) {
          if (cancelled) break;
          // LangGraph streaming emits many frames per second; collapse them
          if (debounceTimer !== null) continue;
          debounceTimer = setTimeout(() => {
            debounceTimer = null;
            if (!cancelled) void refetch();
          }, 300);
        }
      } catch {
        // Aborted on bot switch — expected
      }
    })();

    return () => {
      cancelled = true;
      if (debounceTimer !== null) clearTimeout(debounceTimer);
      controller.abort();
    };
  }, [activeBot]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Focus input when bot selected
  useEffect(() => {
    inputRef.current?.focus();
  }, [activeBot]);

  const send = useCallback(async () => {
    if (!activeBot || !input.trim()) return;
    const text = input.trim();
    setSending(true);
    // Optimistic echo; the next activity-driven refetch replaces it with
    // server history (which includes the user message).
    setMessages(prev => [
      ...prev,
      { id: `local_${Date.now()}`, role: "user", text, seq: prev.length },
    ]);
    setInput("");
    try {
      await rpc("threads.send", { botId: activeBot.id, text });
    } catch (e) {
      setInput(text);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  }, [activeBot, input]);

  const createBot = useCallback(async () => {
    if (!newBotName.trim()) return;
    setCreating(true);
    try {
      const bot = await rpc<Bot>("bots.create", { name: newBotName.trim() });
      setBots(prev => [...prev, bot]);
      setActiveBot(bot);
      setNewBotName("");
      setShowNewBot(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }, [newBotName]);

  const commitRename = useCallback(async () => {
    if (!renamingId) return;
    const name = renameValue.trim();
    setRenamingId(null);
    if (!name) return;
    try {
      await rpc("bots.update", { botId: renamingId, name });
      setBots(prev => prev.map(b => (b.id === renamingId ? { ...b, name } : b)));
      setActiveBot(cur => (cur && cur.id === renamingId ? { ...cur, name } : cur));
    } catch {
      // Rename is cosmetic — ignore failures
    }
  }, [renamingId, renameValue]);

  const removeBot = useCallback(async (bot: Bot) => {
    if (!window.confirm(`删除队友「${bot.name}」及其对话记录？`)) return;
    try {
      await rpc("bots.remove", { botId: bot.id });
    } catch (e) {
      window.alert(e instanceof Error ? e.message : String(e));
      return;
    }
    setBots(prev => prev.filter(b => b.id !== bot.id));
    setActiveBot(cur => (cur?.id === bot.id ? null : cur));
  }, []);

  const filteredBots = bots.filter(b => b.name.toLowerCase().includes(searchQuery.toLowerCase()));

  if (error) {
    return (
      <div className="error-screen">
        <div className="error-card">
          <h2>连接错误</h2>
          <p>{error}</p>
          <p className="error-hint">
            请确认 Soothe Bridge 运行在 3100 端口，且 Soothe daemon 已启动。
          </p>
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="loading-screen">
        <div className="loading-spinner" />
        <p>正在连接 Soothe Bridge…</p>
      </div>
    );
  }

  return (
    <div className="app-layout">
      {/* ── Left: Contact List (QQ-style) ── */}
      <aside className="sidebar">
        {/* Profile header */}
        <div className="sidebar-header">
          <div className="sidebar-avatar" style={{ background: avatarColor("Sobo") }}>
            SO
          </div>
          <span className="sidebar-title">Sobo</span>
          <button
            className="sidebar-add-btn"
            onClick={() => setShowNewBot(v => !v)}
            title="添加新队友"
          >
            +
          </button>
        </div>

        {/* Search */}
        <div className="sidebar-search">
          <input
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="搜索…"
          />
        </div>

        {/* New bot inline form */}
        {showNewBot && (
          <div className="sidebar-new-bot">
            <input
              value={newBotName}
              onChange={e => setNewBotName(e.target.value)}
              onKeyDown={e => e.key === "Enter" && void createBot()}
              placeholder="队友名称…"
              autoFocus
            />
            <button onClick={() => void createBot()} disabled={creating || !newBotName.trim()}>
              添加
            </button>
          </div>
        )}

        {/* Contact list */}
        <div className="contact-list">
          {filteredBots.map(bot => {
            const isActive = activeBot?.id === bot.id;
            const color = bot.color ?? avatarColor(bot.name);
            if (renamingId === bot.id) {
              return (
                <div key={bot.id} className="contact-item renaming">
                  <input
                    className="contact-rename-input"
                    value={renameValue}
                    onChange={e => setRenameValue(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === "Enter") void commitRename();
                      else if (e.key === "Escape") setRenamingId(null);
                    }}
                    onBlur={() => void commitRename()}
                    autoFocus
                  />
                </div>
              );
            }
            return (
              <button
                key={bot.id}
                className={`contact-item ${isActive ? "active" : ""}`}
                onClick={() => setActiveBot(bot)}
                onDoubleClick={() => {
                  setRenamingId(bot.id);
                  setRenameValue(bot.name);
                }}
                title="双击重命名"
              >
                <div className="contact-avatar" style={{ background: color }}>
                  {avatarLabel(bot.name)}
                </div>
                <div className="contact-info">
                  <span className="contact-name">{bot.name}</span>
                  <span className="contact-preview">{bot.preview ?? "点击开始对话"}</span>
                </div>
              </button>
            );
          })}
          {filteredBots.length === 0 && (
            <div className="contact-empty">{bots.length === 0 ? "还没有队友" : "未找到匹配"}</div>
          )}
        </div>
      </aside>

      {/* ── Right: Chat Area ── */}
      <main className="chat-area">
        {activeBot ? (
          <>
            {/* Chat header */}
            <header className="chat-header">
              <span className="chat-header-name">{activeBot.name}</span>
              <span className="chat-header-status">在线</span>
              <button
                className="chat-header-delete"
                onClick={() => void removeBot(activeBot)}
                title="删除该队友"
              >
                删除
              </button>
            </header>

            {/* Message list */}
            <div className="message-list">
              {messages.map(msg => {
                const isUser = msg.role === "user";
                const color = avatarColor(isUser ? "Me" : activeBot.name);
                return (
                  <div key={msg.id} className={`message-row ${isUser ? "msg-right" : "msg-left"}`}>
                    <div className="message-avatar" style={{ background: color }}>
                      {avatarLabel(isUser ? "Me" : activeBot.name)}
                    </div>
                    <div className="message-bubble-wrap">
                      <div className={`message-bubble ${isUser ? "bubble-user" : "bubble-bot"}`}>
                        {msg.text}
                      </div>
                    </div>
                  </div>
                );
              })}
              {sending && (
                <div className="message-row msg-left">
                  <div
                    className="message-avatar"
                    style={{ background: avatarColor(activeBot.name) }}
                  >
                    {avatarLabel(activeBot.name)}
                  </div>
                  <div className="message-bubble-wrap">
                    <div className="message-bubble bubble-bot bubble-typing">
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input area */}
            <div className="chat-input-area">
              <input
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                placeholder={`发消息给 ${activeBot.name}…`}
                disabled={sending}
                className="chat-input"
              />
              <button
                className="chat-send-btn"
                onClick={() => void send()}
                disabled={sending || !input.trim()}
              >
                发送
              </button>
            </div>
          </>
        ) : (
          <div className="chat-empty">
            <div className="chat-empty-icon">💬</div>
            <p>选择一个队友开始对话</p>
          </div>
        )}
      </main>
    </div>
  );
}
