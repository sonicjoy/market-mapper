import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import swan from "../assets/logos/wsd/swan.png";
import { getMeta, listReview } from "../api";
import { useCart } from "../cartStore";
import { consoleTitle, envLabel } from "../lib/identity";
import { dockPath } from "../lib/pageFilters";
import { waitingReviewCount } from "../lib/reviewQueue";
import { LAYOUT_LIVE_BANNER, LAYOUT_SHADOW_BANNER } from "../lib/sotCopy";
import { bootTheme } from "../lib/theme";
import { NAV } from "../nav";
import { AgentChat } from "./AgentChat";
import { ThemeToggle } from "./ThemeToggle";

function NavCount({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="rounded bg-brand-100 px-1.5 text-[10px] font-semibold text-brand-700 dark:bg-brand-900 dark:text-brand-200">
      {count}
    </span>
  );
}

export function Layout() {
  const location = useLocation();
  const cart = useCart();
  const { data: meta, isLoading, isError } = useQuery({
    queryKey: ["meta"],
    queryFn: getMeta,
  });
  const { data: reviewQueue } = useQuery({
    queryKey: ["review"],
    queryFn: listReview,
    refetchInterval: 15_000,
  });
  const reviewWaiting = waitingReviewCount(reviewQueue);

  // Tab title carries the environment so a TEST tab is never mistaken for PROD. Set from meta rather
  // than index.html, which cannot know which overlay the image landed in.
  useEffect(() => {
    document.title = consoleTitle(meta?.env);
  }, [meta?.env]);

  useEffect(() => bootTheme(), []);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-slate-500 dark:text-slate-400">
        Loading mapping console…
      </div>
    );
  }
  if (isError || !meta) {
    return (
      <div className="flex h-screen items-center justify-center text-sm text-red-600">
        Failed to load console metadata. Is the control-plane API running?
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-2.5 dark:border-slate-800 dark:bg-slate-900">
        {/* White Swan Predicts brand, as in mm-trading-dash's Layout: the investor portal's swan, darkened
            on the light theme, + the boxed HTML wordmark in ink and Predicts orange, then the console name.
            Predicts from md, full size + console name from lg, so the operator line never wraps. */}
        <div className="flex items-center gap-3">
          <img
            src={swan}
            alt="White Swan Predicts"
            className="h-9 w-auto brightness-[.22] contrast-[1.1] dark:filter-none"
          />
          <span
            aria-hidden
            className="hidden items-center gap-1.5 whitespace-nowrap text-[10.5px] font-bold uppercase leading-none tracking-[0.14em] sm:inline-flex lg:gap-2 lg:text-[12.5px] lg:tracking-[0.17em]"
          >
            <span className="rounded-sm bg-[#161110] px-1.5 py-[5px] text-white dark:bg-[#F3EFEB] dark:text-slate-900 lg:px-2 lg:py-1.5">
              White Swan
            </span>
            <span className="hidden text-[#FC551C] dark:text-[#FF6A33] md:inline">Predicts</span>
          </span>
          <Link
            to="/entry"
            className="hidden border-l border-slate-300 pl-3 text-[12.5px] font-medium text-slate-500 dark:border-slate-700 dark:text-slate-400 lg:inline"
          >
            Mappings
          </Link>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {envLabel(meta.env) || meta.env}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <div className="text-xs text-slate-500 dark:text-slate-400">
            {meta.operator} · {meta.role}
          </div>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside className="w-48 shrink-0 border-r border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
          <nav className="space-y-4">
            {(["Explore", "Work"] as const).map((group) => {
              const items = NAV.filter(
                (n) =>
                  n.group === group &&
                  (!n.adminOnly || meta.role === "admin") &&
                  (n.path !== "/catalog" || meta.catalog_enabled !== false),
              );
              if (items.length === 0) {
                return null;
              }
              return (
              <div key={group}>
                <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  {group}
                </div>
                <ul className="space-y-0.5">
                  {items.map((n) => (
                    <li key={n.path}>
                      <NavLink
                        to={dockPath(n.path, location.pathname, location.search)}
                        className={({ isActive }) =>
                          `flex items-center justify-between rounded-md px-2 py-1.5 text-sm ${
                            isActive
                              ? "bg-brand-50 font-medium text-brand-700 dark:bg-brand-950/60 dark:text-brand-200"
                              : "text-slate-700 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800"
                          }`
                        }
                      >
                        <span>{n.label}</span>
                        {n.path === "/cart" ? <NavCount count={cart.length} /> : null}
                        {n.path === "/review" ? <NavCount count={reviewWaiting} /> : null}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
              );
            })}
          </nav>
        </aside>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <main className="min-h-0 flex-1 overflow-auto p-5">
            {location.pathname.startsWith("/review") ? (
              <div className="mb-4 notice-amber text-xs">
                {meta.live_sot === "bq" && meta.allow_activate
                  ? LAYOUT_LIVE_BANNER
                  : LAYOUT_SHADOW_BANNER}
              </div>
            ) : null}
            <Outlet />
          </main>
          <AgentChat />
        </div>
      </div>
    </div>
  );
}
