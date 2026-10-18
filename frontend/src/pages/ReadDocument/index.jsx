// =============================================================================
// ReadDocument — a standalone page that just shows a document.
//
// A Teams notification links straight to the file in SharePoint, which opens
// Word for the web with the reader's own rights. At Dragnet that usually means
// EDIT, so someone asked to review a document can change the controlled source
// by typing in it, and the change never meets the CDI check an upload runs.
//
// Power Automate points at THIS page instead: /read/{lifecycle item id}. It
// shows the document as a PDF, which cannot be edited at all.
// =============================================================================

import { useParams } from "react-router-dom";

import DocumentViewer from "../../components/shared/DocumentViewer.jsx";

export default function ReadDocument() {
  const { id } = useParams();
  return (
    <DocumentViewer
      doc={{ id, Title: "Document" }}
      // Nowhere to go back to — this page IS the document.
      onClose={() => window.close()}
    />
  );
}
