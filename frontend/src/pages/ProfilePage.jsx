import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { PageSubnavigation } from "../components/AuthenticatedLayout.jsx";
import { useStore } from "../store.js";
import { buildApiUrl } from "../utils/connection.js";

const ProfilePage = () => {
  const { user, token } = useStore();
  const { userId } = useParams();
  const navigate = useNavigate();
  const [profile, setProfile] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const targetUserId = userId || user?.id;
  const profileSubnavItems = [
    { label: "Profile", to: `/profile/${targetUserId}` },
    { label: "Friends", to: `/profile/${targetUserId}/friends` },
    { label: "History", to: `/profile/${targetUserId}/history` },
  ];

  const loadProfile = async () => {
    if (!targetUserId || !token) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(buildApiUrl(`/api/players/${targetUserId}`), {
        headers: { Authorization: `Bearer ${token}` },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Failed to load profile.");
      setProfile(payload);
    } catch (loadError) {
      setError(loadError.message || "Failed to load profile.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadProfile();
  }, [targetUserId, token]);

  const friendAction = async (action) => {
    if (!profile?.user?.id || !token) return;
    setBusy(true);
    setError("");
    try {
      const options =
        action === "send"
          ? {
              method: "POST",
              headers: {
                Authorization: `Bearer ${token}`,
                "Content-Type": "application/json",
              },
              body: JSON.stringify({ target_user_id: profile.user.id }),
            }
          : {
              method: "DELETE",
              headers: { Authorization: `Bearer ${token}` },
            };
      const url =
        action === "send"
          ? buildApiUrl("/api/friends/requests")
          : buildApiUrl(`/api/friends/${profile.user.id}`);
      const response = await fetch(url, options);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Friend action failed.");
      await loadProfile();
    } catch (actionError) {
      setError(actionError.message || "Friend action failed.");
    } finally {
      setBusy(false);
    }
  };

  const renderFriendButton = () => {
    if (!profile || profile.is_self) {
      return (
        <button
          className="rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300"
          onClick={() => navigate(`/profile/${user?.id}/friends`)}
        >
          Manage friends
        </button>
      );
    }
    if (profile.friend_status === "friends") {
      return (
        <button
          className="rounded-md border border-rose-500/60 px-3 py-2 text-sm text-rose-200 hover:bg-rose-950"
          onClick={() => friendAction("remove")}
          disabled={busy}
        >
          Remove friend
        </button>
      );
    }
    if (profile.friend_status === "outgoing_request") {
      return <span className="rounded-md bg-slate-800 px-3 py-2 text-sm text-slate-300">Request sent</span>;
    }
    if (profile.friend_status === "incoming_request") {
      return <Link className="rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950" to={`/profile/${user?.id}/friends`}>Respond</Link>;
    }
    return (
      <button
        className="rounded-md bg-teal-400 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-teal-300"
        onClick={() => friendAction("send")}
        disabled={busy}
      >
        Add friend
      </button>
    );
  };

  return (
    <>
      <PageSubnavigation items={profileSubnavItems} />

      {error ? <p className="mb-4 rounded-md bg-rose-950/70 px-3 py-2 text-sm text-rose-200">{error}</p> : null}
      {loading ? <p className="text-slate-400">Loading profile...</p> : null}

      {profile ? (
        <section className="rounded-lg border border-slate-800 bg-slate-900 p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-3xl font-semibold text-white">{profile.user.username}</h1>
                <span className={`rounded-full px-2 py-1 text-xs ${profile.user.online ? "bg-emerald-500/15 text-emerald-200" : "bg-slate-800 text-slate-400"}`}>
                  {profile.user.online ? "online" : "offline"}
                </span>
              </div>
              {profile.user.email ? <p className="mt-2 text-sm text-slate-400">{profile.user.email}</p> : null}
              <p className="mt-1 break-all text-xs text-slate-500">{profile.user.id}</p>
            </div>
            {renderFriendButton()}
          </div>

          <dl className="mt-8 grid gap-4 sm:grid-cols-3">
            <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Friends</dt>
              <dd className="mt-2 text-2xl font-semibold text-white">{profile.friends_count}</dd>
            </div>
            <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Relation</dt>
              <dd className="mt-2 text-sm font-medium text-slate-200">{profile.friend_status}</dd>
            </div>
            <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-500">Role</dt>
              <dd className="mt-2 text-sm font-medium text-slate-200">{profile.user.is_admin ? "Admin" : "Player"}</dd>
            </div>
          </dl>
        </section>
      ) : null}
    </>
  );
};

export default ProfilePage;
