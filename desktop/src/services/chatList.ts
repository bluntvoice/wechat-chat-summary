import type { Chat } from "../types/desktop";

export type ChatListFilter = "all" | "summarized";

const chatNameCollator = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});

/** 按 SQLite 返回的 chat_id 集合派生筛选与稳定排序，不依赖群名称。 */
export function filterAndSortChats(
  chats: Chat[],
  summarizedChatIds: Iterable<string>,
  query = "",
  filter: ChatListFilter = "all",
) {
  const summarized = new Set(summarizedChatIds);
  const needle = query.trim().toLocaleLowerCase("zh-CN");
  return chats
    .filter((chat) => filter === "all" || summarized.has(chat.id))
    .filter((chat) => !needle || chat.name.toLocaleLowerCase("zh-CN").includes(needle))
    .slice()
    .sort((left, right) => {
      const summarizedOrder = Number(!summarized.has(left.id)) - Number(!summarized.has(right.id));
      if (summarizedOrder) return summarizedOrder;
      return chatNameCollator.compare(left.name, right.name) || left.id.localeCompare(right.id);
    });
}
