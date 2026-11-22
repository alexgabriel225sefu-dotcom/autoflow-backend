import "../landing.css";
import "./buttons.css";
import { ArrowRight } from "lucide-react";
import { Magnet } from "./magnet";

export const metadata = { robots: { index: false, follow: false } };

export default function Preview() {
  return (
    <main className="mkt" style={{ minHeight: "100vh", padding: "64px 24px", display: "grid", gap: 56, alignContent: "center" }}>
      <section className="mkt-wrap" style={{ textAlign: "center" }}>
        <p className="lp-eyebrow">Now</p>
        <div className="pv-row">
          <a className="mkt-btn mkt-btn-lg" href="#">Try free for 14 days</a>
          <a className="mkt-btn mkt-btn-outline mkt-btn-lg" href="#">See the platform</a>
        </div>
      </section>
      <section className="mkt-wrap" style={{ textAlign: "center" }}>
        <p className="lp-eyebrow">A. Shimmer + lift + arrow</p>
        <div className="pv-row">
          <a className="mkt-btn mkt-btn-lg pv-shimmer" href="#">Try free for 14 days <ArrowRight size={18} className="pv-arrow" aria-hidden /></a>
          <a className="mkt-btn mkt-btn-outline mkt-btn-lg pv-shimmer" href="#">See the platform <ArrowRight size={18} className="pv-arrow" aria-hidden /></a>
        </div>
      </section>
      <section className="mkt-wrap" style={{ textAlign: "center" }}>
        <p className="lp-eyebrow">B. Moving border</p>
        <div className="pv-row">
          <a className="mkt-btn mkt-btn-lg" href="#">Try free for 14 days</a>
          <a className="mkt-btn mkt-btn-outline mkt-btn-lg pv-border" href="#">See the platform</a>
        </div>
      </section>
      <section className="mkt-wrap" style={{ textAlign: "center" }}>
        <p className="lp-eyebrow">C. Magnetic</p>
        <div className="pv-row">
          <Magnet className="mkt-btn mkt-btn-lg pv-magnet" href="#">Try free for 14 days</Magnet>
          <Magnet className="mkt-btn mkt-btn-outline mkt-btn-lg pv-magnet" href="#">See the platform</Magnet>
        </div>
      </section>
    </main>
  );
}
