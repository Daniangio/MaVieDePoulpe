import { useState } from "react";
import { signInWithEmail, signUpWithEmail } from "../lib/firebase.js";

const AuthPage = () => {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleAuth = async (event) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (isLogin) {
        await signInWithEmail(email.trim(), password);
      } else {
        await signUpWithEmail(email.trim(), password);
      }
    } catch (err) {
      setError(err?.message || "Authentication failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-10">
      <section className="grid w-full max-w-5xl overflow-hidden rounded-lg border border-slate-800 bg-slate-900 shadow-2xl md:grid-cols-[1fr_24rem]">
        <div className="flex min-h-[28rem] flex-col justify-between bg-[radial-gradient(circle_at_20%_20%,rgba(45,212,191,0.22),transparent_32%),linear-gradient(135deg,#0f172a,#111827_55%,#022c22)] p-8">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.22em] text-teal-200">
              Ma vie de poulpe
            </p>
            <h1 className="mt-4 max-w-xl text-4xl font-semibold tracking-normal text-white">
              Auth, lobby, profiles, friends, chat, rooms, and admin backoffice.
            </h1>
          </div>
          <p className="max-w-xl text-sm leading-6 text-slate-300">
            The reusable account and social layer is ready while the new game loop is built.
          </p>
        </div>

        <form onSubmit={handleAuth} className="space-y-5 p-6">
          <div>
            <h2 className="text-2xl font-semibold text-white">
              {isLogin ? "Sign in" : "Create account"}
            </h2>
            <p className="mt-2 text-sm text-slate-400">
              Firebase email/password authentication is used in development and production.
            </p>
          </div>

          <label className="block">
            <span className="text-sm font-medium text-slate-300">Email</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-teal-400"
              required
              disabled={loading}
            />
          </label>

          <label className="block">
            <span className="text-sm font-medium text-slate-300">Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-white outline-none focus:border-teal-400"
              required
              disabled={loading}
            />
          </label>

          {error ? <p className="rounded-md bg-rose-950/70 px-3 py-2 text-sm text-rose-200">{error}</p> : null}

          <button
            type="submit"
            className="w-full rounded-md bg-teal-400 px-4 py-2 font-semibold text-slate-950 transition hover:bg-teal-300 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={loading}
          >
            {loading ? "Working..." : isLogin ? "Sign in" : "Create account"}
          </button>

          <button
            type="button"
            onClick={() => {
              setIsLogin((value) => !value);
              setError("");
            }}
            className="w-full text-sm font-medium text-teal-200 hover:text-teal-100"
            disabled={loading}
          >
            {isLogin ? "Need an account? Register" : "Already have an account? Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
};

export default AuthPage;
