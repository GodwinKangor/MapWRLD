// Campus camera limits on top of Cesium's default mouse controls. A soft wall keeps the point being looked at inside the campus rectangle, applied every frame
// rather than as a snap when a drag ends.

type Vector3 = { x: number; y: number; z: number };
type Cartographic = { longitude: number; latitude: number; height: number };
type Bounds = { west: number; south: number; east: number; north: number };
type WindowPosition = { x: number; y: number };

type CameraLike = {
  position: Vector3;
  direction: Vector3;
  heading: number;
  pitch: number;
  positionCartographic: Cartographic;
  percentageChanged?: number;
  changed: { addEventListener: (listener: () => void) => () => void };
  getPickRay: (position: WindowPosition) => { origin: Vector3; direction: Vector3 } | undefined;
  setView: (options: unknown) => void;
};

type ViewerLike = {
  camera: CameraLike;
  scene: {
    canvas: HTMLCanvasElement;
    pickPositionSupported?: boolean;
    pickPosition: (position: WindowPosition) => Vector3 | undefined;
    requestRender: () => void;
    screenSpaceCameraController: Record<string, unknown> & { minimumZoomDistance: number; maximumZoomDistance: number };
  };
};

export type CameraCesiumApi = {
  Cartesian3: {
    new (x?: number, y?: number, z?: number): Vector3;
    add: (a: Vector3, b: Vector3, result: Vector3) => Vector3;
    subtract: (a: Vector3, b: Vector3, result: Vector3) => Vector3;
    fromRadians: (longitude: number, latitude: number, height: number) => Vector3;
  };
  Ellipsoid: { WGS84: { geodeticSurfaceNormal: (point: Vector3, result: Vector3) => Vector3; cartesianToCartographic: (point: Vector3) => Cartographic | undefined } };
  Plane: { fromPointNormal: (point: Vector3, normal: Vector3) => unknown };
  IntersectionTests: { rayPlane: (ray: unknown, plane: unknown) => Vector3 | undefined };
  Math: { toDegrees: (radians: number) => number; toRadians: (degrees: number) => number };
};

type Options = {
  bounds: Bounds;
  groundHeight: number;       // fallback ground (ellipsoid height, m) when nothing is under the cursor
  minZoom: number;
  maxZoom: number;
  shallowestPitch: number;    // degrees; stops the view tilting up into the void past the campus
};

export function installCampusControls(viewer: ViewerLike, Cesium: CameraCesiumApi, options: Options) {
  const { scene, camera } = viewer;
  const controller = scene.screenSpaceCameraController;
  controller.minimumZoomDistance = options.minZoom;
  controller.maximumZoomDistance = options.maxZoom;
  camera.percentageChanged = 0.001;

  const scratch = () => new Cesium.Cartesian3();
  const up = (point: Vector3) => Cesium.Ellipsoid.WGS84.geodeticSurfaceNormal(point, scratch());

  // ground point under a screen position: the rendered terrain/building, else a level plane at campus height
  const groundUnder = (position: WindowPosition) => {
    const ray = camera.getPickRay(position);
    if (!ray) return undefined;
    const picked = scene.pickPositionSupported ? scene.pickPosition(position) : undefined;
    if (picked && Number.isFinite(picked.x)) return picked;
    const anchor = Cesium.Cartesian3.fromRadians(camera.positionCartographic.longitude, camera.positionCartographic.latitude, options.groundHeight);
    return Cesium.IntersectionTests.rayPlane(ray, Cesium.Plane.fromPointNormal(anchor, up(anchor)));
  };

  // ---- soft wall: keep the looked-at point inside the campus, and the view below the horizon
  let correcting = false;
  function keepInside() {
    if (correcting) return;
    correcting = true;
    try {
      const pitch = Cesium.Math.toDegrees(camera.pitch);
      if (pitch > options.shallowestPitch) {
        camera.setView({ orientation: { heading: camera.heading, pitch: Cesium.Math.toRadians(options.shallowestPitch), roll: 0 } });
      }
      const center = { x: scene.canvas.clientWidth / 2, y: scene.canvas.clientHeight / 2 };
      const target = groundUnder(center);
      const cartographic = target && Cesium.Ellipsoid.WGS84.cartesianToCartographic(target);
      if (!target || !cartographic) return;
      const longitude = Cesium.Math.toDegrees(cartographic.longitude);
      const latitude = Cesium.Math.toDegrees(cartographic.latitude);
      const clampedLongitude = Math.min(options.bounds.east, Math.max(options.bounds.west, longitude));
      const clampedLatitude = Math.min(options.bounds.north, Math.max(options.bounds.south, latitude));
      if (clampedLongitude === longitude && clampedLatitude === latitude) return;
      const inside = Cesium.Cartesian3.fromRadians(Cesium.Math.toRadians(clampedLongitude), Cesium.Math.toRadians(clampedLatitude), cartographic.height);
      camera.position = Cesium.Cartesian3.add(camera.position, Cesium.Cartesian3.subtract(inside, target, scratch()), scratch());
    } finally {
      correcting = false;
    }
  }
  const removeChanged = camera.changed.addEventListener(keepInside);

  return removeChanged;
}
