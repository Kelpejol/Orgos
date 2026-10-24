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
  const legacy = render(ChainPreview, { item: { ProposedOwnerRole: "Review Lead" } });
  assert.match(legacy, /Control owner: Review Lead/);
  assert.match(legacy, /No record entry/);
});
