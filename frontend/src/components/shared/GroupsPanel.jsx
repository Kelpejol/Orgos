// =============================================================================
// GroupsPanel.jsx — manage OrgOS people groups (e.g. "Compliance Team").
//
// Compliance/Admin can create groups, add/remove people, and delete groups.
// A group's name is usable as an owner in documents/controls/evidence, so any
// member can act on it. Everyone can view; only Compliance/Admin can edit.
// =============================================================================

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useGroups } from "../../hooks/useGrc.js";
import { groupsApi } from "../../api/grcApi.js";
import { useCurrentUserRole } from "../../hooks/useCurrentUserRole.js";
import UserSearchField from "./UserSearchField.jsx";
import { LoadingState, ErrorState, EmptyState } from "./LoadingState.jsx";
import { useAlert } from "./AlertModal.jsx";

const btn = (bg, fg = "#fff", bd = "none") => ({
  padding: "8px 14px", fontSize: 12, fontWeight: 600, borderRadius: 8,
  border: bd, background: bg, color: fg, cursor: "pointer",
});

function MemberChip({ m, onRemove }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11.5,
      background: "var(--color-background-secondary)", border: "1px solid var(--color-border-tertiary)",
      borderRadius: 20, padding: "3px 6px 3px 10px" }}>
      {m.display_name || m.email || m.oid}
      {onRemove && (
        <button onClick={onRemove} title="Remove"
          style={{ border: "none", background: "transparent", cursor: "pointer",
            color: "var(--color-text-tertiary)", fontSize: 14, lineHeight: 1, padding: 0 }}>×</button>
      )}
    </span>
  );
}

function GroupCard({ group, canEdit }) {
  const qc = useQueryClient();
  const { notify } = useAlert();
  const [busy, setBusy] = useState(false);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["groups"] }); qc.invalidateQueries({ queryKey: ["group-names"] }); };

  const addMember = async (user) => {
    if (!user) return;
    setBusy(true);
    try { await groupsApi.addMembers(group.id, [user]); refresh(); }
    catch (e) { notify({ tone: "danger", title: "Add failed", message: e.response?.data?.detail || e.message }); }
    finally { setBusy(false); }
  };
  const removeMember = async (oid) => {
    setBusy(true);
    try { await groupsApi.removeMember(group.id, oid); refresh(); }
    catch (e) { notify({ tone: "danger", title: "Remove failed", message: e.response?.data?.detail || e.message }); }
    finally { setBusy(false); }
  };
  const del = async () => {
    if (!window.confirm(`Delete the group "${group.name}"? Documents referencing it keep the name but it won't be a live group.`)) return;
    setBusy(true);
    try { await groupsApi.remove(group.id); refresh(); notify({ tone: "success", title: "Group deleted", message: group.name }); }
    catch (e) { notify({ tone: "danger", title: "Delete failed", message: e.response?.data?.detail || e.message }); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ border: "1px solid var(--color-border-tertiary)", borderRadius: 12, padding: "14px 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700 }}>{group.name}</div>
          {group.description && (
            <div style={{ fontSize: 12, color: "var(--color-text-secondary)", marginTop: 2 }}>{group.description}</div>
          )}
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 3 }}>
            {group.member_count} member{group.member_count === 1 ? "" : "s"}
            {group.category ? ` · ${group.category}` : ""}
          </div>
        </div>
        {canEdit && (
          <button onClick={del} disabled={busy} style={{ ...btn("transparent", "#A32D2D", "1.5px solid #F09595"), padding: "6px 12px" }}>
            Delete
          </button>
        )}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
        {group.members.length === 0 && (
          <span style={{ fontSize: 12, color: "var(--color-text-tertiary)" }}>No members yet.</span>
        )}
        {group.members.map((m) => (
          <MemberChip key={m.oid} m={m} onRemove={canEdit ? () => removeMember(m.oid) : null} />
        ))}
      </div>

      {canEdit && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: 4 }}>
            Add someone
          </div>
          <UserSearchField onSelect={addMember} placeholder="Type a name or email to add…" />
        </div>
      )}
    </div>
  );
}

