import { RouteNotFound } from "@/components/app/route-states";

export default function NotFound() {
  return (
    <div className="a4t" style={{ padding: "var(--sp-4, 1.5rem)" }}>
      <RouteNotFound />
    </div>
  );
}
