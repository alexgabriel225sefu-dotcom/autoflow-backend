"use client";

import { useEffect, useRef } from "react";
import { TRUSTPILOT_SCRIPT_URL, trustpilotConfig } from "@/lib/trustpilot";

declare global {
  interface Window {
    Trustpilot?: { loadFromElement: (el: HTMLElement, force?: boolean) => void };
  }
}

/**
 * The Trustpilot TrustBox: logo, stars and the real review count, as Trustpilot
 * itself reports them. The whole box is a link to the public profile.
 *
 * It renders nothing until the ids are configured, and its numbers can only come
 * from Trustpilot's own widget. Nothing about the score is written in this repo.
 * The script is added once, in the browser, only where this component is
 * mounted (the public landing page); it is not loaded in the signed-in platform.
 */
export function TrustpilotWidget({ height = "24px" }: { height?: string }) {
  const config = trustpilotConfig();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!config || !ref.current) return;
    const el = ref.current;
    const load = () => window.Trustpilot?.loadFromElement(el, true);
    if (window.Trustpilot) {
      load();
      return;
    }
    let script = document.querySelector<HTMLScriptElement>("script[data-trustpilot]");
    if (!script) {
      script = document.createElement("script");
      script.src = TRUSTPILOT_SCRIPT_URL;
      script.async = true;
      script.dataset.trustpilot = "1";
      document.head.appendChild(script);
    }
    script.addEventListener("load", load);
    return () => script?.removeEventListener("load", load);
  }, [config]);

  if (!config) return null;

  return (
    <div
      ref={ref}
      className="trustpilot-widget lp-trust"
      data-locale="en-US"
      data-template-id={config.templateId}
      data-businessunit-id={config.businessUnitId}
      data-style-height={height}
      data-style-width="100%"
      data-theme="dark"
    >
      <a href={config.profileUrl} target="_blank" rel="noopener noreferrer">
        Trustpilot
      </a>
    </div>
  );
}
