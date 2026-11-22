import "../landing.css";
import { AuroraBackground } from "@/components/ui/aurora-background";
import { HeroStage } from "@/components/marketing/hero-stage";
import { LandingNav } from "@/components/marketing/landing-nav";

export const metadata = { robots: { index: false, follow: false } };

const RED: [string, string, string] = ["hsla(5, 90%, 55%, 0.38)", "hsla(345, 80%, 45%, 0.2)", "transparent"];

export default async function Preview({ searchParams }: { searchParams: Promise<{ v?: string }> }) {
  const { v } = await searchParams;
  const custom = v === "red";
  return (
    <main className="mkt">
      <LandingNav />
      <AuroraBackground
        variant={custom ? "custom" : "ember"}
        colors={custom ? RED : undefined}
        speed={0.6}
        className="min-h-[900px]"
      >
        <div className="mkt-wrap"><HeroStage /></div>
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-[#08080A]" />
      </AuroraBackground>
    </main>
  );
}
