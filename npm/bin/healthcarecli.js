#!/usr/bin/env node
/**
 * healthcarecli.js — thin shim that delegates to the Python CLI.
 *
 * Resolution order:
 *   1. `healthcarecli` console_script (installed by pip into PATH)
 *   2. `python -m healthcarecli` (always works if pip package is installed)
 */

const { spawnSync } = require("child_process");

const args = process.argv.slice(2);

// Try the console_script first (fastest path, works when pip scripts are on PATH)
function tryDirect() {
  const cmd = process.platform === "win32" ? "healthcarecli.exe" : "healthcarecli";
  // Avoid recursive self-call: only use if it resolves to a different binary
  const which = spawnSync(process.platform === "win32" ? "where" : "which", [cmd], {
    stdio: "pipe",
  });
  if (which.status !== 0) return false;

  const resolved = (which.stdout || "").toString().trim().split("\n")[0];
  // If the resolved path is this script, skip to avoid infinite loop
  if (resolved && !resolved.includes("node_modules")) {
    const r = spawnSync(resolved, args, { stdio: "inherit", shell: false });
    process.exit(r.status ?? 0);
  }
  return false;
}

// Fall back to python -m healthcarecli
function viaPython() {
  for (const py of ["python3", "python"]) {
    const check = spawnSync(py, ["--version"], { stdio: "pipe" });
    if (check.status === 0) {
      const r = spawnSync(py, ["-m", "healthcarecli", ...args], {
        stdio: "inherit",
        shell: false,
      });
      process.exit(r.status ?? 0);
    }
  }

  console.error(
    "[healthcarecli] Python not found. Re-install with: npm install -g healthcarecli"
  );
  process.exit(1);
}

tryDirect();
viaPython();
