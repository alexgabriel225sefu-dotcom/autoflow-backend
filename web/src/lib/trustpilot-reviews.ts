import type { Testimonial } from "@/components/ui/hover-testimonial-card";
import { trustpilotLinks } from "@/lib/trustpilot";

/**
 * Real Trustpilot reviews, copied word for word from the review itself.
 * Add every review you receive, the good and the bad: picking only the flattering
 * ones is what Trustpilot's rules and consumer law forbid. Never write, shorten or
 * "fix" a review. The section stays hidden while this list is empty.
 */
export const TRUSTPILOT_REVIEWS: readonly Pick<Testimonial, "id" | "quote" | "author">[] = [
  { id: "paul-varga", quote: "Awesome.It s very helpfull", author: { name: "Paul Varga" } },
  { id: "karla-laszlo", quote: "Awesome nice platform!!", author: { name: "Karla Laszlo" } },
];

export function trustpilotTestimonials(): Testimonial[] {
  const source = { name: "Read on Trustpilot", href: trustpilotLinks().profileUrl };
  return TRUSTPILOT_REVIEWS.map((review) => ({ ...review, source }));
}
