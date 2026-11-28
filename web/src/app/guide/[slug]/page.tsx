import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ArticleView } from "@/components/marketing/article-view";
import { ARTICLES, articleBySlug, articlePath } from "@/content/articles";

// Only the slugs below exist; anything else is a 404, never a fallback render.
export const dynamicParams = false;

export function generateStaticParams() {
  return ARTICLES.map((a) => ({ slug: a.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const a = articleBySlug(slug);
  if (!a) return {};
  const path = articlePath(a.slug);
  return {
    title: a.title,
    description: a.description,
    keywords: [...a.keywords],
    alternates: { canonical: path },
    openGraph: {
      type: "article",
      url: path,
      siteName: "Apex4Traders",
      title: a.title,
      description: a.description,
      publishedTime: a.published,
      modifiedTime: a.updated,
      authors: ["Apex4Traders"],
    },
  };
}

export default async function GuideArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const a = articleBySlug(slug);
  if (!a) notFound();
  return <ArticleView article={a} />;
}
