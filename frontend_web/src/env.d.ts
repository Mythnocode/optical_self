/// <reference types="vite/client" />

import type { DesktopBridge } from "../../desktop/bridge-contract.js";

declare global {
  interface Window {
    opticalDesktop?: DesktopBridge;
  }
}

export {};
