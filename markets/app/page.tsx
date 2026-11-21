import {Suspense} from "react";
import {Briefing} from "./briefing";
import Desk from "./desk";
import { NewsSkeleton } from "./skeletons";
import { equityNews } from "@/lib/massive";
import { traced } from "@/lib/trace";
export const dynamic = "force-dynamic";
export default async function Home() {
  const stories = await traced("Markets · stock news", trace => equityNews(trace)).catch(() => null);
  return <Desk briefing={<Suspense fallback={<NewsSkeleton title="Stock news"/>}><Briefing newspaper stories={stories}/></Suspense>}/>;
}
