import { isStockTip, type Article } from "@/lib/massive";
import { NewsList } from "./stock-news";

/**
 * Stock news as the publisher wrote it. This app makes no model calls of its own (every
 * model call goes through the project's Python backend), so each story keeps its own
 * headline, and "Story details" shows the publisher's description unless it reads as a tip.
 */
function details(story: Article): Article {
  const description = story.description?.replace(/\s+/g, " ").trim();
  if (!description || description === story.title || isStockTip(description)) return story;
  const sentences = Array.from(new Intl.Segmenter("en", { granularity: "sentence" }).segment(description), (part) => part.segment);
  let summary = "";
  for (const sentence of sentences) {
    if (summary && (summary + sentence).length > 420) break;
    summary += sentence;
  }
  return { ...story, summary: summary.trim() };
}

export function Briefing({ stories, title }: { stories: Article[] | null; title?: string; newspaper?: boolean }) {
  return <NewsList title={title} stories={stories ? stories.map(details) : null}/>;
}
