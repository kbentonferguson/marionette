import { useEffect } from "react";
import { imagePath } from "../../lib/transport";
import { useImageResource } from "../../lib/useImageResource";
import {
  adoptTranscriptPreviewBlob,
  isBlobPreviewUrl,
  isDurableTranscriptImageReady,
  peekOwnedTranscriptPreviewBlob,
  releaseTranscriptPreviewBlob,
} from "./transcriptImageBlobs";
import { isDurableImagePath } from "./transcriptImageRetry";

export type TranscriptImageProps = {
  path: string;
  name: string;
  previewUrl?: string;
  onImageClick?: (url: string) => void;
};

export function TranscriptImage({path, name, previewUrl, onImageClick}: TranscriptImageProps) {
  const hasDurable = isDurableImagePath(path);
  const source = hasDurable ? imagePath(path) : previewUrl || path;
  const image = useImageResource(source, hasDurable);
  const fallback = !isDurableTranscriptImageReady(path)
    ? (isBlobPreviewUrl(previewUrl) ? previewUrl : peekOwnedTranscriptPreviewBlob(path)) : null;
  useEffect(() => {
    if (hasDurable && previewUrl && isBlobPreviewUrl(previewUrl)) adoptTranscriptPreviewBlob(path, previewUrl);
  }, [hasDurable, path, previewUrl]);
  useEffect(() => {
    if (hasDurable && image.loaded) releaseTranscriptPreviewBlob(path);
  }, [hasDurable, path, image.loaded]);
  const displaySrc = image.url || fallback || undefined;
  return (
    <div className="relative w-11 h-11 rounded overflow-hidden border border-edge bg-panel flex-shrink-0">
      <img
        src={displaySrc}
        alt={name}
        data-durable-src={hasDurable ? source : undefined}
        data-durable-loaded={image.loaded ? "1" : "0"}
        data-failure-count={String(image.failures)}
        data-blob-fallback={!image.url && fallback ? "1" : "0"}
        onClick={() => onImageClick?.(source)}
        className="w-full h-full object-cover rounded cursor-pointer hover:opacity-85 transition-opacity"
      />
    </div>
  );
}
