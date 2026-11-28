import { jsonLdString } from "@/lib/json-ld";

/** One JSON-LD script tag. The payload is escaped by jsonLdString. */
export function JsonLd({ data }: { data: unknown }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: jsonLdString(data) }}
    />
  );
}
