import { readFileSync, readdirSync } from "node:fs";
import { Script } from "node:vm";

// Reproduce the ordinary-function wrapper observed in Fudan WebVPN.
// This catches top-level await, import/export and import.meta in built JS.
function check(directory) {
  let count = 0;
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = `${directory}/${entry.name}`;
    if (entry.isDirectory()) count += check(path);
    else if (/\.(?:js|mjs)$/.test(entry.name)) {
      const source = readFileSync(path, "utf8");
      new Script(`vpn_eval((function(){\n${source}\n}).toString().slice(12,-2), "");`, {
        filename: path,
      });
      count++;
    }
  }
  return count;
}
const count = check("dist");
if (!count) throw new Error("No built JavaScript found");
console.log(`WebVPN wrapper syntax passed for ${count} built script(s).`);
