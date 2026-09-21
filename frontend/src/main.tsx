import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import WorldExplorer from './WorldExplorer';

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {new URLSearchParams(location.search).get('view') === 'world' ? <WorldExplorer /> : <App />}
  </StrictMode>
);
