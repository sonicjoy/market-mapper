import { Suspense, lazy } from "react";
import { createBrowserRouter, Navigate } from "react-router-dom";

import { Layout } from "./components/Layout";
import { RequireAdmin } from "./components/RequireAdmin";
import { CartPage } from "./pages/CartPage";
import { CoveragePage } from "./pages/CoveragePage";
import { EntryPage } from "./pages/EntryPage";
import { ReviewDetailPage } from "./pages/ReviewDetailPage";
import { ReviewPage } from "./pages/ReviewPage";
import { RulesPage } from "./pages/RulesPage";
import { BulkOverridePage } from "./pages/BulkOverridePage";
import { CatalogPage } from "./pages/CatalogPage";
import { MissingPage } from "./pages/MissingPage";
import { OverridePatternsPage } from "./pages/OverridePatternsPage";
import { UnmappedPage } from "./pages/UnmappedPage";
import { VenueGapsPage } from "./pages/VenueGapsPage";
import { GapLeaderboardPage } from "./pages/GapLeaderboardPage";
import { MappingRiskPage } from "./pages/MappingRiskPage";

const ApiDocsPage = lazy(() => import("./pages/ApiDocsPage"));

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/entry" replace /> },
      { path: "entry", element: <EntryPage /> },
      { path: "cart", element: <CartPage /> },
      { path: "inbox", element: <Navigate to="/entry" replace /> },
      { path: "review", element: <ReviewPage /> },
      { path: "review/:ref", element: <ReviewDetailPage /> },
      { path: "gap-leaderboard", element: <GapLeaderboardPage /> },
      { path: "rules", element: <RulesPage /> },
      { path: "coverage", element: <CoveragePage /> },
      { path: "unmapped", element: <UnmappedPage /> },
      { path: "missing", element: <MissingPage /> },
      { path: "venue-gaps", element: <VenueGapsPage /> },
      { path: "override-patterns", element: <OverridePatternsPage /> },
      { path: "mapping-risk", element: <MappingRiskPage /> },
      { path: "catalog", element: <CatalogPage /> },
      { path: "bulk-override", element: <BulkOverridePage /> },
      {
        path: "api-docs",
        element: (
          <RequireAdmin>
            <Suspense fallback={<p className="text-sm text-slate-500 dark:text-slate-400">Loading API docs…</p>}>
              <ApiDocsPage />
            </Suspense>
          </RequireAdmin>
        ),
      },
    ],
  },
]);
