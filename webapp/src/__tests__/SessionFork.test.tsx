// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, type Session } from "../lib/api";
import { SessionFork } from "../components/SessionFork";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const source: Session = { id: "parent", title: "Source", created: 1 };
const child: Session = { id: "child", title: "Fork of Source", created: 2,
  forked_from: { parent_id: "parent", at_event_id: 2 } };
const preview = { revision: "a".repeat(64), boundaries: [{ event_id: 2, label: "Done", role: "assistant" }] };

it("previews explicit boundaries, blocks duplicate submission and opens the child", async () => {
  vi.spyOn(api, "previewSessionFork").mockResolvedValue(preview);
  let complete: (value: Session) => void = () => { throw new Error("not pending"); };
  const fork = vi.spyOn(api, "forkSession").mockImplementation(() => new Promise((resolve) => { complete = resolve; }));
  const onSelect = vi.fn();
  const onCreated = vi.fn();
  render(<SessionFork session={source} sessions={[source]} onSelect={onSelect} onCreated={onCreated} />);
  fireEvent.click(screen.getByRole("button", { name: "Fork session" }));
  await screen.findByLabelText("Fork after saved message");
  const create = screen.getByRole("button", { name: "Create fork" });
  fireEvent.click(create);
  fireEvent.click(create);
  expect(fork).toHaveBeenCalledTimes(1);
  expect(fork).toHaveBeenCalledWith({ session_id: "parent", event_id: 2, revision: preview.revision, request_id: expect.any(String) });
  complete(child);
  fireEvent.click(await screen.findByRole("button", { name: "Open Fork of Source" }));
  expect(onCreated).toHaveBeenCalledWith(child);
  expect(onSelect).toHaveBeenCalledWith("child");
});

