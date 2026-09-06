// =============================================================================
// JobTitleInput.jsx — a text input that suggests real Dragnet job titles.
//
// Backed by GET /api/v1/org-roles/job-titles (the distinct job titles across
// staff). Uses a native <datalist> so it autocompletes the real titles while
// still allowing free text when someone's title isn't in Entra yet. Drop-in
// replacement for a plain <input type="text">.
// =============================================================================

import { useId } from "react";
import { useJobTitles } from "../../hooks/useGrc.js";

export default function JobTitleInput({ value, onChange, placeholder, style }) {
  const { data: titles = [] } = useJobTitles();
  const listId = useId();
  return (
    <>
      <input
        type="text"
        list={listId}
        value={value ?? ""}
        onChange={onChange}
        placeholder={placeholder || "Start typing a job title…"}
        style={style}
      />
      <datalist id={listId}>
        {titles.map((t) => (
          <option key={t} value={t} />
        ))}
      </datalist>
    </>
  );
}
