import { ARTICLES, articlePath, type Article } from "@/content/articles";
import { FAQ_ITEMS } from "@/content/faq";
import { SITE_URL } from "@/lib/site";

/**
 * Plain-text summaries for AI assistants, following the llms.txt convention.
 *
 * Built from the same data as the pages, so an assistant that reads these
 * files is told exactly what a visitor is told, and nothing that is not on
 * the site. The convention is new and no assistant is obliged to read it;
 * the pages themselves stay the source of truth.
 */
const ABOUT =
  "Apex4Traders is software that runs trading rules you configure, on a cTrader account you connect yourself. " +
  "You build a rule from named conditions, read it back in plain language, preview what it would decide and test it on a demo account.";

const FACTS = [
  "It is not financial advice, it does not supply signals, it does not manage money for anyone and it never takes custody of funds.",
  "It connects to cTrader through cTrader's own authorisation (OAuth), so it never sees a broker password. You can disconnect at any time.",
  "In this release automation runs on demo accounts only. Live trading and checkout are not open.",
  "The demo is free for 14 days. The price of the paid plan is shown on the pricing page, not here.",
  "cTrader is available now. MetaTrader 4 and MetaTrader 5 are listed as coming soon, with no dates promised.",
  "Leveraged trading carries a high risk of loss. A preview never places an order.",
];

const url = (path: string) => `${SITE_URL}${path}`;

export function llmsTxt(): string {
  const lines: string[] = [
    "# Apex4Traders",
    "",
    `> ${ABOUT}`,
    "",
    "## Key facts",
    "",
    ...FACTS.map((f) => `- ${f}`),
    "",
    "## Guides",
    "",
    `- [How to test a trading rule on a demo account](${url("/guide/test-a-rule-on-demo")}): eight steps from sign-up to the first journal entry.`,
    ...ARTICLES.map((a) => `- [${a.title}](${url(articlePath(a.slug))}): ${a.description}`),
    "",
    "## Product",
    "",
    `- [Home](${url("/")}): what the platform does.`,
    `- [FAQ](${url("/faq")}): ${FAQ_ITEMS.length} questions answered plainly.`,
    `- [Pricing](${url("/pricing")}): the current offer.`,
    `- [Sign up](${url("/signup")}): create a free demo account.`,
    "",
    "## Optional",
    "",
    `- [Full text of every guide](${url("/llms-full.txt")}): the guides and the FAQ as one Markdown document.`,
    "",
  ];
  return lines.join("\n");
}

function tableMd(t: NonNullable<Article["sections"][number]["table"]>): string[] {
  return [
    `| ${t.head.join(" | ")} |`,
    `| ${t.head.map(() => "---").join(" | ")} |`,
    ...t.rows.map((r) => `| ${r.join(" | ")} |`),
  ];
}

export function articleMarkdown(a: Article): string {
  const out: string[] = [
    `# ${a.title}`,
    "",
    `Source: ${url(articlePath(a.slug))}`,
    `Updated: ${a.updated}`,
    "",
    `**Short answer.** ${a.summary}`,
    "",
  ];
  for (const s of a.sections) {
    out.push(`## ${s.heading}`, "");
    for (const p of s.paragraphs) out.push(p, "");
    if (s.bullets) out.push(...s.bullets.map((b) => `- ${b}`), "");
    if (s.steps) out.push(...s.steps.map((b, i) => `${i + 1}. ${b}`), "");
    if (s.table) out.push(`*${s.table.caption}*`, "", ...tableMd(s.table), "");
  }
  out.push("## Questions people ask", "");
  for (const f of a.faq) out.push(`### ${f.question}`, "", f.answer, "");
  return out.join("\n");
}

export function llmsFullTxt(): string {
  const parts: string[] = [
    "# Apex4Traders: guides and FAQ",
    "",
    `> ${ABOUT}`,
    "",
    ...FACTS.map((f) => `- ${f}`),
    "",
  ];
  for (const a of ARTICLES) parts.push("---", "", articleMarkdown(a));
  parts.push("---", "", "# Apex4Traders FAQ", "", `Source: ${url("/faq")}`, "");
  for (const f of FAQ_ITEMS) parts.push(`## ${f.question}`, "", f.answer, "");
  return parts.join("\n");
}
