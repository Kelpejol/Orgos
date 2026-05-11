// =============================================================================
// components/shared/StatusBadge.jsx
// Colour-coded badges for every status value used across OrgOS.
// Extracted directly from the approved prototype — colours are non-negotiable.
// =============================================================================

const SC = {
  Overdue: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  "Due Soon": { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  "Due soon": { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Upcoming: { bg: "#F1EFE8", tx: "#444441", bd: "#B4B2A9" },
  Assigned: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Unassigned: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Active: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Expired: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  "Expiring Soon": { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  "Expiring soon": { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Accepted: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Submitted: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  "Under Review": { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },
  "Under review": { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },
  Rejected: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Covered: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Partial: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  "Not covered": { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Open: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  "In progress": { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Resolved: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Critical: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Major: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Minor: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  Preventive: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  Detective: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Corrective: { bg: "#FAECE7", tx: "#712B13", bd: "#F0997B" },
  Directive: { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },
  Extraction: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  Orphan: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Harmonisation: { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },
  Superseded: { bg: "#F1EFE8", tx: "#444441", bd: "#B4B2A9" },
  Withdrawn: { bg: "#F1EFE8", tx: "#444441", bd: "#B4B2A9" },
  Policy: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  Procedure: { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },
  SOP: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Statutory: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  Certification: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Licensing: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Regulatory: { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },
  // Document types
  JobDescription: { bg: "#F0F4E8", tx: "#3A5A0C", bd: "#A8C87A" },
  Contract: { bg: "#FDF0E0", tx: "#7A4A00", bd: "#F0B860" },
  Audit: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  // Review statuses
  "Pending Review": { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  "Edited and Accepted": { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },
  Routed: { bg: "#E6F1FB", tx: "#0C447C", bd: "#85B7EB" },
  "False Positive": { bg: "#F1EFE8", tx: "#595952", bd: "#B4B2A9" },
  "Second Review Requested": { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },

  // Lifecycle stages
  Review: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  Sensitisation: { bg: "#FAECE7", tx: "#D85A30", bd: "#F0997B" },
  Approval: { bg: "#FBEAF0", tx: "#993556", bd: "#E8A0BD" },
  "AI draft": { bg: "#EEEDFE", tx: "#3C3489", bd: "#AFA9EC" },
  Revised: { bg: "#E1F5EE", tx: "#085041", bd: "#5DCAA5" },

  // Gap types
  EvidenceGap: { bg: "#FAEEDA", tx: "#633806", bd: "#FAC775" },
  ControlGap: { bg: "#FCEBEB", tx: "#791F1F", bd: "#F09595" },
  ProcessGap: { bg: "#FDF0E0", tx: "#7A4A00", bd: "#F0B860" },
};

const FALLBACK = { bg: "#F1EFE8", tx: "#444441", bd: "#B4B2A9" };

/**
 * Colour-coded status badge.
 * @param {{ label: string, small?: boolean }} props
 */
export default function StatusBadge({ label, small = false }) {
  if (!label) return null;
  const s = SC[label] || FALLBACK;
  return (
    <span
      style={{
        fontSize: small ? 9 : 10,
        padding: small ? "1px 5px" : "1px 6px",
        borderRadius: 3,
        background: s.bg,
        color: s.tx,
        border: `0.5px solid ${s.bd}`,
        whiteSpace: "nowrap",
        fontWeight: 500,
      }}
    >
      {label}
    </span>
  );
}
