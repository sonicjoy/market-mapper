import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { getMeta } from "../api";

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { data: meta, isLoading } = useQuery({
    queryKey: ["meta"],
    queryFn: getMeta,
  });
  if (isLoading) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>;
  }
  if (meta?.role !== "admin") {
    return <Navigate to="/entry" replace />;
  }
  return children;
}
