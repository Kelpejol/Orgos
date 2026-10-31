// =============================================================================
// JobTitleInput.jsx — a role field: suggestions come from Org Roles only.
//
// Org Roles is the role register. A Microsoft job title is never a role, so it is
// never suggested here. Free text is still allowed (a document may need a role
// that is about to be created), but anything that is not in Org Roles is said so
// under the field, and the role check (V07) flags it on the document.
//
// Backed by GET /api/v1/groups/names. (The file keeps its old name so every
// screen that uses it changes at once.)
// =============================================================================

import { useId } from "react";
import { useGroupNames } from "../../hooks/useGrc.js";

const norm = (t) => (t || "").toLowerCase().replace(/[&/]/g, " and ").replace(/[^a-z0-9 ]+/g, " ")
  .split(/\s+/).filter(Boolean).join(" ");

export default function JobTitleInput({ value, onChange, placeholder, style }) {
  const { data: roles = [], isSuccess } = useGroupNames();
  const listId = useId();
  const typed = (value ?? "").trim();
  const known = !typed || roles.some((r) => norm(r) === norm(typed));
  return (
    <>
      <input
        type="text"
        list={listId}
        value={value ?? ""}
        onChange={onChange}
        placeholder={placeholder || "Choose a role in Org Roles…"}
        style={style}
      />
      <datalist id={listId}>
        {roles.map((r) => <option key={r} value={r} />)}
      </datalist>
      {isSuccess && !known && (
        <div style={{ fontSize: 11, color: "#8A5A00", marginTop: 3 }}>
          “{typed}” is not a role in Org Roles. Choose one from the list, or create it in Org Roles first.
        </div>
      )}
    </>
  );
}
