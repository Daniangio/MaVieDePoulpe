import { jwtDecode } from "jwt-decode";
import { create } from "zustand";
import { fetchWithRetry } from "./utils/connection.js";

const ACCESS_TOKEN_KEY = "authToken";
const DEFAULT_CHAT_ID = "global:global";

const decodeTokenPayload = (token) => {
  if (!token) return null;
  try {
    const decoded = jwtDecode(token);
    if (!decoded?.sub) return null;
    const email = decoded.email || null;
    return {
      token,
      user: {
        id: decoded.sub,
        username: decoded.name || email || decoded.username || decoded.sub,
        email,
        is_admin: Boolean(decoded.admin || decoded.is_admin),
      },
      exp: decoded.exp || null,
    };
  } catch (_error) {
    return null;
  }
};

const isTokenExpired = (exp) => Boolean(exp && exp * 1000 <= Date.now());

const storedAccessToken = sessionStorage.getItem(ACCESS_TOKEN_KEY);
const decodedStoredAccess = decodeTokenPayload(storedAccessToken);
const initialAccess =
  decodedStoredAccess && !isTokenExpired(decodedStoredAccess.exp) ? decodedStoredAccess : null;

if (!initialAccess && storedAccessToken) {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
}

export const useStore = create((set, get) => ({
  token: initialAccess?.token || null,
  user: initialAccess?.user || null,
  authMe: null,
  authBootstrapped: false,
  sessionState: null,
  isConnected: false,
  connectionIssue: "",
  lastErrorMessage: "",
  lastErrorId: 0,

  chatOpen: false,
  chatChannels: [],
  activeChatId: DEFAULT_CHAT_ID,
  chatMessages: [],
  chatMessagesByChannel: {},
  chatUnreadCount: 0,
  chatUnreadByChannel: {},
  chatComposerDraft: "",
  sendMessage: null,

  setSendMessage: (fn) => set({ sendMessage: fn }),
  setAuthBootstrapped: (value = true) => set({ authBootstrapped: value }),

  setAuthSession: ({ accessToken }) => {
    const decoded = decodeTokenPayload(accessToken);
    if (!decoded) {
      get().clearAuth();
      return false;
    }
    sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    set({
      token: accessToken,
      user: decoded.user,
      authBootstrapped: true,
    });
    return true;
  },

  setAuthUser: (userPayload) =>
    set((state) => ({
      user: userPayload
        ? {
            ...state.user,
            id: userPayload.uid || userPayload.id || state.user?.id,
            username: userPayload.username || userPayload.email || state.user?.username || "",
            email: userPayload.email || state.user?.email || null,
            is_admin: Boolean(userPayload.is_admin),
          }
        : state.user,
    })),

  fetchAuthMe: async () => {
    const token = get().token;
    if (!token) return null;
    try {
      const response = await fetchWithRetry(
        "/api/auth/me",
        {
          headers: { Authorization: `Bearer ${token}` },
        },
        {
          attempts: 8,
          initialDelayMs: 300,
          maxDelayMs: 5000,
          onRetry: () => set({ connectionIssue: "Backend unavailable. Retrying..." }),
        }
      );
      if (response.status === 401) {
        get().clearAuth();
        return null;
      }
      if (!response.ok) throw new Error("Failed to fetch auth profile");
      const payload = await response.json();
      set({ authMe: payload, connectionIssue: "" });
      get().setAuthUser(payload);
      return payload;
    } catch (error) {
      set({ connectionIssue: "Backend unavailable. Retrying shortly..." });
      console.warn("Backend unavailable while fetching auth profile.", error);
      return null;
    }
  },

  fetchSessionState: async () => {
    const token = get().token;
    if (!token) {
      set({ sessionState: null });
      return null;
    }
    try {
      const response = await fetchWithRetry(
        "/api/session/state",
        {
          headers: { Authorization: `Bearer ${token}` },
        },
        {
          attempts: 8,
          initialDelayMs: 300,
          maxDelayMs: 5000,
          onRetry: () => set({ connectionIssue: "Backend unavailable. Retrying..." }),
        }
      );
      if (response.status === 401) {
        get().clearAuth();
        return null;
      }
      if (!response.ok) throw new Error(`Failed to fetch session state (${response.status})`);
      const payload = await response.json();
      set({ sessionState: payload, connectionIssue: "" });
      return payload;
    } catch (error) {
      set({ connectionIssue: "Backend unavailable. Retrying shortly..." });
      console.warn("Backend unavailable while fetching session state.", error);
      return null;
    }
  },

  clearAuth: () => {
    sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    set({
      token: null,
      user: null,
      authMe: null,
      authBootstrapped: true,
      sessionState: null,
      isConnected: false,
      connectionIssue: "",
      lastErrorMessage: "",
      lastErrorId: 0,
      chatOpen: false,
      chatChannels: [],
      activeChatId: DEFAULT_CHAT_ID,
      chatMessages: [],
      chatMessagesByChannel: {},
      chatUnreadCount: 0,
      chatUnreadByChannel: {},
      chatComposerDraft: "",
      sendMessage: null,
    });
  },

  setConnectionStatus: (status) =>
    set((state) => ({
      isConnected: Boolean(status),
      connectionIssue: status ? "" : state.connectionIssue,
    })),
  setConnectionIssue: (message) => set({ connectionIssue: message || "" }),

  handleAuthSuccess: (payload) => {
    const user = {
      id: payload.id,
      username: payload.username || payload.email || payload.id,
      email: payload.email || null,
      is_admin: Boolean(payload.is_admin),
    };
    set({ user });
  },

  handleError: (payload) => {
    const message = String(payload?.message || "Unknown server error.");
    console.error(`Server Error: ${message}`, payload);
    set((state) => ({
      lastErrorMessage: message,
      lastErrorId: (state.lastErrorId || 0) + 1,
    }));
  },

  setChatOpen: (open) =>
    set({
      chatOpen: Boolean(open),
      chatUnreadCount: open ? 0 : get().chatUnreadCount,
      chatUnreadByChannel: open
        ? {
            ...get().chatUnreadByChannel,
            [get().activeChatId || DEFAULT_CHAT_ID]: 0,
          }
        : get().chatUnreadByChannel,
    }),

  setChatComposerDraft: (draft) => set({ chatComposerDraft: String(draft || "") }),

  setActiveChatId: (chatId) =>
    set((state) => {
      const activeChatId = String(chatId || DEFAULT_CHAT_ID).trim() || DEFAULT_CHAT_ID;
      const unreadByChannel = {
        ...(state.chatUnreadByChannel || {}),
        [activeChatId]: 0,
      };
      return {
        activeChatId,
        chatMessages: state.chatMessagesByChannel?.[activeChatId] || [],
        chatUnreadByChannel: unreadByChannel,
        chatUnreadCount: Object.entries(unreadByChannel).reduce(
          (total, [channelId, count]) =>
            total + (channelId === activeChatId ? 0 : Number(count || 0)),
          0
        ),
      };
    }),

  handleChatChannels: (payload) => {
    const channels = Array.isArray(payload?.channels) ? payload.channels : [];
    set((state) => {
      const activeExists = channels.some((channel) => channel?.id === state.activeChatId);
      const activeChatId = activeExists ? state.activeChatId : channels[0]?.id || DEFAULT_CHAT_ID;
      return {
        chatChannels: channels,
        activeChatId,
        chatMessages: state.chatMessagesByChannel?.[activeChatId] || [],
      };
    });
  },

  handleChatDirectStarted: (payload) => {
    const chatId = String(payload?.chat_id || "").trim();
    if (chatId) {
      get().setActiveChatId(chatId);
      get().requestChatHistory(chatId);
    }
  },

  handleChatHistory: (payload) => {
    const messages = Array.isArray(payload?.messages) ? payload.messages : [];
    const chatId = String(payload?.chat_id || DEFAULT_CHAT_ID).trim() || DEFAULT_CHAT_ID;
    set((state) => {
      const unreadByChannel = {
        ...(state.chatUnreadByChannel || {}),
        [chatId]: 0,
      };
      return {
        chatMessagesByChannel: {
          ...(state.chatMessagesByChannel || {}),
          [chatId]: messages,
        },
        chatMessages: state.activeChatId === chatId ? messages : state.chatMessages,
        chatUnreadByChannel: unreadByChannel,
        chatUnreadCount: Object.entries(unreadByChannel).reduce(
          (total, [channelId, count]) => total + (channelId === chatId ? 0 : Number(count || 0)),
          0
        ),
      };
    });
  },

  isChatChannelMuted: (chatId) => {
    const channel = (get().chatChannels || []).find((entry) => entry?.id === chatId);
    return Boolean(channel?.muted);
  },

  requestChatChannels: () => {
    const sendMessage = get().sendMessage;
    if (sendMessage) sendMessage({ action: "request_chat_channels", payload: {} });
  },

  requestChatHistory: (chatId) => {
    const sendMessage = get().sendMessage;
    if (!sendMessage) return;
    sendMessage({
      action: "request_chat_history",
      payload: { chat_id: chatId || get().activeChatId || DEFAULT_CHAT_ID, limit: 80 },
    });
  },

  handleChatMessage: (payload) => {
    if (!payload || typeof payload !== "object") return;
    set((state) => {
      const messageId = String(payload.id || payload.stream_id || "").trim();
      const entryId = String(payload.entry_id || "").trim();
      const currentMessages = state.chatMessagesByChannel?.[payload.chat_id] || [];
      const exists =
        (messageId || entryId) &&
        currentMessages.some(
          (message) =>
            (messageId && String(message?.id || message?.stream_id || "").trim() === messageId) ||
            (entryId && String(message?.entry_id || "").trim() === entryId)
        );
      if (exists) return {};
      const chatId = String(payload.chat_id || DEFAULT_CHAT_ID).trim() || DEFAULT_CHAT_ID;
      const channelMessages = state.chatMessagesByChannel?.[chatId] || [];
      const nextChannelMessages = [...channelMessages, payload].slice(-120);
      const channel = (state.chatChannels || []).find((entry) => entry?.id === chatId);
      const shouldCountUnread = !state.chatOpen || state.activeChatId !== chatId;
      const nextUnreadByChannel = {
        ...(state.chatUnreadByChannel || {}),
        [chatId]:
          shouldCountUnread && !channel?.muted
            ? Number(state.chatUnreadByChannel?.[chatId] || 0) + 1
            : Number(state.chatUnreadByChannel?.[chatId] || 0),
      };
      return {
        chatMessagesByChannel: {
          ...(state.chatMessagesByChannel || {}),
          [chatId]: nextChannelMessages,
        },
        chatMessages: state.activeChatId === chatId ? nextChannelMessages : state.chatMessages,
        chatUnreadByChannel: nextUnreadByChannel,
        chatUnreadCount: Object.values(nextUnreadByChannel).reduce(
          (total, count) => total + Number(count || 0),
          0
        ),
      };
    });
  },
}));
