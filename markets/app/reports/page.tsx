import { Masthead } from "../masthead";
import ReportForm from "./report-form";

export const metadata = { title: "Company research · Europa" };

export default async function Reports({ searchParams }: { searchParams: Promise<{ ticker?: string | string[] }> }) {
  const { ticker } = await searchParams;
  return <><Masthead page="reports"/><main className="shell report-shell">
    <div className="page-intro"><div><h1>Company research</h1><p>A sourced brief on a company’s earnings and recent news.</p></div></div>
    <ReportForm initialTicker={typeof ticker === "string" ? ticker.slice(0, 15).toUpperCase() : ""}/>
  </main></>;
}
