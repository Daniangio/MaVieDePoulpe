import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { PageSubnavigation } from "../components/AuthenticatedLayout.jsx";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const FriendsPage = () => {
  const { user, token } = useStore();
  const { userId } = useParams();
  const [friendsData, setFriendsData] = useState(null);
  const [usernameInput, setUsernameInput] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const isOwnProfile = !userId || userId === user?.id;
  const targetUserId = userId || user?.id;
  const profileSubnavItems = [
    { label: "Profile", to: `/profile/${targetUserId}` },
    { label: "Friends", to: `/profile/${targetUserId}/friends` },
    { label: "History", to: `/profile/${targetUserId}/history` },
  ];

  const loadFriends = async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(buildApiUrl("/api/friends"), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to load friends.");
      setFriendsData(payload);
    } catch (loadError) {
      setError(loadError.message || "Failed to load friends.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadFriends();
  }, [token, user?.id]);

  const submitRequest = async () => {
    if (!usernameInput.trim() || !token) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(buildApiUrl("/api/friends/requests"), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ username: usernameInput.trim() }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to send request.");
      setFriendsData(payload);
      setUsernameInput("");
    } catch (requestError) {
      setError(requestError.message || "Failed to send request.");
    } finally {
      setBusy(false);
    }
  };

  const respond = async (requestId, accept) => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(buildApiUrl(`/api/friends/requests/${requestId}`), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ accept }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to update request.");
      setFriendsData(payload);
    } catch (requestError) {
      setError(requestError.message || "Failed to update request.");
    } finally {
      setBusy(false);
    }
  };

  const removeFriend = async (friendUserId) => {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(buildApiUrl(`/api/friends/${friendUserId}`), {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to remove friend.");
      setFriendsData(payload);
    } catch (requestError) {
      setError(requestError.message || "Failed to remove friend.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageSubnavigation items={profileSubnavItems} />

      {!isOwnProfile ? (
        <section className="rounded-lg border border-slate-800 bg-slate-900 p-6">
          <h1 className="text-2xl font-semibold text-white">Friends</h1>
          <p className="mt-2 text-slate-400">Friend management is available from your own profile.</p>
        </section>
      ) : (
        <section className="grid gap-4 md:grid-cols-[20rem_1fr]">
          <aside className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <h1 className="text-2xl font-semibold text-white">Friends</h1>
            <p className="mt-2 text-sm text-slate-400">Add players by exact username or email.</p>
            <div className="mt-5 flex gap-2">
              <input
                value={usernameInput}
                onChange={(event) => setUsernameInput(event.target.value)}
                className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-teal-400"
                placeholder="username"
              />
              <button className="rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300" onClick={submitRequest} disabled={busy}>
                Send
              </button>
            </div>
            {error ? <p className="mt-4 rounded-md bg-rose-950/70 px-3 py-2 text-sm text-rose-200">{error}</p> : null}
          </aside>

          <div className="space-y-4">
            <Panel title="Incoming Requests">
              <RequestList entries={friendsData?.incoming_requests || []} empty="No incoming requests.">
                {(entry) => (
                  <div className="flex gap-2">
                    <button className="rounded-md bg-teal-400 px-3 py-1.5 text-sm font-semibold text-slate-950" onClick={() => respond(entry.request_id, true)} disabled={busy}>Accept</button>
                    <button className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200" onClick={() => respond(entry.request_id, false)} disabled={busy}>Decline</button>
                  </div>
                )}
              </RequestList>
            </Panel>

            <Panel title="Outgoing Requests">
              <RequestList entries={friendsData?.outgoing_requests || []} empty="No outgoing requests." />
            </Panel>

            <Panel title="Friends">
              {loading ? <p className="text-slate-400">Loading friends...</p> : null}
              {(friendsData?.friends || []).map((entry) => (
                <div key={entry.user.id} className="flex items-center justify-between gap-3 border-b border-slate-800 py-3 last:border-0">
                  <div>
                    <Link className="font-medium text-white hover:text-teal-200" to={`/profile/${entry.user.id}`}>
                      {entry.user.username}
                    </Link>
                    <p className="mt-1 text-xs text-slate-500">
                      Friends since {entry.since ? new Date(entry.since).toLocaleDateString() : "unknown"}
                    </p>
                  </div>
                  <button className="rounded-md border border-rose-500/60 px-3 py-1.5 text-sm text-rose-200 hover:bg-rose-950" onClick={() => removeFriend(entry.user.id)} disabled={busy}>
                    Remove
                  </button>
                </div>
              ))}
              {!loading && (friendsData?.friends || []).length === 0 ? <p className="text-slate-400">No friends yet.</p> : null}
            </Panel>
          </div>
        </section>
      )}
    </>
  );
};

const Panel = ({ title, children }) => (
  <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
    <h2 className="mb-3 font-semibold text-white">{title}</h2>
    {children}
  </section>
);

const RequestList = ({ entries, empty, children }) => {
  if (!entries.length) return <p className="text-slate-400">{empty}</p>;
  return entries.map((entry) => (
    <div key={entry.request_id} className="flex items-center justify-between gap-3 border-b border-slate-800 py-3 last:border-0">
      <Link className="font-medium text-white hover:text-teal-200" to={`/profile/${entry.user.id}`}>
        {entry.user.username}
      </Link>
      {children ? children(entry) : null}
    </div>
  ));
};

export default FriendsPage;
