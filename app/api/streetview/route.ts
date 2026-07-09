import { NextRequest, NextResponse } from "next/server";
import { buildings } from "@/data/buildings";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const id = request.nextUrl.searchParams.get("building");
  const building = buildings.find((item) => item.id === id);
  const apiKey = process.env.GOOGLE_MAPPLATFORM_APIKEY ?? process.env.GOOGLE_MAPS_API_KEY;

  if (!building) return NextResponse.json({ error: "Unknown building" }, { status: 404 });
  if (!apiKey) return NextResponse.json({ error: "Google Maps key is not configured" }, { status: 503 });

  const [longitude, latitude] = building.entrance.coordinates;
  const lookupParams = new URLSearchParams({
    location: `${latitude},${longitude}`,
    radius: "100",
    source: "outdoor",
    key: apiKey.trim(),
  });

  try {
    const metadataResponse = await fetch(
      `https://maps.googleapis.com/maps/api/streetview/metadata?${lookupParams}`,
      { cache: "no-store" },
    );
    const metadata = await metadataResponse.json() as {
      status?: string;
      pano_id?: string;
      location?: { lat: number; lng: number };
    };

    if (metadata.status !== "OK" || !metadata.pano_id || !metadata.location) {
      return NextResponse.json({ error: "No Street View imagery found" }, { status: 404 });
    }

    const distance = distanceInMeters(metadata.location.lat, metadata.location.lng, latitude, longitude);
    if (distance > 120) {
      return NextResponse.json({ error: "Street View imagery is too far from this entrance" }, { status: 404 });
    }

    // Street View headings must be measured from the panorama—not copied from
    // the 3D map camera—so the returned image actually faces the entrance.
    const heading = bearingInDegrees(metadata.location.lat, metadata.location.lng, latitude, longitude);
    const params = new URLSearchParams({
    size: "640x640",
    pano: metadata.pano_id,
    heading: String(Math.round(heading)),
    pitch: "4",
    fov: "82",
    return_error_code: "true",
    key: apiKey.trim(),
  });
    const response = await fetch(`https://maps.googleapis.com/maps/api/streetview?${params}`, {
      cache: "no-store",
    });
    if (!response.ok || !response.body) {
      return NextResponse.json({ error: "No Street View imagery found" }, { status: response.status || 404 });
    }

    return new NextResponse(response.body, {
      headers: {
        "Content-Type": response.headers.get("content-type") ?? "image/jpeg",
        "Cache-Control": "private, no-store, max-age=0",
      },
    });
  } catch {
    return NextResponse.json({ error: "Street View request failed" }, { status: 502 });
  }
}

function bearingInDegrees(fromLat: number, fromLng: number, toLat: number, toLng: number) {
  const φ1 = toRadians(fromLat);
  const φ2 = toRadians(toLat);
  const λ = toRadians(toLng - fromLng);
  const y = Math.sin(λ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(λ);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

function distanceInMeters(fromLat: number, fromLng: number, toLat: number, toLng: number) {
  const earthRadius = 6_371_000;
  const Δφ = toRadians(toLat - fromLat);
  const Δλ = toRadians(toLng - fromLng);
  const φ1 = toRadians(fromLat);
  const φ2 = toRadians(toLat);
  const a = Math.sin(Δφ / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin(Δλ / 2) ** 2;
  return earthRadius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function toRadians(value: number) {
  return value * Math.PI / 180;
}
