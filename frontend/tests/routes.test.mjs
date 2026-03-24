import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(process.cwd());

function exists(relPath) {
  return fs.existsSync(path.join(ROOT, relPath));
}

test("core routes exist", () => {
  assert.equal(exists("src/app/page.tsx"), true);
  assert.equal(exists("src/app/dashboard"), true);
  assert.equal(exists("src/app/login"), true);
  assert.equal(exists("src/app/settings"), true);
});

test("frontend services resolve from env or browser origin without hardcoded localhost", () => {
  const apiService = fs.readFileSync(
    path.join(ROOT, "src/services/api.ts"),
    "utf-8",
  );
  const wsService = fs.readFileSync(
    path.join(ROOT, "src/services/websocket.ts"),
    "utf-8",
  );

  assert.match(apiService, /NEXT_PUBLIC_API_URL/);
  assert.match(apiService, /window\.location/);
  assert.doesNotMatch(apiService, /127\.0\.0\.1:8080|localhost:8080/);

  assert.match(wsService, /NEXT_PUBLIC_WS_URL/);
  assert.match(wsService, /NEXT_PUBLIC_API_URL/);
  assert.match(wsService, /window\.location/);
  assert.doesNotMatch(wsService, /127\.0\.0\.1:8080|localhost:8080/);
});
