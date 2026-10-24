import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const stubs = {
  hooks: `export const useJobTitles = () => ({data: ["Directory Example"]});
    export const useGroupNames = () => ({data: ["Registered Example"]});`,
  query: `export const useQuery = () => ({});
    export const useMutation = () => ({});
    export const useQueryClient = () => ({invalidateQueries() {}});`,
  api: `export default {};`,
  alert: `export const useAlert = () => ({notify() {}});`,
  user: `export const useCurrentUserRole = () => ({isCompliance: true});`,
};

async function component(path, extraExports = []) {
  const entry = fileURLToPath(new URL(`../src/${path}`, import.meta.url));
  const result = await build({
    entryPoints: [entry], bundle: true, write: false, platform: "node", format: "cjs",
    packages: "external", jsx: "automatic", logLevel: "silent", define: { "import.meta.env": "{}" },
    plugins: [{
      name: "isolated-role-wording-test",
      setup(build) {
        for (const [filter, path] of [
          [/useGrc\.js$/, "hooks"], [/^@tanstack\/react-query$/, "query"],
          [/grcApi\.js$/, "api"], [/AlertModal\.jsx$/, "alert"],
          [/useCurrentUserRole\.js$/, "user"],
        ]) build.onResolve({ filter }, () => ({ path, namespace: "stub" }));
        build.onLoad({ filter: /.*/, namespace: "stub" }, args => ({ contents: stubs[args.path] }));
        build.onLoad({ filter: /\.jsx$/ }, async args => {
          if (args.path !== entry || !extraExports.length) return;
          return { contents: `${await readFile(entry, "utf8")}\nexport {${extraExports.join(",")}};`, loader: "jsx" };
        });
      },
    }],
  });
  const module = { exports: {} };
  new Function("module", "exports", "require", result.outputFiles[0].text)(module, module.exports, require);
  return module.exports;
}

const render = (Component, props) => renderToStaticMarkup(createElement(Component, props));

test("role input distinguishes registered roles from unchanged directory suggestions", async () => {
  const { default: Input } = await component("components/shared/JobTitleInput.jsx");
  const html = render(Input, { value: "", onChange() {} });
  assert.match(html, /Enter a role in Org Roles/);
  assert.match(html, /Registered Example \(role\)/);
  assert.match(html, /Directory Example \(directory title; verify in Org Roles\)/);
  assert.equal((html.match(/<option /g) || []).length, 2);
});

test("unresolved owner guidance points to Org Roles without asserting a directory title is authority", async () => {
  const { default: Owner } = await component("components/shared/OwnerDisplay.jsx");
  const html = render(Owner, { item: { OwnerRole: "Example Lead", OwnerKind: "unresolved" } });
  assert.match(html, /Check this role in Org Roles and assign the people who hold it/);
  assert.doesNotMatch(html, /set a real job title/);
});

test("ambiguous legacy definition explains the source-document fix and keeps the original value", async () => {
  const { DefinitionPanel } = await component("components/shared/ControlDefinitionReview.jsx");
  const html = render(DefinitionPanel, { item: { Candidate: {
    responsibility_as_written: "Review Lead / Operations Lead", responsibility_ambiguous: true,
  } } });
  assert.match(html, /Review Lead \/ Operations Lead/);
  assert.match(html, /one Control owner from Org Roles/);
  assert.match(html, /records it as Blocked/);
  assert.doesNotMatch(html, /Role Catalogue/);
});

test("legacy definition keeps both historical responsibility fields and the separate record custodian", async () => {
  const { default: View } = await component("pages/ControlRegister/ControlDefinitionView.jsx");
  const html = render(View, { control: {
    id: "example", ControlId: "SWEEP-01", OwnerRole: "Review Lead", Status: "Active",
    Definition: { accountable: "Review Lead", executing: "Operations Lead", requirement: "Review access." },
    Records: [{ record_id: "REC-0001", catalogue: "governed", name: "Review record", custodian: "Records Custodian" }],
  }, onBack() {} });
  assert.match(html, /Accountable \(older form\)/);
  assert.match(html, /Executing \(older form\)/);
  assert.match(html, /Kept by Records Custodian/);
});

test("extraction chain preview names the Control owner and preserves definition versus legacy evidence wording", async () => {
  const { ChainPreview } = await component("pages/ExtractionReview/index.jsx", ["ChainPreview"]);
  const definition = render(ChainPreview, { item: { ControlId: "SWEEP-01", Candidate: { evidence: [{ record_id: "REC-0001" }] } } });
  assert.match(definition, /Control owner is recognised/);
  assert.match(definition, /an obligation for REC-0001/);
  const legacy = render(ChainPreview, { item: { ProposedOwnerRole: "Review Lead", AcceptPreview: {
    creates: [{ register: "Control Register", detail: "Control owner: Review Lead" }],
    warnings: ["No Record Tracker entry will be created."],
  } } });
  assert.match(legacy, /Control owner: Review Lead/);
  assert.match(legacy, /No Record Tracker entry/);
});

