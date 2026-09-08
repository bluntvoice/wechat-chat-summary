import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { GenerationTaskProvider } from "./contexts/GenerationTaskContext";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <GenerationTaskProvider><App /></GenerationTaskProvider>
  </StrictMode>,
);
