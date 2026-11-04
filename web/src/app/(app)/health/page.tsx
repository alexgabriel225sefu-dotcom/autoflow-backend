import { RoadmapPanel } from "@/components/app/roadmap-panel";
export default function HealthPage() { return <RoadmapPanel title="Automation health" description="A conservative score of the dependencies visible to this session." endpoint="health-score" readOnly />; }
