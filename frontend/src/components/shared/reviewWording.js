// Display wording only: persisted review statuses and decision values stay unchanged.
export function reviewOutcomeLabel(status, decision) {
  if (status === "Accepted") {
    return decision === "Edit and Accept" ? "Accepted after edits" : "Accepted";
  }
  return [status, decision].filter(Boolean).join(" — ");
}
