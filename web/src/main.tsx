import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/outfit/400.css";
import "@fontsource/outfit/500.css";
import "@fontsource/outfit/700.css";
import "@fontsource/geist-mono/400.css";
import "@fontsource/geist-mono/500.css";
import "./index.css";
import App from "./App";
import { consumeAccessTokenFromFragment } from "./utils/accessToken";

try {
  const stored = localStorage.getItem("gms-theme");
  if (stored === "light" || stored === "dark") {
    document.documentElement.dataset.theme = stored;
  } else {
    document.documentElement.dataset.theme = "dark";
  }
} catch {
  document.documentElement.dataset.theme = "dark";
}

consumeAccessTokenFromFragment();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);