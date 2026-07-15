import { NextResponse } from "next/server";
import { buildings as staticBuildings, type Building, type Entrance } from "@/data/buildings";

export const revalidate = 300;

type DatabaseEntrance = {
  id: string;
  label: string;
  kind: Entrance["kind"];
  longitude: number;
  latitude: number;
  approach_longitude: number;
  approach_latitude: number;
  heading: number;
  is_primary: boolean;
};

type DatabaseMedia = { caption: string; sort_order: number };
type DatabaseBuilding = {
  id: string;
  name: string;
  short_code: string;
  category: string;
  subtitle: string;
  description: string;
  longitude: number;
  latitude: number;
  is_open: boolean;
  hours_summary: string;
  image_class: string;
  features: string[] | null;
  gallery_labels: string[] | null;
  entrances: DatabaseEntrance[];
  building_media: DatabaseMedia[];
};

export async function GET() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return response(staticBuildings, "static");

  try {
    const result = await fetch(
      `${url}/rest/v1/buildings?select=*,entrances(*),building_media(caption,sort_order)&order=name.asc`,
      {
        headers: { apikey: key, Authorization: `Bearer ${key}` },
        next: { revalidate: 300 },
      },
    );
    if (!result.ok) throw new Error(`Supabase returned ${result.status}`);
    const rows = await result.json() as DatabaseBuilding[];
    const mapped = rows.map(mapBuilding).filter((item): item is Building => item !== null);
    return response(mapped.length ? mapped : staticBuildings, mapped.length ? "supabase" : "static");
  } catch (error) {
    console.error("Building database unavailable; using static data.", error);
    return response(staticBuildings, "static");
  }
}

function mapBuilding(row: DatabaseBuilding): Building | null {
  const entrances = (row.entrances ?? []).map((entrance) => ({
    id: entrance.id,
    label: entrance.label,
    kind: entrance.kind,
    coordinates: [entrance.longitude, entrance.latitude] as [number, number],
    approach: [entrance.approach_longitude, entrance.approach_latitude] as [number, number],
    heading: entrance.heading,
  }));
  const primaryRow = row.entrances?.find((entrance) => entrance.is_primary);
  const primary = entrances.find((entrance) => entrance.id === primaryRow?.id) ?? entrances[0];
  if (!primary) return null;
  const media = [...(row.building_media ?? [])].sort((a, b) => a.sort_order - b.sort_order);
  return {
    id: row.id,
    name: row.name,
    shortCode: row.short_code,
    category: row.category,
    subtitle: row.subtitle,
    description: row.description,
    coordinates: [row.longitude, row.latitude],
    entrance: primary,
    entrances,
    open: row.is_open,
    hours: row.hours_summary,
    imageClass: row.image_class,
    features: row.features ?? [],
    gallery: media.length ? media.map((item) => item.caption) : (row.gallery_labels ?? []),
    energy: {
      useType: row.category,
      system: "Planning estimate",
      demandKw: 0,
      annualMwh: 0,
      emissions: "Medium",
      retrofit: "Add energy metadata in Supabase",
      score: 0,
    },
  };
}

function response(buildings: Building[], source: "supabase" | "static") {
  return NextResponse.json({ buildings, source }, {
    headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=86400" },
  });
}
