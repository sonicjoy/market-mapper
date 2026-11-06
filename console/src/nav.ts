export type NavGroup = "Work" | "Explore";

export type NavItem = {
  path: string;
  label: string;
  group: NavGroup;
  adminOnly?: boolean;
};

export const NAV: NavItem[] = [
  { path: "/entry", label: "Editor", group: "Work" },
  { path: "/cart", label: "Cart", group: "Work" },
  { path: "/review", label: "Proposed", group: "Work" },
  { path: "/bulk-override", label: "Bulk override", group: "Work" },
  { path: "/gap-leaderboard", label: "Gap leaderboard", group: "Explore" },
  { path: "/rules", label: "Rules", group: "Explore" },
  { path: "/coverage", label: "Coverage", group: "Explore" },
  { path: "/unmapped", label: "Unmapped", group: "Explore" },
  { path: "/missing", label: "Missing", group: "Explore" },
  { path: "/venue-gaps", label: "Venue gaps", group: "Explore" },
  { path: "/override-patterns", label: "Override patterns", group: "Explore" },
  { path: "/mapping-risk", label: "Mapping risk", group: "Explore" },
  { path: "/catalog", label: "Catalog", group: "Explore" },
  { path: "/api-docs", label: "API Docs", group: "Explore", adminOnly: true },
];
