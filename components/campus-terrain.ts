type Vector3 = { x: number; y: number; z: number };
type Cartographic = { longitude: number; latitude: number; height: number };
type TerrainAnchor = { node: string; position: [number, number, number] };
export type CampusProjection = {
  longitude: number;
  latitude: number;
  longitudePerMeter: number;
  latitudePerMeter: number;
};

export type GroundedModel = {
  show: boolean;
  modelMatrix: unknown;
  ready: boolean;
  readyEvent: { addEventListener: (listener: () => void) => () => void };
  getNode: (name: string) => { matrix: unknown } | undefined;
  destroy: () => void;
};

export type TerrainCesiumApi = {
  Matrix4: {
    new (): unknown;
    inverseTransformation: (matrix: unknown, result: unknown) => unknown;
    multiplyByPoint: (matrix: unknown, point: Vector3, result: Vector3) => Vector3;
    fromTranslation: (translation: Vector3) => unknown;
  };
  Cartesian3: {
    new (x?: number, y?: number, z?: number): Vector3;
    fromRadians: (longitude: number, latitude: number, height: number) => Vector3;
  };
  Cartographic: {
    fromCartesian: (point: Vector3) => Cartographic;
    fromDegrees: (longitude: number, latitude: number) => Cartographic;
  };
  sampleTerrainMostDetailed: (provider: unknown, positions: Cartographic[]) => Promise<Cartographic[]>;
};

// Sample independently of the camera's current terrain LOD. These fixed node
// transforms are calculated once; panning and zooming never recompute them.
export async function sampleCampusGround(
  Cesium: TerrainCesiumApi,
  terrainProvider: unknown,
  modelMatrix: unknown,
  anchorsUrl: string,
  projection: CampusProjection,
  isCancelled: () => boolean,
) {
  const response = await fetch(anchorsUrl);
  if (!response.ok) throw new Error("Campus terrain anchors unavailable");
  const { anchors } = await response.json() as { anchors: TerrainAnchor[] };
  if (isCancelled()) return [];
  // Recover geographic coordinates using the source export's calibrated
  // projection. A UI camera target is not the model's geographic origin.
  const positions = anchors.map(({ position: [east, , south] }) =>
    Cesium.Cartographic.fromDegrees(
      projection.longitude + east * projection.longitudePerMeter,
      projection.latitude - south * projection.latitudePerMeter,
    ),
  );
  const sampled = await Cesium.sampleTerrainMostDetailed(terrainProvider, positions);
  if (isCancelled()) return [];
  if (sampled.some((position) => !Number.isFinite(position.height))) {
    throw new Error("Campus terrain elevation unavailable");
  }
  const inverse = Cesium.Matrix4.inverseTransformation(modelMatrix, new Cesium.Matrix4());
  return anchors.map((anchor, index) => {
    const ground = sampled[index];
    const local = Cesium.Matrix4.multiplyByPoint(inverse, Cesium.Cartesian3.fromRadians(
      ground.longitude, ground.latitude, ground.height,
    ), new Cesium.Cartesian3());
    const [east, up, south] = anchor.position;
    // Back to glTF's east/up/south axes. Translating the parent moves the
    // entire building, including its detailed meshes, without deforming it.
    return { node: anchor.node, longitude: positions[index].longitude, latitude: positions[index].latitude, matrix: Cesium.Matrix4.fromTranslation(new Cesium.Cartesian3(
      local.x - east, local.z - up, -local.y - south,
    )) };
  });
}

export function applyCampusGround(model: GroundedModel, placements: Awaited<ReturnType<typeof sampleCampusGround>>) {
  for (const placement of placements) {
    const node = model.getNode(placement.node);
    if (!node) throw new Error(`Campus terrain node missing: ${placement.node}`);
    node.matrix = placement.matrix;
  }
}
