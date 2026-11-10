import "@fontsource-variable/inter";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router-dom";
import { App, projectRoutes, siteRoutes } from "./App";
import "./index.css";
import { queryClient } from "./lib/api";
import Auth from "./pages/Auth";

const router = createHashRouter([
  { path: "/login", element: <Auth mode="login" /> },
  { path: "/signup", element: <Auth mode="signup" /> },
  { path: "/setup", element: <Auth mode="setup" /> },
  { path: "/reset", element: <Auth mode="reset" /> },
  { path: "/p/:project", element: <App />, children: projectRoutes },
  { path: "/", element: <App />, children: siteRoutes },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
