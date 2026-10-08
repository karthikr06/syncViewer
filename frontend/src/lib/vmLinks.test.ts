import { describe, expect, it } from "vitest";
import { buildVmIndex, linkifyMarkdown } from "./vmLinks";

const vms = buildVmIndex([
  { id: "1", name: "db-003" },
  { id: "2", name: "db-0031" },
  { id: "3", name: "web-1" },
]);

describe("linkifyMarkdown", () => {
  it("links whole VM names only", () => {
    expect(linkifyMarkdown("db-003 is down; db-0031 is fine", vms)).toBe(
      "[db-003](/resources/1) is down; [db-0031](/resources/2) is fine",
    );
    expect(linkifyMarkdown("xdb-003 and db-003x and my-web-1", vms)).toBe(
      "xdb-003 and db-003x and my-web-1",
    );
  });

  it("leaves code spans and fenced code alone", () => {
    expect(linkifyMarkdown("`db-003` and web-1", vms)).toBe("`db-003` and [web-1](/resources/3)");
    expect(linkifyMarkdown("```\ndb-003\n```", vms)).toBe("```\ndb-003\n```");
  });

  it("works with no VMs", () => {
    expect(linkifyMarkdown("db-003", buildVmIndex([]))).toBe("db-003");
  });
});
