import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

// jsdom's File implementation predates Blob.text()/arrayBuffer(); polyfill
// just enough so AOI parser tests work without spinning up a real browser.
interface BlobShim {
  text?: (this: File) => Promise<string>;
  arrayBuffer?: (this: File) => Promise<ArrayBuffer>;
}
if (typeof File !== "undefined") {
  const proto = File.prototype as unknown as BlobShim;
  if (!proto.text) {
    proto.text = function text(this: File): Promise<string> {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const result = reader.result;
          resolve(typeof result === "string" ? result : "");
        };
        reader.onerror = () => reject(reader.error ?? new Error("FileReader error"));
        reader.readAsText(this);
      });
    };
  }
  if (!proto.arrayBuffer) {
    proto.arrayBuffer = function arrayBuffer(this: File): Promise<ArrayBuffer> {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as ArrayBuffer);
        reader.onerror = () => reject(reader.error ?? new Error("FileReader error"));
        reader.readAsArrayBuffer(this);
      });
    };
  }
}

// jsdom does not implement these — stub so any code that touches them in
// tests doesn't blow up. Keep the stubs minimal and matched to need.
if (typeof window !== "undefined") {
  if (!window.matchMedia) {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  }
}