function CreateGroupForm({ onDone }) {
  const qc = useQueryClient();
  const { notify } = useAlert();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [members, setMembers] = useState([]);
  const [busy, setBusy] = useState(false);

  const inputStyle = { width: "100%", padding: "8px 10px", fontSize: 13, borderRadius: 8,
    border: "1.5px solid var(--color-border-tertiary)", boxSizing: "border-box",
    background: "var(--color-background-primary)", color: "var(--color-text-primary)" };

  const addMember = (u) => { if (u && !members.some((m) => m.oid === u.oid)) setMembers([...members, u]); };
  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await groupsApi.create({ name: name.trim(), description, category, members });
      qc.invalidateQueries({ queryKey: ["groups"] });
      qc.invalidateQueries({ queryKey: ["group-names"] });
      notify({ tone: "success", title: "Group created", message: name.trim() });
      onDone();
    } catch (e) {
      notify({ tone: "danger", title: "Create failed", message: e.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  return (
    <div style={{ border: "1px solid var(--color-border-tertiary)", borderRadius: 12, padding: 16, marginBottom: 14,
      background: "var(--color-background-secondary)" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10 }}>New group</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Group name (used in documents, e.g. Compliance Team)" style={inputStyle} />
        <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description (optional)" style={inputStyle} />
        <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Category (optional, e.g. Compliance, Ops)" style={inputStyle} />
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)", marginBottom: 4 }}>Members</div>
          {members.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
              {members.map((m) => (
                <MemberChip key={m.oid} m={m} onRemove={() => setMembers(members.filter((x) => x.oid !== m.oid))} />
              ))}
            </div>
          )}
          <UserSearchField onSelect={addMember} placeholder="Add people to this group…" />
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={create} disabled={busy || !name.trim()}
          style={btn(!name.trim() ? "#C9CCD1" : "#085041")}>{busy ? "Creating…" : "Create group"}</button>
        <button onClick={onDone} style={btn("transparent", "var(--color-text-secondary)", "1.5px solid var(--color-border-tertiary)")}>Cancel</button>
      </div>
    </div>
  );
}

export default function GroupsPanel() {
  const { isCompliance } = useCurrentUserRole();
  const { data: groups = [], isLoading, error, refetch } = useGroups();
  const [creating, setCreating] = useState(false);

  const notProvisioned = error && (error.response?.status === 503 || /not exist|provision/i.test(error.message || ""));

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, gap: 12 }}>
        <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>
          Groups classify people (e.g. a Compliance Team). Use a group name as an owner in a document and any member can act on it.
        </div>
        {isCompliance && !creating && !notProvisioned && (
          <button onClick={() => setCreating(true)} style={btn("var(--color-text-primary)", "var(--color-background-primary)")}>
            + New group
          </button>
        )}
      </div>

      {creating && <CreateGroupForm onDone={() => setCreating(false)} />}

      {isLoading && <LoadingState message="Loading groups…" />}

      {notProvisioned && (
        <div style={{ fontSize: 12.5, color: "#8A5A00", background: "#FDF3E2", border: "1px solid #F0CE94",
          borderRadius: 10, padding: "12px 14px", lineHeight: 1.6 }}>
          <b>Groups aren't set up yet.</b> An admin needs to create a SharePoint list named exactly
          <b> “OrgOS Groups”</b> in the OrgOS site once (OrgOS can't create lists itself). The columns
          are added automatically after that — then groups work here with no further setup.
        </div>
      )}

      {error && !notProvisioned && <ErrorState error={error} onRetry={refetch} />}

      {!isLoading && !error && groups.length === 0 && (
        <EmptyState message={isCompliance ? "No groups yet. Create one to get started." : "No groups have been created yet."} />
      )}

      {groups.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {groups.map((g) => <GroupCard key={g.id} group={g} canEdit={isCompliance} />)}
        </div>
      )}
    </div>
  );
}