it("retains retry identity after failure and exposes ancestry selection", async () => {
  vi.spyOn(api, "previewSessionFork").mockResolvedValue(preview);
  const fork = vi.spyOn(api, "forkSession").mockRejectedValue(new Error("Source changed. Refresh boundaries."));
  const onSelect = vi.fn();
  render(<SessionFork session={child} sessions={[source, child]} onSelect={onSelect} onCreated={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Source" }));
  expect(onSelect).toHaveBeenCalledWith("parent");
  fireEvent.click(screen.getByRole("button", { name: "Fork session" }));
  fireEvent.click(await screen.findByRole("button", { name: "Create fork" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Source changed");
  fireEvent.click(screen.getByRole("button", { name: "Create fork" }));
  await waitFor(() => expect(fork).toHaveBeenCalledTimes(2));
  expect(fork.mock.calls[0]).toEqual(fork.mock.calls[1]);
});

it("shows an empty saved history with refresh and cancel controls", async () => {
  vi.spyOn(api, "previewSessionFork").mockResolvedValue({ revision: "a", boundaries: [] });
  render(<SessionFork session={source} sessions={[source]} onSelect={vi.fn()} onCreated={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Fork session" }));
  await screen.findByText("No saved boundary is available yet.");
  expect(screen.queryByRole("button", { name: "Create fork" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("button", { name: "Fork session" })).toBeTruthy();
});


it("keeps one child link after sessions refresh and creates a sibling with fresh identity", async () => {
  const load = vi.spyOn(api, "previewSessionFork").mockResolvedValue(preview);
  const sibling: Session = { ...child, id: "sibling", title: "Second fork" };
  const fork = vi.spyOn(api, "forkSession").mockResolvedValueOnce(child).mockResolvedValueOnce(sibling);
  const onSelect = vi.fn();
  const onCreated = vi.fn();
  const view = render(<SessionFork session={source} sessions={[source]} onSelect={onSelect} onCreated={onCreated} />);
  fireEvent.click(screen.getByRole("button", { name: "Fork session" }));
  fireEvent.click(await screen.findByRole("button", { name: "Create fork" }));
  const another = await screen.findByRole("button", { name: "Create another fork" });
  expect(document.activeElement).toBe(another);
  expect(screen.getAllByRole("button", { name: "Open Fork of Source" })).toHaveLength(1);
  view.rerender(<SessionFork session={source} sessions={[source, child]} onSelect={onSelect} onCreated={onCreated} />);
  expect(screen.getAllByRole("button", { name: "Open Fork of Source" })).toHaveLength(1);
  expect(onSelect).not.toHaveBeenCalled();
  fireEvent.click(another);
  fireEvent.click(await screen.findByRole("button", { name: "Create fork" }));
  await screen.findByRole("button", { name: "Open Second fork" });
  expect(load).toHaveBeenCalledTimes(2);
  expect(fork.mock.calls[1][0].request_id).not.toBe(fork.mock.calls[0][0].request_id);
  expect(fork.mock.calls[1][0].session_id).toBe(source.id);
  expect(onCreated).toHaveBeenNthCalledWith(2, sibling);
  expect(onSelect).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Open Fork of Source" }));
  expect(onSelect).toHaveBeenCalledWith(child.id);
});

it("refreshes a stale preview before creating with a new revision and identity", async () => {
  const refreshed = { ...preview, revision: "b".repeat(64) };
  vi.spyOn(api, "previewSessionFork").mockResolvedValueOnce(preview).mockResolvedValueOnce(refreshed);
  const fork = vi.spyOn(api, "forkSession").mockRejectedValueOnce(new Error("Source changed. Refresh boundaries.")).mockResolvedValueOnce(child);
  render(<SessionFork session={source} sessions={[source]} onSelect={vi.fn()} onCreated={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Fork session" }));
  fireEvent.click(await screen.findByRole("button", { name: "Create fork" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Refresh boundaries" }));
  fireEvent.click(await screen.findByRole("button", { name: "Create fork" }));
  await screen.findByText("Fork created.");
  expect(fork.mock.calls[1][0].revision).toBe(refreshed.revision);
  expect(fork.mock.calls[1][0].request_id).not.toBe(fork.mock.calls[0][0].request_id);
});

it.each(["resolve", "reject"])("ignores a create %s after switching away from the source", async (outcome) => {
  vi.spyOn(api, "previewSessionFork").mockResolvedValue(preview);
  let complete: (value: Session) => void = () => { throw new Error("not pending"); };
  let fail: (error: Error) => void = () => { throw new Error("not pending"); };
  const fork = vi.spyOn(api, "forkSession").mockImplementation(() => new Promise((resolve, reject) => { complete = resolve; fail = reject; }));
  const onCreated = vi.fn();
  const onSelect = vi.fn();
  const view = render(<SessionFork key={source.id} session={source} sessions={[source]} onSelect={onSelect} onCreated={onCreated} />);
  fireEvent.click(screen.getByRole("button", { name: "Fork session" }));
  fireEvent.click(await screen.findByRole("button", { name: "Create fork" }));
  expect(screen.getByRole("button", { name: "Creating fork..." }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Refresh boundaries" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Cancel" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByLabelText("Fork after saved message").hasAttribute("disabled")).toBe(true);
  view.rerender(<SessionFork key={child.id} session={child} sessions={[source, child]} onSelect={onSelect} onCreated={onCreated} />);
  await act(async () => { if (outcome === "resolve") complete(child); else fail(new Error("late failure")); });
  expect(fork.mock.calls[0][0].session_id).toBe(source.id);
  expect(onCreated).not.toHaveBeenCalled();
  expect(onSelect).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Fork session" })).toBeTruthy();
  expect(screen.queryByText("Fork created.")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
});

it.each(["resolve", "reject"])("ignores a preview %s after the source unmounts", async (outcome) => {
  let complete: (value: typeof preview) => void = () => { throw new Error("not pending"); };
  let fail: (error: Error) => void = () => { throw new Error("not pending"); };
  vi.spyOn(api, "previewSessionFork").mockImplementation(() => new Promise((resolve, reject) => { complete = resolve; fail = reject; }));
  const onCreated = vi.fn();
  const view = render(<SessionFork key={source.id} session={source} sessions={[source]} onSelect={vi.fn()} onCreated={onCreated} />);
  fireEvent.click(screen.getByRole("button", { name: "Fork session" }));
  view.rerender(<SessionFork key={child.id} session={child} sessions={[child]} onSelect={vi.fn()} onCreated={onCreated} />);
  await act(async () => { if (outcome === "resolve") complete(preview); else fail(new Error("late failure")); });
  expect(screen.getByRole("button", { name: "Fork session" })).toBeTruthy();
  expect(screen.queryByLabelText("Fork after saved message")).toBeNull();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(onCreated).not.toHaveBeenCalled();
});
