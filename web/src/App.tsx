import * as React from "react";
import { Navigate, type RouteObject } from "react-router-dom";
import { Shell } from "./components/Shell";
import { HubProvider } from "./lib/state";

const lazy = (load: () => Promise<{ default: React.ComponentType }>) => {
  const C = React.lazy(load);
  return <React.Suspense fallback={<div className="p-6 text-[13px] text-muted-foreground">Loading…</div>}><C /></React.Suspense>;
};

/** Pages inside a project: /p/<project>/… */
export const projectRoutes: RouteObject[] = [
  { index: true, element: <Navigate to="home" replace /> },
  { path: "home", element: lazy(() => import("./pages/Home")) },
  { path: "runs", element: lazy(() => import("./pages/Runs")) },
  { path: "runs/:slug", element: lazy(() => import("./pages/RunPage")) },
  { path: "runs/:slug/:tab", element: lazy(() => import("./pages/RunPage")) },
  { path: "compare/:slugs", element: lazy(() => import("./pages/Compare")) },
  { path: "research", element: lazy(() => import("./pages/Research")) },
  { path: "research/:topic", element: lazy(() => import("./pages/Research")) },
  { path: "post/:post", element: lazy(() => import("./pages/Research")) },
  { path: "messages", element: lazy(() => import("./pages/Messages")) },
  { path: "messages/:channel", element: lazy(() => import("./pages/Messages")) },
  { path: "feedback", element: lazy(() => import("./pages/Feedback")) },
  { path: "designs", element: lazy(() => import("./pages/Designs")) },
  { path: "designs/:design", element: lazy(() => import("./pages/DesignPage")) },
  { path: "handbook", element: lazy(() => import("./pages/Handbook")) },
  { path: "settings", element: lazy(() => import("./pages/ProjectSettings")) },
  { path: "*", element: <Navigate to="home" replace /> },
];

/** Pages that belong to the signed-in person, not to a project. */
export const siteRoutes: RouteObject[] = [
  { index: true, element: lazy(() => import("./pages/Projects")) },
  { path: "account", element: lazy(() => import("./pages/Account")) },
  { path: "docs", element: lazy(() => import("./pages/Docs")) },
  { path: "docs/:guide", element: lazy(() => import("./pages/Docs")) },
  { path: "docs/:guide/:section", element: lazy(() => import("./pages/Docs")) },
  { path: "admin", element: lazy(() => import("./pages/Admin")) },
  { path: "*", element: <Navigate to="/" replace /> },
];

export function App() {
  return (
    <HubProvider>
      <Shell />
    </HubProvider>
  );
}
