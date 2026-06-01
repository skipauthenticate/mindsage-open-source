/// <reference types="vite/client" />

// noVNC type declarations
declare module '@novnc/novnc' {
  interface RFBOptions {
    credentials?: {
      password?: string;
      target?: string;
      username?: string;
    };
    shared?: boolean;
    repeaterID?: string;
    wsProtocols?: string[];
  }

  export default class RFB {
    constructor(target: HTMLElement, url: string, options?: RFBOptions);

    // Properties
    viewOnly: boolean;
    focusOnClick: boolean;
    clipViewport: boolean;
    dragViewport: boolean;
    scaleViewport: boolean;
    resizeSession: boolean;
    showDotCursor: boolean;
    background: string;
    qualityLevel: number;
    compressionLevel: number;
    capabilities: {
      power: boolean;
    };

    // Methods
    disconnect(): void;
    sendCredentials(credentials: { password?: string; target?: string; username?: string }): void;
    sendKey(keysym: number, code: string | null, down?: boolean): void;
    sendCtrlAltDel(): void;
    focus(): void;
    blur(): void;
    machineShutdown(): void;
    machineReboot(): void;
    machineReset(): void;
    clipboardPasteFrom(text: string): void;

    // Events
    addEventListener(type: 'connect', listener: () => void): void;
    addEventListener(type: 'disconnect', listener: (e: CustomEvent) => void): void;
    addEventListener(type: 'credentialsrequired', listener: () => void): void;
    addEventListener(type: 'securityfailure', listener: (e: CustomEvent) => void): void;
    addEventListener(type: 'clipboard', listener: (e: CustomEvent) => void): void;
    addEventListener(type: 'bell', listener: () => void): void;
    addEventListener(type: 'desktopname', listener: (e: CustomEvent) => void): void;
    addEventListener(type: 'capabilities', listener: (e: CustomEvent) => void): void;
    removeEventListener(type: string, listener: EventListener): void;
  }
}
