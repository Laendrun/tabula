// Copies the spec's JSON Schemas (spec/schemas/*.schema.json) into the extension's schemas/ folder, where
// package.json's jsonValidation points: the .vsix can only contain files of this folder. Run by `npm run build`
// (and so before packaging); the copies aren't in git, the spec's files are the only ones to edit.
const fs = require("fs");
const path = require("path");

const SPEC = path.join(__dirname, "..", "..", "..", "spec", "schemas");

function copySchemas(to = path.join(__dirname, "..", "schemas")) {
  const names = fs.readdirSync(SPEC).filter((f) => f.endsWith(".schema.json")).sort();
  if (!names.length) throw new Error(`no schemas in ${SPEC}`);
  fs.mkdirSync(to, { recursive: true });
  for (const name of names) fs.copyFileSync(path.join(SPEC, name), path.join(to, name));
  return names;
}

module.exports = { copySchemas, SPEC };

if (require.main === module) {
  const names = copySchemas();
  console.log(`schemas: copied ${names.join(", ")} from spec/schemas`);
}
