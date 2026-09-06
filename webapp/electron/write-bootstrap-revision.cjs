"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

// beforePack also covers direct electron-builder invocations outside npm scripts.
function writeBootstrapRevision(context) {
  const appDir = context.appDir || context.packager.appDir;
  const git = (...args) => execFileSync("git", ["-C", appDir, ...args], { encoding: "utf8" }).trim();
  if (git("status", "--porcelain", "--untracked-files=all")) {
    throw new Error("Cannot package an exact source revision from a dirty checkout. Commit or move changes, then rebuild.");
  }
  const revision = git("rev-parse", "HEAD");
  const tree = git("rev-parse", "HEAD^{tree}");
  const { version } = JSON.parse(fs.readFileSync(path.join(appDir, "package.json"), "utf8"));
  const metadata = { schema: 1, repo: "https://github.com/professorpalmer/marionette.git", revision, tree, version };
  fs.writeFileSync(path.join(appDir, "electron", "bootstrap-revision.json"), JSON.stringify(metadata, null, 2) + "\n");
  return metadata;
}
module.exports = writeBootstrapRevision;
