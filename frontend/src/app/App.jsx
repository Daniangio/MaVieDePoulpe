import { useCallback, useEffect, useRef } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import AuthenticatedLayout from "../components/AuthenticatedLayout.jsx";
import GlobalChatOverlay from "../components/GlobalChatOverlay.jsx";
import {
  ensureFirebasePersistence,
  signOutFirebase,
  subscribeToIdTokenChanges,
} from "../lib/firebase.js";
import AdminPage from "../pages/AdminPage.jsx";
import AdminContentPage from "../pages/AdminContentPage.jsx";
import AuthPage from "../pages/AuthPage.jsx";
import FriendsPage from "../pages/FriendsPage.jsx";
import GameHistoryPage from "../pages/GameHistoryPage.jsx";
import GameRoomPage from "../pages/GameRoomPage";
import LobbyPage from "../pages/LobbyPage.jsx";
import PlayPage from "../pages/PlayPage.jsx";
import PostGamePage from "../pages/PostGamePage.jsx";
import ProfilePage from "../pages/ProfilePage.jsx";
import SoloPlayPage from "../pages/SoloPlayPage.jsx";
import { useStore } from "../store.js";
import { buildApiUrl, buildWsUrl } from "../utils/connection.js";

const StateGuard = ({ children }) => {
  const { token, authBootstrapped } = useStore();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!authBootstrapped) return;
    const isOnAuth = location.pathname === "/auth";
    if (!token && !isOnAuth) {
      navigate("/auth", { replace: true });
      return;
    }
    if (token && isOnAuth) {
      navigate("/lobby", { replace: true });
    }
  }, [authBootstrapped, token, location.pathname, navigate]);

  if (!authBootstrapped) {
    return <div className="flex min-h-screen items-center justify-center">Restoring session...</div>;
  }

  return children;
};

