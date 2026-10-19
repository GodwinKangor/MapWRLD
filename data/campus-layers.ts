// Shared campus geography for the map: the world boundary, the default view, and the
// illustrative energy-network and future-work overlays. Coordinates are [longitude, latitude].

export type LonLat = [number, number];

// The map world: terrain, imagery, buildings, roads, fields and trees all stop at this rectangle.
export const CAMPUS_BOUNDS = { west: -72.2972, south: 43.6961, east: -72.2785, north: 43.7108 };

export const DARTMOUTH_HOME = { longitude: -72.2884, latitude: 43.7037 };
export const GROUND_VIEW = { longitude: -72.2897, latitude: 43.7007 };

// Schematic only: hub positions and links illustrate the district-heat and electric networks;
// they are not surveyed pipe or cable routes.
export const ENERGY_GRAPH = {
  hub: [-72.2873, 43.7006],
  westHub: [-72.2902, 43.7027],
  northHub: [-72.2889, 43.7049],
  eastHub: [-72.2866, 43.7038],
} satisfies Record<string, LonLat>;

export const HEATING_CONNECTIONS: Array<[LonLat, LonLat]> = [
  [ENERGY_GRAPH.hub, ENERGY_GRAPH.westHub],
  [ENERGY_GRAPH.westHub, ENERGY_GRAPH.northHub],
  [ENERGY_GRAPH.northHub, ENERGY_GRAPH.eastHub],
  [ENERGY_GRAPH.eastHub, ENERGY_GRAPH.hub],
  [ENERGY_GRAPH.northHub, [-72.28913, 43.70535]],
  [ENERGY_GRAPH.westHub, [-72.2899353, 43.7027887]],
  [ENERGY_GRAPH.westHub, [-72.29044, 43.70456]],
  [ENERGY_GRAPH.hub, [-72.28858, 43.70187]],
  [ENERGY_GRAPH.eastHub, [-72.28658, 43.70371]],
  [ENERGY_GRAPH.eastHub, [-72.28578, 43.70887]],
];

// the first four heating links are the trunk loop; the rest are branches
export const HEATING_TRUNK_COUNT = 4;

export const ELECTRIC_CONNECTIONS: Array<[LonLat, LonLat]> = [
  [[-72.2909, 43.7001], [-72.2886, 43.7016]],
  [[-72.2886, 43.7016], [-72.2869, 43.7038]],
  [[-72.2869, 43.7038], [-72.2858, 43.7089]],
  [[-72.2886, 43.7016], [-72.2902, 43.7046]],
];

export const FUTURE_WORK: { label: string; coordinates: LonLat }[] = [
  { label: "Low-temp heat loop study", coordinates: [-72.2873, 43.7006] },
  { label: "Lab airflow optimization", coordinates: [-72.28578, 43.70887] },
  { label: "Dining heat recovery review", coordinates: [-72.29044, 43.70456] },
];

export function insideCampus([longitude, latitude]: LonLat) {
  return longitude >= CAMPUS_BOUNDS.west && longitude <= CAMPUS_BOUNDS.east && latitude >= CAMPUS_BOUNDS.south && latitude <= CAMPUS_BOUNDS.north;
}
