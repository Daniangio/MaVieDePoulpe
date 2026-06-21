import { useEffect, useMemo, useRef, useState } from "react";
import {
  Link2,
  MessageCircle,
  Plus,
  Send,
  Shield,
  Search,
  UserMinus,
  UserPlus,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const DEFAULT_CHAT_ID = "global:global";

const formatTime = (value) => {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

const parseMemberIds = (value) =>
  String(value || "")
    .split(/[\s,;]+/)
    .map((entry) => entry.trim())
    .filter(Boolean);

const GlobalChatOverlay = () => {
  const [draft, setDraft] = useState("");
  const [channelSearch, setChannelSearch] = useState("");
  const [friendSearch, setFriendSearch] = useState("");
  const [showCreateGroup, setShowCreateGroup] = useState(false);
  const [newChannelName, setNewChannelName] = useState("");
  const [selectedInviteFriends, setSelectedInviteFriends] = useState([]);
  const [kickDraft, setKickDraft] = useState("");
  const [reintegrateDraft, setReintegrateDraft] = useState("");
  const [friends, setFriends] = useState([]);
  const bottomRef = useRef(null);
  const {
    chatOpen,
    chatChannels,
    activeChatId,
    chatMessages,
    chatUnreadCount,
    chatUnreadByChannel,
    chatComposerDraft,
    isConnected,
    sendMessage,
    token,
    user,
    setChatOpen,
    setActiveChatId,
    requestChatChannels,
    requestChatHistory,
    setChatComposerDraft,
  } = useStore((state) => ({
    chatOpen: state.chatOpen,
    chatChannels: state.chatChannels,
    activeChatId: state.activeChatId,
    chatMessages: state.chatMessages,
    chatUnreadCount: state.chatUnreadCount,
    chatUnreadByChannel: state.chatUnreadByChannel,
    chatComposerDraft: state.chatComposerDraft,
    isConnected: state.isConnected,
    sendMessage: state.sendMessage,
    token: state.token,
    user: state.user,
    setChatOpen: state.setChatOpen,
    setActiveChatId: state.setActiveChatId,
    requestChatChannels: state.requestChatChannels,
    requestChatHistory: state.requestChatHistory,
    setChatComposerDraft: state.setChatComposerDraft,
  }));

  const canSend = Boolean(isConnected && sendMessage);
  const channels = useMemo(
    () => (Array.isArray(chatChannels) && chatChannels.length ? chatChannels : [{ id: DEFAULT_CHAT_ID, name: "Global", kind: "global" }]),
    [chatChannels]
  );
  const normalizedSearch = channelSearch.trim().toLowerCase();
  const visibleChannels = useMemo(
    () =>
      normalizedSearch
        ? channels.filter((channel) =>
            `${channel.name || ""} ${channel.kind || ""}`.toLowerCase().includes(normalizedSearch)
          )
        : channels,
    [channels, normalizedSearch]
  );
  const friendSuggestions = useMemo(() => {
    const query = (showCreateGroup ? friendSearch : channelSearch).trim().toLowerCase();
    const list = Array.isArray(friends) ? friends : [];
    if (!query) return list.slice(0, 5);
    return list
      .filter((entry) => `${entry?.user?.username || ""} ${entry?.user?.id || ""}`.toLowerCase().includes(query))
      .slice(0, 8);
  }, [channelSearch, friendSearch, friends, showCreateGroup]);
  const activeChannel = channels.find((channel) => channel.id === activeChatId) || channels[0];
  const visibleMessages = useMemo(() => (Array.isArray(chatMessages) ? chatMessages : []), [chatMessages]);
  const isGroup = activeChannel?.kind === "group";
  const isGlobal = activeChannel?.kind === "global";
  const isCreator = isGroup && String(activeChannel?.created_by || "") === String(user?.id || "");
  const canManageGroupMembers = isGroup && (isCreator || Boolean(user?.is_admin));
  const canManageGlobalMembers = isGlobal && Boolean(user?.is_admin);
  const canRemoveChannel =
    (activeChannel?.kind === "global" && user?.is_admin && activeChannel?.id !== DEFAULT_CHAT_ID) ||
    (isGroup && canManageGroupMembers);

  useEffect(() => {
    if (!chatOpen || !token) return;
    let cancelled = false;
    const loadFriends = async () => {
      try {
        const response = await fetch(buildApiUrl("/api/friends"), {
          headers: { Authorization: `Bearer ${token}` },
        });
        const payload = await response.json().catch(() => ({}));
        if (!cancelled && response.ok) {
          setFriends(Array.isArray(payload?.friends) ? payload.friends : []);
        }
      } catch (error) {
        if (!cancelled) setFriends([]);
      }
    };
    void loadFriends();
    return () => {
      cancelled = true;
    };
  }, [chatOpen, token]);

  useEffect(() => {
    if (!chatOpen || !canSend) return;
    requestChatChannels();
  }, [canSend, chatOpen, requestChatChannels]);

  useEffect(() => {
    if (!chatOpen || !canSend || !activeChannel?.id) return;
    requestChatHistory(activeChannel.id);
  }, [activeChannel?.id, canSend, chatOpen, requestChatHistory]);

  useEffect(() => {
    if (!chatOpen) return;
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [chatOpen, activeChatId, visibleMessages.length]);

  useEffect(() => {
    if (!chatComposerDraft) return;
    setDraft(chatComposerDraft);
    setChatComposerDraft("");
  }, [chatComposerDraft, setChatComposerDraft]);

  const sendAction = (action, payload) => {
    if (!canSend) return;
    sendMessage({ action, payload });
  };

  const submit = (event) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || !activeChannel?.id) return;
    sendAction("send_chat_message", { chat_id: activeChannel.id, text });
    setDraft("");
  };

  const createChannel = () => {
    const name = newChannelName.trim();
    if (!name) return;
    sendAction("create_chat_channel", {
      name,
      kind: "group",
      member_ids: selectedInviteFriends.map((entry) => entry.user.id),
    });
    setNewChannelName("");
    setSelectedInviteFriends([]);
    setShowCreateGroup(false);
  };

  const toggleInviteFriend = (entry) => {
    const friendId = entry?.user?.id;
    if (!friendId) return;
    setSelectedInviteFriends((prev) =>
      prev.some((selected) => selected.user.id === friendId)
        ? prev.filter((selected) => selected.user.id !== friendId)
        : [...prev, entry]
    );
  };

  const startDirectChat = (entry) => {
    const friendId = entry?.user?.id;
    if (!friendId) return;
    sendAction("start_direct_chat", { friend_user_id: friendId });
  };

  if (!user) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[1200] flex items-end gap-3 font-interface">
      {chatOpen ? (
        <div className="mr-16 flex h-[36rem] w-[min(58rem,calc(100vw-6rem))] overflow-hidden rounded-3xl border border-amber-200/30 bg-slate-950/95 shadow-[0_24px_80px_rgba(2,6,23,0.55)] backdrop-blur-xl">
          <aside className="flex w-64 shrink-0 flex-col border-r border-white/10 bg-white/[0.03]">
            <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.28em] text-amber-200">
                  Chat
                </p>
                <p className="text-[11px] text-slate-400">Channels and groups</p>
              </div>
              <button
                type="button"
                onClick={() => setChatOpen(false)}
                className="rounded-full border border-white/10 p-2 text-slate-300 transition hover:border-amber-200/60 hover:text-white"
                aria-label="Close chat"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="border-b border-white/10 p-3">
              <div className="flex items-center gap-2 rounded-2xl border border-white/10 bg-slate-900 px-3 py-2">
                <Search className="h-3.5 w-3.5 text-slate-500" />
                <input
                  value={channelSearch}
                  onChange={(event) => setChannelSearch(event.target.value)}
                  placeholder="Search chats or friends"
                  className="min-w-0 flex-1 bg-transparent text-xs text-white outline-none placeholder:text-slate-500"
                />
                <button
                  type="button"
                  onClick={() => setShowCreateGroup((value) => !value)}
                  className="rounded-full border border-amber-200/30 p-1.5 text-amber-100 transition hover:border-amber-200"
                  aria-label="Create group"
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              {showCreateGroup ? (
                <div className="mb-3 rounded-2xl border border-amber-200/20 bg-amber-300/10 p-3">
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.22em] text-amber-100">
                    New Group
                  </p>
                  <input
                    value={newChannelName}
                    onChange={(event) => setNewChannelName(event.target.value)}
                    placeholder="Group name"
                    className="mb-2 w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-2 text-xs text-white outline-none placeholder:text-slate-500"
                  />
                  <input
                    value={friendSearch}
                    onChange={(event) => setFriendSearch(event.target.value)}
                    placeholder="Search friends to invite"
                    className="mb-2 w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-2 text-xs text-white outline-none placeholder:text-slate-500"
                  />
                  <div className="mb-2 max-h-28 space-y-1 overflow-y-auto">
                    {friendSuggestions.map((entry) => {
                      const selected = selectedInviteFriends.some(
                        (friend) => friend.user.id === entry.user.id
                      );
                      return (
                        <button
                          key={`invite-${entry.user.id}`}
                          type="button"
                          onClick={() => toggleInviteFriend(entry)}
                          className={`w-full rounded-xl border px-2 py-1.5 text-left text-xs ${
                            selected
                              ? "border-emerald-300/50 bg-emerald-300/15 text-emerald-100"
                              : "border-white/10 bg-slate-900/70 text-slate-300"
                          }`}
                        >
                          {entry.user.username}
                        </button>
                      );
                    })}
                  </div>
                  <button
                    type="button"
                    onClick={createChannel}
                    disabled={!newChannelName.trim() || !canSend}
                    className="w-full rounded-xl border border-amber-200/40 bg-amber-300/15 px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-amber-100 disabled:opacity-40"
                  >
                    Create Group
                  </button>
                </div>
              ) : null}

              <div className="space-y-2">
                {visibleChannels.map((channel) => {
                  const unread = Number(chatUnreadByChannel?.[channel.id] || 0);
                  const selected = channel.id === activeChannel?.id;
                  const displayName = String(channel.name || "")
                    .split(",")
                    .map((part) =>
                      part.trim() === String(user?.username || "").trim() ? "You" : part.trim()
                    )
                    .join(", ");
                  return (
                    <button
                      key={channel.id}
                      type="button"
                      onClick={() => setActiveChatId(channel.id)}
                      className={`flex w-full items-center justify-between gap-2 rounded-2xl border px-3 py-2 text-left transition ${
                        selected
                          ? "border-amber-200/60 bg-amber-300/15 text-white"
                          : "border-white/10 bg-slate-900/70 text-slate-300 hover:border-white/25"
                      }`}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm">{displayName || channel.name}</span>
                        <span className="flex items-center gap-1 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                          {channel.kind === "global" ? "Global" : channel.kind === "direct" ? "Friend" : "Group"}
                          {channel.muted ? <VolumeX className="h-3 w-3" /> : null}
                        </span>
                      </span>
                      <span className="flex shrink-0 items-center gap-1">
                        {unread > 0 && !channel.muted ? (
                          <span className="rounded-full bg-red-500 px-2 py-0.5 text-[10px] font-bold text-white">
                            {Math.min(unread, 99)}
                          </span>
                        ) : null}
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(event) => {
                            event.stopPropagation();
                            sendAction("set_chat_muted", { chat_id: channel.id, muted: !channel.muted });
                          }}
                          onKeyDown={(event) => {
                            if (event.key !== "Enter" && event.key !== " ") return;
                            event.preventDefault();
                            event.stopPropagation();
                            sendAction("set_chat_muted", { chat_id: channel.id, muted: !channel.muted });
                          }}
                          className="rounded-full border border-white/10 p-1 text-slate-400 transition hover:border-amber-200/50 hover:text-amber-100"
                          title={channel.muted ? "Unmute" : "Mute"}
                        >
                          {channel.muted ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>

              {channelSearch.trim() && !showCreateGroup ? (
                <div className="mt-4 border-t border-white/10 pt-3">
                  <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.22em] text-slate-400">
                    Friends
                  </p>
                  <div className="space-y-2">
                    {friendSuggestions.map((entry) => (
                      <button
                        key={`direct-${entry.user.id}`}
                        type="button"
                        onClick={() => startDirectChat(entry)}
                        className="w-full rounded-2xl border border-sky-200/20 bg-sky-300/10 px-3 py-2 text-left text-xs text-sky-100"
                      >
                        Start chat with {entry.user.username}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </aside>

          <section className="flex min-w-0 flex-1 flex-col">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
              <div className="min-w-0">
                <p className="truncate text-lg font-semibold text-white">{activeChannel?.name || "Global"}</p>
                <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">
                  {activeChannel?.kind || "global"} · expires after {Math.round(Number(activeChannel?.retention_seconds || 86400) / 3600)}h
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {isGroup && !isCreator ? (
                  <button
                    type="button"
                    onClick={() => sendAction("leave_chat_channel", { chat_id: activeChannel.id })}
                    className="rounded-xl border border-red-300/30 bg-red-500/10 px-3 py-2 text-xs text-red-100"
                  >
                    Leave
                  </button>
                ) : null}
                {canRemoveChannel ? (
                  <button
                    type="button"
                    onClick={() => sendAction("remove_chat_channel", { chat_id: activeChannel.id })}
                    className="rounded-xl border border-red-300/30 bg-red-500/10 px-3 py-2 text-xs text-red-100"
                  >
                    {isGroup ? "Disband" : "Remove"}
                  </button>
                ) : null}
              </div>
            </div>

            <div className="border-b border-white/10 bg-slate-950/60 px-4 py-2">
              <div className="flex flex-wrap items-center gap-2">
                {canManageGroupMembers ? (
                  <>
                    <select
                      value=""
                      onChange={(event) => {
                        const friendId = event.target.value;
                        if (!friendId) return;
                        sendAction("add_chat_members", { chat_id: activeChannel.id, member_ids: [friendId] });
                      }}
                      className="min-w-44 rounded-xl border border-white/10 bg-slate-900 px-3 py-2 text-xs text-white outline-none"
                    >
                      <option value="">Add friend...</option>
                      {friends.map((entry) => (
                        <option key={`add-${entry.user.id}`} value={entry.user.id}>
                          {entry.user.username}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => setShowCreateGroup(true)}
                      className="rounded-xl border border-emerald-300/30 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-100"
                    >
                      <UserPlus className="mr-1 inline h-3.5 w-3.5" />
                      Invite
                    </button>
                    <input
                      value={kickDraft}
                      onChange={(event) => setKickDraft(event.target.value)}
                      placeholder="Kick user ID"
                      className="min-w-36 rounded-xl border border-white/10 bg-slate-900 px-3 py-2 text-xs text-white outline-none placeholder:text-slate-500"
                    />
                    <button
                      type="button"
                      onClick={() => sendAction("kick_chat_member", { chat_id: activeChannel.id, member_id: kickDraft.trim() })}
                      className="rounded-xl border border-red-300/30 bg-red-500/10 px-3 py-2 text-xs text-red-100"
                    >
                      <UserMinus className="mr-1 inline h-3.5 w-3.5" />
                      Kick
                    </button>
                  </>
                ) : null}
                {canManageGlobalMembers ? (
                  <>
                    <input
                      value={kickDraft}
                      onChange={(event) => setKickDraft(event.target.value)}
                      placeholder="Kick user ID from global"
                      className="min-w-44 rounded-xl border border-white/10 bg-slate-900 px-3 py-2 text-xs text-white outline-none placeholder:text-slate-500"
                    />
                    <button
                      type="button"
                      onClick={() => sendAction("kick_chat_member", { chat_id: activeChannel.id, member_id: kickDraft.trim() })}
                      className="rounded-xl border border-red-300/30 bg-red-500/10 px-3 py-2 text-xs text-red-100"
                    >
                      <UserMinus className="mr-1 inline h-3.5 w-3.5" />
                      Kick
                    </button>
                    <input
                      value={reintegrateDraft}
                      onChange={(event) => setReintegrateDraft(event.target.value)}
                      placeholder="Reintegrate user ID"
                      className="min-w-44 rounded-xl border border-white/10 bg-slate-900 px-3 py-2 text-xs text-white outline-none placeholder:text-slate-500"
                    />
                    <button
                      type="button"
                      onClick={() => sendAction("add_chat_members", { chat_id: activeChannel.id, member_ids: parseMemberIds(reintegrateDraft) })}
                      className="rounded-xl border border-emerald-300/30 bg-emerald-400/10 px-3 py-2 text-xs text-emerald-100"
                    >
                      Reintegrate
                    </button>
                  </>
                ) : null}
                {user?.is_admin ? (
                  <span className="ml-auto rounded-xl border border-purple-200/20 bg-purple-300/10 px-3 py-2 text-[10px] uppercase tracking-[0.16em] text-purple-100">
                    <Shield className="mr-1 inline h-3.5 w-3.5" />
                    Admin options enabled
                  </span>
                ) : null}
              </div>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
              {visibleMessages.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] px-4 py-8 text-center text-sm text-slate-400">
                  No messages yet.
                </div>
              ) : (
                visibleMessages.map((message, index) => {
                  const mine = String(message.sender_id || "") === String(user.id || "");
                  const share = message.share && typeof message.share === "object" ? message.share : null;
                  return (
                    <div
                      key={message.entry_id || `${message.sent_at || "msg"}_${index}`}
                      className={`rounded-2xl border px-3 py-2 ${
                        mine
                          ? "ml-10 border-amber-200/25 bg-amber-300/10"
                          : "mr-10 border-white/10 bg-white/[0.04]"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-[0.16em] text-slate-500">
                        <span className="truncate text-slate-300">
                          {mine ? "You" : message.sender_name || message.sender_id || "Player"}
                        </span>
                        <span>{formatTime(message.sent_at)}</span>
                      </div>
                      {message.text ? (
                        <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-100">{message.text}</p>
                      ) : null}
                      {share?.url ? (
                        <a
                          href={share.url}
                          className="mt-2 flex items-center gap-2 rounded-xl border border-sky-200/20 bg-sky-300/10 px-3 py-2 text-xs text-sky-100 transition hover:border-sky-200/50"
                        >
                          <Link2 className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">{share.title || share.url}</span>
                        </a>
                      ) : null}
                    </div>
                  );
                })
              )}
              <div ref={bottomRef} />
            </div>

            <form onSubmit={submit} className="border-t border-white/10 p-3">
              <div className="flex items-center gap-2">
                <input
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  maxLength={1000}
                  placeholder={activeChannel?.muted ? "Channel muted; you can still send." : canSend ? "Write a message..." : "Connecting..."}
                  className="min-w-0 flex-1 rounded-2xl border border-white/10 bg-slate-900/90 px-3 py-3 text-sm text-white outline-none transition placeholder:text-slate-500 focus:border-amber-200/50"
                />
                <button
                  type="submit"
                  disabled={!draft.trim() || !canSend}
                  className="rounded-2xl border border-amber-200/40 bg-amber-300/15 p-3 text-amber-100 transition hover:border-amber-200/80 disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label="Send message"
                >
                  <Send className="h-4 w-4" />
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
      <button
        type="button"
        onClick={() => setChatOpen(!chatOpen)}
        className="absolute bottom-0 right-0 rounded-full border border-amber-200/40 bg-slate-950/90 p-4 text-amber-100 shadow-[0_14px_40px_rgba(2,6,23,0.45)] transition hover:border-amber-200 hover:bg-slate-900"
        aria-label={chatOpen ? "Close chat" : "Open chat"}
      >
        <MessageCircle className="h-5 w-5" />
        {chatUnreadCount > 0 ? (
          <span className="absolute -right-1 -top-1 min-w-5 rounded-full bg-red-500 px-1.5 py-0.5 text-center text-[10px] font-bold text-white">
            {Math.min(chatUnreadCount, 99)}
          </span>
        ) : null}
      </button>
    </div>
  );
};

export default GlobalChatOverlay;