function AppContent() {
  const location = useLocation();
  const {
    token,
    authBootstrapped,
    connectionIssue,
    clearAuth,
    fetchAuthMe,
    fetchSessionState,
    handleAuthSuccess,
    handleChatChannels,
    handleChatDirectStarted,
    handleChatHistory,
    handleChatMessage,
    handleError,
    setAuthBootstrapped,
    setAuthSession,
    setConnectionIssue,
    setConnectionStatus,
    setSendMessage,
  } = useStore();
  const socketRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptRef = useRef(0);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectAttemptRef.current = 0;
    const socket = socketRef.current;
    socketRef.current = null;
    setSendMessage(null);
    setConnectionStatus(false);
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.close(1000, "client disconnect");
    }
  }, [setConnectionStatus, setSendMessage]);

  const handleSocketMessage = useCallback(
    (message) => {
      const type = message?.type;
      const payload = message?.payload || {};
      if (type === "auth_success" || type === "guest_auth_success") {
        handleAuthSuccess(payload);
      } else if (type === "chat_channels") {
        handleChatChannels(payload);
      } else if (type === "chat_history") {
        handleChatHistory(payload);
      } else if (type === "chat_message") {
        handleChatMessage(payload);
      } else if (type === "chat_direct_started") {
        handleChatDirectStarted(payload);
      } else if (type === "error" || type === "auth_error") {
        handleError(payload);
      }
    },
    [
      handleAuthSuccess,
      handleChatChannels,
      handleChatDirectStarted,
      handleChatHistory,
      handleChatMessage,
      handleError,
    ]
  );

  const connect = useCallback(
    (accessToken) => {
      if (!accessToken || socketRef.current) return;
      const socket = new WebSocket(buildWsUrl("/ws", { token: accessToken }));
      socketRef.current = socket;
      setConnectionIssue("Connecting...");

      socket.onopen = () => {
        reconnectAttemptRef.current = 0;
        setConnectionStatus(true);
        setConnectionIssue("");
        setSendMessage((message) => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify(message));
          }
        });
        socket.send(JSON.stringify({ action: "request_chat_channels", payload: {} }));
      };

      socket.onmessage = (event) => {
        try {
          handleSocketMessage(JSON.parse(event.data));
        } catch (error) {
          console.warn("Invalid websocket message.", error);
        }
      };

      socket.onclose = () => {
        if (socketRef.current !== socket) return;
        socketRef.current = null;
        setSendMessage(null);
        setConnectionStatus(false);
        if (accessToken) {
          const attempt = reconnectAttemptRef.current + 1;
          reconnectAttemptRef.current = attempt;
          const delayMs = Math.min(10000, 750 * 2 ** Math.min(attempt - 1, 4));
          setConnectionIssue(`Realtime unavailable. Reconnecting in ${Math.ceil(delayMs / 1000)}s...`);
          reconnectTimerRef.current = window.setTimeout(() => connect(accessToken), delayMs);
        }
      };

      socket.onerror = () => {
        setConnectionIssue("Realtime unavailable. Reconnecting...");
      };
    },
    [
      handleSocketMessage,
      setConnectionIssue,
      setConnectionStatus,
      setSendMessage,
    ]
  );

  useEffect(() => {
    let disposed = false;
    let unsubscribe = () => {};
    setAuthBootstrapped(false);
    void ensureFirebasePersistence().then(() => {
      unsubscribe = subscribeToIdTokenChanges(async (firebaseUser) => {
        if (disposed) return;
        if (!firebaseUser) {
          disconnect();
          clearAuth();
          setAuthBootstrapped(true);
          return;
        }
        try {
          const accessToken = await firebaseUser.getIdToken(true);
          const ok = setAuthSession({ accessToken });
          if (ok) await fetchAuthMe();
        } finally {
          setAuthBootstrapped(true);
        }
      });
    });
    return () => {
      disposed = true;
      unsubscribe();
      disconnect();
    };
  }, [clearAuth, disconnect, fetchAuthMe, setAuthBootstrapped, setAuthSession]);

  useEffect(() => {
    if (!authBootstrapped || !token) return undefined;
    void fetchSessionState();
    const sessionIntervalId = window.setInterval(() => {
      void fetchSessionState();
    }, 15000);
    connect(token);
    return () => {
      window.clearInterval(sessionIntervalId);
      disconnect();
    };
  }, [authBootstrapped, connect, disconnect, fetchSessionState, token]);

  useEffect(() => {
    if (!authBootstrapped || !token || !connectionIssue.startsWith("Backend unavailable")) {
      return undefined;
    }
    let cancelled = false;
    const clearWhenHealthy = async () => {
      try {
        const response = await fetch(buildApiUrl("/api/health"), { cache: "no-store" });
        if (!cancelled && response.ok) setConnectionIssue("");
      } catch (_error) {
        // The regular auth/session retry loop owns the visible connection state.
      }
    };
    void clearWhenHealthy();
    const intervalId = window.setInterval(clearWhenHealthy, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [authBootstrapped, connectionIssue, setConnectionIssue, token]);

  const handleLogout = async () => {
    disconnect();
    try {
      await signOutFirebase();
    } catch (error) {
      console.warn("Firebase sign-out failed.", error);
    }
    clearAuth();
  };

  const authenticatedPage = (page) =>
    token ? (
      <AuthenticatedLayout onLogout={handleLogout}>{page}</AuthenticatedLayout>
    ) : (
      <Navigate to="/auth" />
    );
  const inGamePage = (page) => (token ? page : <Navigate to="/auth" />);
  const isInGameRoom = /^\/games\/[^/]+$/.test(location.pathname) || /^\/admin\/replays\/[^/]+$/.test(location.pathname);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <StateGuard>
        {authBootstrapped && token && connectionIssue && !isInGameRoom ? (
          <div className="fixed left-1/2 top-3 z-[1000] -translate-x-1/2 rounded-full border border-amber-300/70 bg-slate-950/95 px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-amber-100 shadow-xl">
            {connectionIssue}
          </div>
        ) : null}
        {authBootstrapped && token && !isInGameRoom ? <GlobalChatOverlay /> : null}
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route path="/lobby" element={authenticatedPage(<LobbyPage />)} />
          <Route path="/play" element={authenticatedPage(<PlayPage />)} />
          <Route path="/play/solo" element={authenticatedPage(<SoloPlayPage />)} />
          <Route path="/profile/:userId" element={authenticatedPage(<ProfilePage />)} />
          <Route path="/profile/:userId/friends" element={authenticatedPage(<FriendsPage />)} />
          <Route path="/profile/:userId/history" element={authenticatedPage(<GameHistoryPage />)} />
          <Route path="/games/:roomId" element={inGamePage(<GameRoomPage />)} />
          <Route path="/games/:roomId/post-game" element={authenticatedPage(<PostGamePage />)} />
          <Route path="/admin" element={authenticatedPage(<AdminPage />)} />
          <Route path="/admin/content" element={authenticatedPage(<AdminContentPage />)} />
          <Route path="/admin/replays/:replayId" element={inGamePage(<GameRoomPage replayMode />)} />
          <Route path="*" element={<Navigate to={token ? "/lobby" : "/auth"} />} />
        </Routes>
      </StateGuard>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}

export default App;
