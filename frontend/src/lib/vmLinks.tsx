/** Turn VM names mentioned in text (recommendations, AI answers, digests) into links to that VM. */
import { useLiveQuery } from "dexie-react-hooks";
import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useDb } from "../auth/AuthProvider";

export interface VmIndex {
  byName: Map<string, string>; // name -> resource id
  pattern: RegExp | null; // matches any known name as a whole word
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function buildVmIndex(vms: { id: string; name: string }[]): VmIndex {
  const byName = new Map(vms.map((v) => [v.name, v.id]));
  const names = [...byName.keys()].filter(Boolean).sort((a, b) => b.length - a.length).map(escape);
  // names like "api-001" contain dashes, so \b is not enough: no word char or dash on either side
  const pattern = names.length ? new RegExp(`(?<![\\w-])(${names.join("|")})(?![\\w-])`, "g") : null;
  return { byName, pattern };
}

export function useVmIndex(): VmIndex {
  const db = useDb();
  const vms = useLiveQuery(() => db.resources.toArray(), [db]);
  return buildVmIndex(vms ?? []);
}

export function VmText({ text, index }: { text: string; index: VmIndex }) {
  if (!index.pattern) return <>{text}</>;
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(index.pattern)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const id = index.byName.get(m[0]);
    out.push(
      <Link key={at} className="link font-medium" to={`/resources/${id}`}>
        {m[0]}
      </Link>,
    );
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out.map((n, i) => <Fragment key={i}>{n}</Fragment>)}</>;
}

/** Markdown version: link names in plain text, leave code spans and fenced code untouched. */
export function linkifyMarkdown(md: string, index: VmIndex): string {
  if (!index.pattern) return md;
  return md
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part.replace(index.pattern!, (name) => `[${name}](/resources/${index.byName.get(name)})`),
    )
    .join("");
}
