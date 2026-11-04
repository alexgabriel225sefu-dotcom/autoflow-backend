import { RoadmapPanel } from "@/components/app/roadmap-panel";
export default function RuleLayerPage() { return <RoadmapPanel title="Broker-agnostic rule layer" description="Calculate a bounded position size from server-provided instrument conventions." endpoint="rule-layer" disclaimer="This calculation is informational; it does not submit an order." />; }
