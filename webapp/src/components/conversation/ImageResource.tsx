import type { ImgHTMLAttributes } from "react";
import { useImageResource } from "../../lib/useImageResource";

/** Protected image locators must never be assigned directly to img.src. */
export function isBackendImageSource(src: string): boolean {
  return /\/api\/image(?:\?|$)/i.test(src);
}

export function ImageResource({src = "", ...props}: Omit<ImgHTMLAttributes<HTMLImageElement>, "srcSet">) {
  const image = useImageResource(src, isBackendImageSource(src));
  return <img {...props} src={image.url} data-image-state={image.loaded ? "ready" : image.failures ? "error" : "loading"} />;
}
