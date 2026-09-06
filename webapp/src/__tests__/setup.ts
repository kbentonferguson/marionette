import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import "../index.css";

afterEach(() => {
  cleanup();
});

// jsdom has no dialog top layer. Browser focus containment/backdrops need E2E;
// these shims expose open/close and focus restoration for component regressions.
if (!HTMLDialogElement.prototype.showModal) {
  const priorFocus = new WeakMap<HTMLDialogElement, Element | null>();
  HTMLDialogElement.prototype.showModal = function () {
    priorFocus.set(this, document.activeElement);
    this.open = true;
    this.querySelector<HTMLElement>("[autofocus], button, input, select, textarea")?.focus();
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
    const previous = priorFocus.get(this);
    if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    priorFocus.delete(this);
  };
}
