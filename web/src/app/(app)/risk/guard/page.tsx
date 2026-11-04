import { RoadmapPanel } from "@/components/app/roadmap-panel";
export default function RiskGuardPage() { return <RoadmapPanel title="Advanced risk guard" description="Evaluate a risk snapshot before any action; this endpoint never sends an order." endpoint="risk/guard" disclaimer="A missing risk input is treated as unknown and blocks the decision." />; }
