/**
 * A real capture of the product in a quiet bezel: 8px of hairline-bordered
 * surface around the image, 20px outer radius, 12px inner. The image carries
 * its own width and height so the page does not shift while it loads.
 * Nothing is drawn on top of it.
 */
export function ProductFrame({
  src, alt, caption, priority = false,
}: {
  src: string; alt: string; caption?: string; priority?: boolean;
}) {
  return (
    <figure className="lp-frame">
      <div className="lp-frame-bezel">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={alt}
          width={1800}
          height={1125}
          loading={priority ? "eager" : "lazy"}
          fetchPriority={priority ? "high" : undefined}
          decoding="async"
        />
      </div>
      {caption ? <figcaption>{caption}</figcaption> : null}
    </figure>
  );
}
