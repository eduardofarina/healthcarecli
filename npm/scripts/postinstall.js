#!/usr/bin/env node
/**
 * postinstall.js — install the Python healthcarecli package via pip.
 * Runs automatically after `npm install -g healthcarecli`.
 */

const { execSync, spawnSync } = require("child_process");

function run(cmd, args) {
  const result = spawnSync(cmd, args, { stdio: "inherit" });
  return result.status === 0;
}

// Resolve the right python / pip command for this platform
function findPython() {
  for (const cmd of ["python3", "python"]) {
    const r = spawnSync(cmd, ["--version"], { stdio: "pipe" });
    if (r.status === 0) {
      const version = (r.stdout || r.stderr).toString().trim();
      const match = version.match(/Python (\d+)\.(\d+)/);
      if (match && (parseInt(match[1]) > 3 || (parseInt(match[1]) === 3 && parseInt(match[2]) >= 10))) {
        return cmd;
      }
    }
  }
  return null;
}

const python = findPython();

if (!python) {
  console.error(
    "\n[healthcarecli] Python 3.10+ is required but was not found.\n" +
    "Install Python from https://python.org and re-run: npm install -g healthcarecli\n"
  );
  process.exit(1);
}

console.log(`\n[healthcarecli] Installing Python package via pip (using ${python})...\n`);

const pipOk = run(python, ["-m", "pip", "install", "--upgrade", "healthcarecli"]);

if (!pipOk) {
  console.error(
    "\n[healthcarecli] pip install failed. Try manually:\n" +
    `  ${python} -m pip install healthcarecli\n`
  );
  process.exit(1);
}

console.log("\n[healthcarecli] Installation complete. Run: healthcarecli --help\n");
