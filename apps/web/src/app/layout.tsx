import type { Metadata, Viewport } from "next";
import "@xyflow/react/dist/style.css";
import "./globals.css";
import "./studio.css";
import "./story-map.css";
import "./asset-preview.css";
import "./assistant.css";
import "./creative-spaces.css";
import "./os-desktop.css";
import "./interaction-consistency.css";
import "./diagnostic-console.css";
import "./cloud-generation.css";
import "./fullscreen-voice.css";
import "./trusted-workflows.css";
import "./director-desk.css";
import "./mobile.css";
import "./conversation-studio.css";
import "./workspace-refinement.css";
import "./canvas.css";
import "./video-board.css";
import "./moss-workspace.css";
import "./canvas-refinement.css";
import "./creative-helper.css";
import "./board-setup.css";
import { AppProviders } from "./providers";

export const metadata: Metadata = {
  title: "Darius — Creative production",
  description: "Local-first conversational creative production for filmmakers.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
