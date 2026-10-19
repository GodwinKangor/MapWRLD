import type { DetailedHTMLProps, HTMLAttributes } from "react";

// The model-viewer custom element (loaded via CDN <Script>, same pattern as
// Cesium in components/campus-map.tsx) has no React/TS types of its own.
// React 19's JSX namespace lives under React.JSX, not the bare global JSX
// namespace, so the augmentation target is "react", not `declare global`.
declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "model-viewer": DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
        src?: string;
        alt?: string;
        "camera-controls"?: boolean;
        "auto-rotate"?: boolean;
        "shadow-intensity"?: string | number;
        exposure?: string | number;
        "environment-image"?: string;
        loading?: "auto" | "lazy" | "eager";
        reveal?: "auto" | "interaction" | "manual";
      };
    }
  }
}