test("evidence chain renders the backend plan even when the description is empty", async () => {
  const { ChainPreview } = await component("pages/ExtractionReview/index.jsx", ["ChainPreview"]);
  const html = render(ChainPreview, { item: { EvidenceType: "Review", EvidenceDescription: "", AcceptPreview: {
    creates: [{ register: "Record Tracker", detail: "Review record — Evidence for: Review access, status: Pending" }],
    warnings: [],
  } } });
  assert.match(html, /Record Tracker/);
  assert.match(html, /Evidence for: Review access/);
  assert.doesNotMatch(html, /No record entry/);
});

const refused = {
  id: "TST-01", ControlId: "TST-01", ItemType: "Extraction", ChangeKind: "New",
  SourceDocumentCode: "DRG-ISMS-STD-TST", ReviewStatus: "Pending Review",
  AcceptanceRefusal: "Control TST-01 writes Control owner: Review Lead; Operations Lead. The document author must revise the document to name exactly one role.",
};

for (const [path, name] of [["pages/ExtractionReview/index.jsx", "ExtractionCard"], ["pages/AIReviewQueue/index.jsx", "QueueCard"]]) {
  test(`${name} shows the refusal before expanding the card`, async () => {
    const module = await component(path, [name]);
    const html = render(module[name], { item: refused, isCompliance: true });
    assert.match(html, /role="alert"/);
    assert.match(html, /TST-01 writes Control owner/);
    assert.match(html, /document author must revise/);
  });
  test(`${name} disables Accept and explains the refusal`, async () => {
    const { DecisionPanel } = await component(path, ["DecisionPanel"]);
    const html = render(DecisionPanel, { item: refused });
    assert.match(html, /<button[^>]*disabled=""[^>]*title="Control TST-01 writes Control owner/);
    assert.match(html, /Reject/);
  });
}

test("bulk review displays refusal reasons and offers only eligible controls", async () => {
  const { DocumentBatches } = await component("components/shared/ControlDefinitionReview.jsx");
  let html = render(DocumentBatches, { items: [refused, { ...refused, id: "TST-02", ControlId: "TST-02", AcceptanceRefusal: "" }] });
  assert.match(html, /Accept 1 eligible/);
  assert.match(html, /document author must revise/);
  html = render(DocumentBatches, { items: [refused] });
  assert.match(html, /<button disabled="" title="All controls require a document revision/);
});

test("assignment role spelling link opens the existing document flow with its source code", async () => {
  const { RoleDocumentLink } = await component("pages/AssignmentOwnership/index.jsx");
  const html = render(RoleDocumentLink, { item: { SourceDocumentCode: "DRG-ISMS-STD-TST" } });
  assert.match(html, /Use this role/);
  assert.match(html, /Create role/);
  assert.match(html, /Fix CDI issues/);
  assert.doesNotMatch(html, /Add person|Grant membership/);
  const element = RoleDocumentLink({ item: { SourceDocumentCode: "DRG-ISMS-STD-TST" } });
  const button = element.props.children.find(child => child?.type === "button");
  const previousWindow = globalThis.window, previousEvent = globalThis.CustomEvent;
  let event;
  try {
    globalThis.window = { dispatchEvent(value) { event = value; } };
    globalThis.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options.detail; } };
    button.props.onClick();
    assert.equal(event.type, "orgos:navigate");
    assert.deepEqual(event.detail, { to: "lifecycle", documentCode: "DRG-ISMS-STD-TST" });
  } finally {
    globalThis.window = previousWindow;
    globalThis.CustomEvent = previousEvent;
  }
});

test("assignment keeps document-gap, JD, conflict and library decisions", async () => {
  const module = await component("pages/AssignmentOwnership/index.jsx", ["JDToDocDecisions", "DocToJDDecisions", "ConflictDecisions", "LIBRARY_FINDINGS"]);
  assert.ok(module.JDToDocDecisions.some(d => d.key === "Create new document"));
  assert.ok(module.DocToJDDecisions.some(d => d.key === "Add to existing JD"));
  assert.ok(module.ConflictDecisions.some(d => d.key === "Select governing document"));
  assert.equal(Object.keys(module.LIBRARY_FINDINGS).length, 5);
});

test("document role link retains the source code and explains how to revise an absent document", async () => {
  const { default: Lifecycle } = await component("pages/DocumentLifecycle/index.jsx");
  const html = render(Lifecycle, { focusDocumentCode: "DRG-ISMS-STD-TST", onClearFocus() {} });
  assert.match(html, /DRG-ISMS-STD-TST/);
  assert.match(html, /Use this role/);
  assert.match(html, /Fix CDI issues/);
  assert.match(html, /no lifecycle entry here/);
  assert.match(html, /Show all documents/);
});
