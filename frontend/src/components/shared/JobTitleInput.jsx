// =============================================================================
// JobTitleInput.jsx — a text input that suggests real owners for a control:
// Dragnet job titles AND OrgOS groups (e.g. "Compliance Team").
//
// Backed by GET /api/v1/org-roles/job-titles and GET /api/v1/groups/names.
// Uses a native <datalist> so it autocompletes real titles/groups while still
// allowing free text. Groups are listed first and labelled "(group)" so the
// reviewer can tell them apart; the saved value is the plain name.
// =============================================================================

import { useId } from "react";
import { useJobTitles, useGroupNames } from "../../hooks/useGrc.js";

export default function JobTitleInput({ value, onChange, placeholder, style }) {
  const { data: titles = [] } = useJobTitles();
  const { data: groups = [] } = useGroupNames();
  const listId = useId();
  return (
    <>
      <input
        type="text"
        list={listId}
        value={value ?? ""}
        onChange={onChange}
        placeholder={placeholder || "Start typing a job title or group…"}
        style={style}
      />
      <datalist id={listId}>
        {groups.map((g) => (
          <option key={`g-${g}`} value={g} label={`${g} (group)`} />
        ))}
        {titles.map((t) => (
          <option key={`t-${t}`} value={t} />
        ))}
      </datalist>
    </>
  );
}
