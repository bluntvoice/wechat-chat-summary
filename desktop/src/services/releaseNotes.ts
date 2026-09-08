export type ReleaseNoteInline = { kind: "text" | "strong"; text: string };

export type ReleaseNoteBlock =
  | { kind: "heading"; level: number; content: ReleaseNoteInline[] }
  | { kind: "paragraph"; content: ReleaseNoteInline[] }
  | { kind: "unordered-list" | "ordered-list"; items: ReleaseNoteInline[][] };

export function parseReleaseNoteInline(value: string): ReleaseNoteInline[] {
  const parts: ReleaseNoteInline[] = [];
  const pattern = /\*\*([^*\n]+)\*\*/g;
  let offset = 0;
  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > offset) parts.push({ kind: "text", text: value.slice(offset, index) });
    parts.push({ kind: "strong", text: match[1] });
    offset = index + match[0].length;
  }
  if (offset < value.length) parts.push({ kind: "text", text: value.slice(offset) });
  return parts.length ? parts : [{ kind: "text", text: value }];
}

export function parseReleaseNotes(markdown: string): ReleaseNoteBlock[] {
  const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReleaseNoteBlock[] = [];
  let paragraph: string[] = [];
  let listKind: "unordered-list" | "ordered-list" | null = null;
  let listItems: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push({ kind: "paragraph", content: parseReleaseNoteInline(paragraph.join("\n")) });
    paragraph = [];
  };
  const flushList = () => {
    if (!listKind || !listItems.length) return;
    blocks.push({ kind: listKind, items: listItems.map(parseReleaseNoteInline) });
    listKind = null;
    listItems = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = /^(#{1,4})\s+(.+)$/.exec(line.trimStart());
    if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ kind: "heading", level: heading[1].length, content: parseReleaseNoteInline(heading[2].trim()) });
      continue;
    }
    const unordered = /^\s*[-*+]\s+(.+)$/.exec(line);
    const ordered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (unordered || ordered) {
      flushParagraph();
      const nextKind = unordered ? "unordered-list" : "ordered-list";
      if (listKind && listKind !== nextKind) flushList();
      listKind = nextKind;
      listItems.push((unordered?.[1] || ordered?.[1] || "").trim());
      continue;
    }
    if (listKind && listItems.length) {
      listItems[listItems.length - 1] += `\n${line.trim()}`;
    } else {
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}
