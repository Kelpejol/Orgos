// =============================================================================
// JobTitleInput.jsx — owner-name suggestions from Org Roles and the legacy
// directory-title source. A directory title alone is not a registered role.
//
// Backed by GET /api/v1/org-roles/job-titles and GET /api/v1/groups/names.
// Uses a native <datalist> with free text. Org Roles entries are listed first;
// directory suggestions are labelled as such. The saved value is the plain name.
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
        placeholder={placeholder || "Enter a role in Org Roles…"}
        style={style}
      />
      <datalist id={listId}>
        {groups.map((g) => (
          <option key={`g-${g}`} value={g} label={`${g} (role)`} />
        ))}
        {titles.map((t) => (
          <option key={`t-${t}`} value={t} label={`${t} (directory title; verify in Org Roles)`} />
        ))}
      </datalist>
    </>
  );
}
