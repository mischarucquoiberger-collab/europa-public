import MarketFrameSize from "./market-frame";
import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "Europa · Markets",
  description: "A clear view of U.S. markets, the latest listings, and company earnings.",
};

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><MarketFrameSize/>{children}</body></html>;
}
