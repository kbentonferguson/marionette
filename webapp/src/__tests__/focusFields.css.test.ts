import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

it("keeps the accent focus box off text fields", () => {
  const css = readFileSync(resolve(__dirname, "../index.css"), "utf8");
  expect(css).toContain("Text fields keep caret + border");
  expect(css).toMatch(
    /:where\(button, a\[href\], summary, \[tabindex\]:not\(input\):not\(select\):not\(textarea\):not\(\[contenteditable="true"\]\)\)/,
  );
  expect(css).not.toMatch(
    /:where\(button, a\[href\], input, select, textarea, summary, \[tabindex\], \[contenteditable="true"\]\):focus-visible/,
  );
  expect(css).toMatch(
    /:where\(input, select, textarea, \[contenteditable="true"\]\):focus-visible \{[\s\S]*outline-width: 0;/,
  );
});
