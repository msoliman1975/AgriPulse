import clsx from "clsx";
import type { ReactNode } from "react";

interface SkeletonProps {
  className?: string;
  children?: ReactNode;
}

export function Skeleton({ className, children }: SkeletonProps): ReactNode {
  return (
    <div className={clsx("animate-pulse rounded bg-ap-line/60", className)} aria-hidden="true">
      {children}
    </div>
  );
}
