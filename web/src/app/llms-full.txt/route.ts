import { llmsFullTxt } from "@/lib/llms";

// Static text for AI assistants, built from the same data as the pages.
export const dynamic = "force-static";

export function GET() {
  return new Response(llmsFullTxt(), {
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "public, max-age=3600",
    },
  });
}
