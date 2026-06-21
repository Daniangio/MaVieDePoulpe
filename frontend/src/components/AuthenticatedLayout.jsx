import { NavLink } from "react-router-dom";
import { useStore } from "../store.js";

const topNavBase =
  "rounded-md px-3 py-2 text-sm font-medium transition hover:bg-slate-900 hover:text-white";
const topNavActive = "bg-slate-900 text-white";
const topNavInactive = "text-slate-300";

const subNavBase =
  "rounded-md px-3 py-2 text-sm font-medium transition hover:bg-slate-800 hover:text-white";
const subNavActive = "bg-slate-800 text-white";
const subNavInactive = "text-slate-400";

export const PageSubnavigation = ({ items }) => {
  const visibleItems = (items || []).filter(Boolean);
  if (!visibleItems.length) return null;

  return (
    <nav className="mb-5 flex flex-wrap items-center gap-2 border-b border-slate-800 pb-4">
      {visibleItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end ?? true}
          className={({ isActive }) =>
            `${subNavBase} ${isActive ? subNavActive : subNavInactive}`
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
};

const AuthenticatedLayout = ({ children, onLogout }) => {
  const { user } = useStore();
  const profilePath = user?.id ? `/profile/${user.id}` : "/lobby";

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-6 text-slate-100">
      <div className="mx-auto max-w-6xl">
        <header className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
          <NavLink to="/lobby" className="text-lg font-semibold text-white">
            Ma vie de poulpe
          </NavLink>
          <nav className="flex flex-wrap items-center gap-2">
            <NavLink
              to="/lobby"
              className={({ isActive }) =>
                `${topNavBase} ${isActive ? topNavActive : topNavInactive}`
              }
            >
              Lobby
            </NavLink>
            <NavLink
              to={profilePath}
              className={({ isActive }) =>
                `${topNavBase} ${isActive ? topNavActive : topNavInactive}`
              }
            >
              Profile
            </NavLink>
            <NavLink
              to="/play"
              className={({ isActive }) =>
                `${topNavBase} ${isActive ? topNavActive : topNavInactive}`
              }
            >
              Play
            </NavLink>
            {user?.is_admin ? (
              <NavLink
                to="/admin"
                className={({ isActive }) =>
                  `${topNavBase} ${isActive ? topNavActive : topNavInactive}`
                }
              >
                Admin
              </NavLink>
            ) : null}
            <button
              className="rounded-md border border-slate-700 px-3 py-2 text-sm font-medium text-slate-200 transition hover:bg-slate-900 hover:text-white"
              onClick={onLogout}
              type="button"
            >
              Sign out
            </button>
          </nav>
        </header>
        {children}
      </div>
    </main>
  );
};

export default AuthenticatedLayout;
