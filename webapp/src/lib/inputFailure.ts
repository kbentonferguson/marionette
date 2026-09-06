/** User-facing recovery copy; never expose error bodies or backend paths. */
export function inputFailureMessage(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const body = "body" in error ? error.body : error;
  if (!body || typeof body !== "object" || !("code" in body) || typeof body.code !== "string") return null;
  switch (body.code) {
    case "input_stopped":
      return "Stop cancelled this input. Inspect Saved inputs and your draft before sending again.";
    case "input_session_changed":
      return "The active session changed. Return to the intended session and review your draft before sending.";
    case "input_stash_expired":
      return "Input staging expired. Review your draft and send it again.";
    case "input_attachment_limit":
      return "Attachment limits exceeded. Reduce the attachments in your draft before sending.";
    case "input_invalid":
    case "input_attachment_invalid":
      return "The input could not be accepted. Check your draft and attachments before sending.";
    case "input_commit_uncertain":
    case "input_delivery_uncertain":
    case "input_stop_uncertain":
    case "input_publication_conflict":
      return "Input delivery could not be confirmed. Inspect Saved inputs and your draft before sending again.";
    case "input_held":
    case "input_already_attempted":
    case "input_handoff_conflict":
    case "input_terminal":
      return "This input is held or has already been attempted. Inspect Saved inputs; copying an original creates a new draft.";
    case "input_retry_conflict":
    case "input_id_conflict":
      return "This input identity belongs to a different submission. Inspect Saved inputs before creating a new draft.";
    default:
      return body.code.startsWith("input_")
        ? "The input needs review. Inspect Saved inputs and your draft before sending again."
        : null;
  }
}
