import type { Metadata } from "next";
import { CampusApp } from "@/components/campus-app";

export const metadata: Metadata = { title: "Dartmouth Energy Twin · standalone preview" };

export default function StandalonePreview() {
  return <CampusApp renderer="three" />;
}
