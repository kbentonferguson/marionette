// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import QueueRecoveryNotice from "../components/conversation/QueueRecoveryNotice";

afterEach(cleanup);
it("shows original content without running or copying until explicitly requested", () => {
  const onCopy = vi.fn();
  const content = '{"queue":[{"text":"original draft"}]}';
  render(<QueueRecoveryNotice entries={[{ kind: "legacy", path: "/isolated/prompt_queue.json", content }]} onCopy={onCopy} />);
  expect(onCopy).not.toHaveBeenCalled();
  expect(screen.getByText(content)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Copy to composer for review", hidden: true }));
  expect(onCopy).toHaveBeenCalledWith(content);
});
it("keeps unreadable evidence visible without offering an empty copy", () => {
  render(<QueueRecoveryNotice entries={[{ kind: "unreadable", path: "/isolated/queue.json", content: null }]} />);
  expect(screen.getByText(/Restore read access/)).toBeTruthy();
  expect(screen.queryByRole("button", { hidden: true })).toBeNull();
});
