import { RouteLoading } from "@/components/app/route-states";

export default function Loading() {
  return (
    <div className="a4t" style={{ padding: "var(--sp-4, 1.5rem)" }}>
      <RouteLoading />
    </div>
  );
}
