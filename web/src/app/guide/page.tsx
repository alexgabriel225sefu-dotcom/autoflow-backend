import type { Metadata } from "next";
import { ContentShell } from "@/components/marketing/content-shell";
import { JsonLd } from "@/components/marketing/json-ld";
import { GuideHub as Hub } from "@/components/marketing/guide-hub";
import { breadcrumbLd, guideHubLd } from "@/lib/json-ld";

const TITLE = "Guides: rules-based trading, cTrader, risk and demo testing";
const DESCRIPTION =
  "Plain-language guides from Apex4Traders: what rules-based trading is, how to connect cTrader safely, how indicators work as conditions, risk per trade, demo testing and journals.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/guide" },
  openGraph: { type: "website", url: "/guide", siteName: "Apex4Traders", title: TITLE, description: DESCRIPTION },
};

const LEDE =
  "Short, plain-language guides on writing rules, connecting your own cTrader account, setting limits and testing on demo. Educational only, and not financial advice.";

export default function GuideHub() {
  return (
    <ContentShell>
      <JsonLd data={guideHubLd()} />
      <JsonLd data={breadcrumbLd([{ name: "Home", path: "/" }, { name: "Guides", path: "/guide" }])} />
      <Hub lede={LEDE} />
    </ContentShell>
  );
}
