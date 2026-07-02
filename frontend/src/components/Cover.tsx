import { useState } from "react";
import { getCoverUrl } from "../api/library";

interface CoverProps {
  mountpoint: string;
  ipodPath: string | undefined;
  alt: string;
  className?: string;
}

export function Cover({ mountpoint, ipodPath, alt, className = "" }: CoverProps) {
  const [failed, setFailed] = useState(false);
  const showImage = !!ipodPath && !failed;

  return (
    <div className={`flex items-center justify-center overflow-hidden bg-surface-hover text-2xl ${className}`}>
      {showImage ? (
        <img
          src={getCoverUrl(mountpoint, ipodPath)}
          alt={alt}
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className="text-text-secondary">♪</span>
      )}
    </div>
  );
}
