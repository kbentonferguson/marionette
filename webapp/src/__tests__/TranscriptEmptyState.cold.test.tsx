import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TranscriptEmptyState from "../components/conversation/TranscriptEmptyState";

describe("TranscriptEmptyState cold miss", () => {
  it("keeps cold loading visually silent", () => {
    render(<TranscriptEmptyState transcriptStale itemCount={0} />);
    expect(screen.queryByText(/Loading session/i)).toBeNull();
    expect(screen.queryByText(/Message the pilot/)).toBeNull();
    expect(screen.getByRole("status", { name: "Loading session" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });
});
