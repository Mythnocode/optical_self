import {
  AmbientLight,
  BoxHelper as ThreeBoxHelper,
  Box3,
  BufferGeometry,
  BoxGeometry,
  CanvasTexture,
  Color,
  CylinderGeometry,
  DirectionalLight,
  DoubleSide,
  Euler,
  Group,
  Line,
  LineBasicMaterial,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  PerspectiveCamera,
  PlaneGeometry,
  Quaternion,
  Raycaster,
  Scene,
  SphereGeometry,
  SRGBColorSpace,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import {
  renderTransformToTeachingPose,
  teachingOrientationToRenderQuaternion,
  teachingToRender,
} from "../domain/coordinates.js";
import { COMPONENT_CATALOG, type ComponentKind } from "../domain/component-catalog.js";
import type { TeachingComponent, TeachingPose, TeachingPreview } from "../domain/scene-types.js";

interface AssetManifestEntry {
  kind: string;
  file: string;
  housing_mm: [number, number, number];
  anchor: "output_face" | "input_face" | "center" | "top" | "bottom";
  axis: "+X";
  up: "+Z";
}

interface AssetManifest {
  schema_version: number;
  assets: AssetManifestEntry[];
}

export interface TeachingRendererOptions {
  axisHeightMm?: number;
  onSelect: (componentId: string | null) => void;
  onPoseChange: (componentId: string, pose: TeachingPose) => void;
  onDragStart?: () => void;
  onDragEnd?: () => void;
  onAssetIssue: (message: string) => void;
}

const BOARD_LENGTH_MM = 450;
const BOARD_WIDTH_MM = 300;
const BOARD_THICKNESS_MM = 12.7;
const MIRROR_COLOR = 0x2b4455;
const RAY_COLOR = 0xe65a00;

export class TeachingRenderer {
  readonly scene = new Scene();
  readonly camera = new PerspectiveCamera(38, 1, 0.1, 4_000);

  private readonly renderer: WebGLRenderer;
  private readonly orbit: OrbitControls;
  private readonly transform: TransformControls;
  private readonly componentRoot = new Group();
  private readonly helperRoot = new Group();
  private readonly raycaster = new Raycaster();
  private readonly pointer = new Vector2();
  private readonly groups = new Map<string, Group>();
  private readonly outlines = new Map<string, ThreeBoxHelper>();
  private readonly assetCache = new Map<string, Promise<Object3D>>();
  private readonly loader = new GLTFLoader();
  private readonly canvas: HTMLCanvasElement;
  private readonly resizeObserver: ResizeObserver;
  private readonly manifestPromise: Promise<AssetManifest>;
  private readonly previewRays = new Group();
  private readonly options: TeachingRendererOptions;
  private axisHeightMm: number;
  private readonly requestFrameId: number;
  private activeGroup: Group | null = null;
  private selectedId: string | null = null;
  private componentById = new Map<string, TeachingComponent>();
  private skipCanvasSelection = false;
  private disposed = false;
  private initialSceneApplied = false;

  constructor(container: HTMLElement, options: TeachingRendererOptions) {
    this.options = options;
    this.axisHeightMm = Number.isFinite(options.axisHeightMm) ? Number(options.axisHeightMm) : 25;
    this.manifestPromise = this.loadManifest();
    this.scene.background = new Color("#C2C8D0");
    this.camera.position.set(0, 0, 200);

    this.renderer = new WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(container.clientWidth, container.clientHeight, false);
    this.renderer.setClearColor("#C2C8D0", 1);
    this.renderer.outputColorSpace = SRGBColorSpace;
    this.renderer.domElement.className = "teaching-canvas";
    this.renderer.domElement.setAttribute("aria-label", "Teaching Three.js optical bench");
    container.append(this.renderer.domElement);
    this.canvas = this.renderer.domElement;

    this.orbit = new OrbitControls(this.camera, this.canvas);
    this.orbit.enableDamping = true;
    this.orbit.dampingFactor = 0.08;
    this.orbit.target.set(40, Math.max(this.axisHeightMm * 0.45, 8), 0);
    this.orbit.addEventListener("change", this.renderOnce);
    this.resetCameraForComponents([]);

    this.transform = new TransformControls(this.camera, this.canvas);
    this.transform.setMode("translate");
    this.transform.setSize(0.8);
    this.transform.addEventListener("dragging-changed", this.onDraggingChanged);
    this.transform.addEventListener("objectChange", this.onObjectChange);
    this.transform.addEventListener("mouseDown", this.onTransformMouseDown);
    this.transform.addEventListener("mouseUp", this.onTransformMouseUp);
    this.scene.add(this.transform.getHelper());

    this.buildEnvironment();
    this.scene.add(this.componentRoot, this.helperRoot);
    this.previewRays.name = "Geometry preview rays";
    this.scene.add(this.previewRays);
    this.canvas.addEventListener("click", this.onCanvasClick);

    this.resizeObserver = new ResizeObserver(this.resize);
    this.resizeObserver.observe(container);
    this.requestFrameId = window.requestAnimationFrame(this.renderLoop);
  }

  setScene(components: TeachingComponent[], selectedId: string | null): void {
    const nextIds = new Set(components.map((component) => component.component_id));
    for (const [id, group] of this.groups) {
      if (!nextIds.has(id)) {
        this.componentRoot.remove(group);
        this.groups.delete(id);
        const outline = this.outlines.get(id);
        if (outline) {
          this.helperRoot.remove(outline);
          disposeTree(outline);
          this.outlines.delete(id);
        }
        disposeFallback(group);
      }
    }
    this.componentById = new Map(components.map((component) => [component.component_id, component]));

    for (const component of components) {
      const group = this.groups.get(component.component_id) ?? this.createComponentGroup(component);
      group.userData.componentId = component.component_id;
      group.userData.kind = component.kind;
      group.visible = component.enabled;
      group.position.fromArray(teachingToRender([component.pose.x_mm, component.pose.y_mm, component.pose.z_mm]));
      group.quaternion.fromArray(teachingOrientationToRenderQuaternion(component.pose, component.kind));
      group.userData.component = component;
      if (!this.groups.has(component.component_id)) {
        this.groups.set(component.component_id, group);
        this.componentRoot.add(group);
        this.attachAsset(component, group);
      }
    }

    this.selectedId = selectedId;
    this.updateSelection();
    if (!this.initialSceneApplied) {
      this.resetCameraForComponents(components);
      this.initialSceneApplied = true;
    } else {
      this.renderOnce();
    }
  }

  setTransformMode(mode: "translate" | "rotate"): void {
    this.transform.setMode(mode);
  }

  setInteractionEnabled(enabled: boolean): void {
    this.transform.enabled = enabled;
  }

  topView(): void {
    this.camera.up.set(0, 0, -1);
    this.camera.position.set(this.orbit.target.x, 350, this.orbit.target.z + 0.001);
    this.camera.lookAt(this.orbit.target);
    this.orbit.update();
    this.renderOnce();
  }

  resetView(): void {
    this.resetCameraForComponents([...this.componentById.values()]);
  }

  focusSelected(): void {
    if (!this.selectedId) {
      return;
    }
    const group = this.groups.get(this.selectedId);
    if (!group) {
      return;
    }
    this.orbit.target.copy(group.position);
    this.camera.position.set(group.position.x + 80, group.position.y + 80, group.position.z + 120);
    this.orbit.update();
    this.renderOnce();
  }

  fitScene(): void {
    const visible = [...this.groups.values()].filter((group) => group.visible);
    if (visible.length === 0) {
      this.resetView();
      return;
    }
    const bounds = new Box3().setFromObject(this.componentRoot);
    const center = bounds.getCenter(new Vector3());
    const size = bounds.getSize(new Vector3());
    const distance = Math.max(size.x, size.y, size.z, 120) * 1.35;
    this.orbit.target.copy(center);
    this.camera.position.set(center.x + distance * 0.75, center.y + distance * 0.55, center.z + distance);
    this.orbit.update();
    this.renderOnce();
  }

  dispose(): void {
    this.disposed = true;
    window.cancelAnimationFrame(this.requestFrameId);
    this.resizeObserver.disconnect();
    this.canvas.removeEventListener("click", this.onCanvasClick);
    this.orbit.removeEventListener("change", this.renderOnce);
    this.orbit.dispose();
    this.transform.removeEventListener("dragging-changed", this.onDraggingChanged);
    this.transform.removeEventListener("objectChange", this.onObjectChange);
    this.transform.removeEventListener("mouseDown", this.onTransformMouseDown);
    this.transform.removeEventListener("mouseUp", this.onTransformMouseUp);
    this.transform.dispose();
    for (const outline of this.outlines.values()) {
      disposeTree(outline);
    }
    disposeTree(this.scene);
    this.renderer.dispose();
    this.canvas.remove();
  }

  private resetCameraForComponents(components: TeachingComponent[]): void {
    const xPositions = components.map((component) => component.pose.x_mm);
    const beamStartX = xPositions.length ? Math.min(...xPositions) : 0;
    const beamEndX = xPositions.length ? Math.max(...xPositions) : 80;
    const spanX = Math.max(beamEndX - beamStartX, 72);
    const target = new Vector3(
      (beamStartX + beamEndX) * 0.5,
      Math.max(this.axisHeightMm * 0.45, 8),
      0,
    );
    const rotation = new Quaternion().setFromEuler(
      new Euler((-22 * Math.PI) / 180, (-38 * Math.PI) / 180, 0, "ZXY"),
    );
    const distance = Math.max(spanX * 2.55, 165);
    const cameraOffset = new Vector3(0, 0, distance).applyQuaternion(rotation);
    this.camera.up.set(0, 1, 0).applyQuaternion(rotation).normalize();
    this.camera.position.copy(target).add(cameraOffset);
    this.camera.quaternion.copy(rotation);
    this.orbit.target.copy(target);
    this.orbit.update();
    this.renderOnce();
  }

  private buildEnvironment(): void {
    this.scene.add(new AmbientLight(0x6a7380, 2.0));
    const keyLight = new DirectionalLight(0xffffff, 1.02);
    keyLight.position.set(-100, 260, 160);
    this.scene.add(keyLight);
    const fillLight = new DirectionalLight(0xffffff, 0.38);
    fillLight.position.set(100, 220, -160);
    this.scene.add(fillLight);

    const table = new Mesh(
      new BoxGeometry(BOARD_LENGTH_MM, BOARD_THICKNESS_MM, BOARD_WIDTH_MM),
      new MeshStandardMaterial({ color: 0xd7dce2, roughness: 0.42, metalness: 0.55 }),
    );
    table.name = "Teaching optical table";
    table.position.set(BOARD_LENGTH_MM / 2, -BOARD_THICKNESS_MM / 2, 0);
    table.receiveShadow = true;
    this.scene.add(table);

    const boardSurface = new Mesh(
      new PlaneGeometry(BOARD_LENGTH_MM, BOARD_WIDTH_MM),
      new MeshStandardMaterial({ map: createBreadboardTexture(), roughness: 0.52, metalness: 0.22 }),
    );
    boardSurface.name = "Breadboard hole pattern";
    boardSurface.rotation.x = -Math.PI / 2;
    boardSurface.position.set(BOARD_LENGTH_MM / 2, 0.01, 0);
    this.scene.add(boardSurface);

    const tableBase = new Mesh(
      new BoxGeometry(800, 0.4, 800),
      new MeshStandardMaterial({ color: 0x9aa3ad, roughness: 1, metalness: 0 }),
    );
    tableBase.position.set(BOARD_LENGTH_MM / 2, -18, 0);
    this.scene.add(tableBase);
    this.buildAxisGuides();
  }

  private buildAxisGuides(): void {
    const axisMaterial = new LineBasicMaterial({ color: 0x6b7280, transparent: true, opacity: 0.35 });
    const rail = new Line(
      geometryForLine([new Vector3(0, 25, 0), new Vector3(BOARD_LENGTH_MM, 25, 0)]),
      axisMaterial,
    );
    rail.name = "Teaching optical axis";
    this.scene.add(rail);
  }

  private createComponentGroup(component: TeachingComponent): Group {
    const group = new Group();
    group.name = `${component.kind}:${component.component_id}`;
    group.userData.componentId = component.component_id;
    group.userData.kind = component.kind;
    group.userData.assetState = "loading";
    group.add(this.createFallbackBody(component));
    return group;
  }

  private createFallbackBody(component: TeachingComponent): Group {
    const definition = COMPONENT_CATALOG[component.kind];
    const [length, width, height] = housingSize(component, definition.housingMm);
    const body = new Group();
    body.name = "Procedural fallback";
    body.userData.generatedFallback = true;
    const color = component.kind === "mirror" ? MIRROR_COLOR : 0x71849a;
    const material = new MeshStandardMaterial({
      color,
      roughness: component.kind === "lens" ? 0.2 : 0.56,
      metalness: component.kind === "lens" ? 0.24 : 0.48,
      transparent: component.kind === "lens",
      opacity: component.kind === "lens" ? 0.72 : 1,
      side: DoubleSide,
    });

    let mesh: Mesh;
    if (component.kind === "lens" || component.kind === "waveplate" || component.kind === "mirror") {
      const diskDiameter = Math.max(width, height);
      const cylinder = new CylinderGeometry(diskDiameter / 2, diskDiameter / 2, length, 32);
      cylinder.rotateZ(Math.PI / 2);
      mesh = new Mesh(cylinder, material);
    } else if (component.kind === "fiber") {
      mesh = new Mesh(new BoxGeometry(length, width, height), material);
    } else {
      mesh = new Mesh(new BoxGeometry(length, width, height), material);
    }

    if (definition.anchor === "output_face") {
      mesh.position.x = -length / 2;
    } else if (definition.anchor === "input_face") {
      mesh.position.x = length / 2;
    }
    mesh.castShadow = false;
    mesh.receiveShadow = false;
    body.add(mesh);
    if (component.kind === "laser") {
      const aperture = new Mesh(
        new SphereGeometry(1.2, 16, 12),
        new MeshStandardMaterial({ color: 0x83eaff, emissive: 0x208bad, emissiveIntensity: 1.2 }),
      );
      aperture.position.x = 0.4;
      body.add(aperture);
    }
    return body;
  }

  private async attachAsset(component: TeachingComponent, group: Group): Promise<void> {
    try {
      const manifest = await this.manifestPromise;
      const entry = manifest.assets.find((asset) => asset.kind === component.kind);
      if (!entry) {
        group.userData.assetState = "fallback";
        return;
      }
      const url = new URL(`assets/teaching/${entry.file}`, window.location.href).href;
      let load = this.assetCache.get(url);
      if (!load) {
        load = this.loader.loadAsync(url).then((gltf) => gltf.scene);
        this.assetCache.set(url, load);
      }
      const source = await load;
      if (this.disposed || this.groups.get(component.component_id) !== group) {
        return;
      }
      const model = source.clone(true);
      prepareMesh(model);
      const dimensions = housingSize(component, entry.housing_mm);
      fitAssetToHousing(model, dimensions, entry.anchor);
      clearFallback(group);
      group.add(model);
      group.userData.assetState = "glb";
      this.renderOnce();
    } catch (error) {
      if (!this.disposed) {
        group.userData.assetState = "fallback";
        this.options.onAssetIssue(`${component.label}: GLB 加载失败，已使用程序几何。`);
        console.warn("Teaching GLB load failed", { kind: component.kind, error });
      }
    }
  }

  private loadManifest(): Promise<AssetManifest> {
    const url = new URL("assets/teaching/assets-manifest.json", window.location.href);
    return fetch(url)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Asset manifest responded with ${response.status}.`);
        }
        return response.json() as Promise<AssetManifest>;
      })
      .catch((error) => {
        this.options.onAssetIssue("Teaching 3D 资产清单无法读取，将使用程序几何。");
        console.warn("Teaching asset manifest unavailable", error);
        return { schema_version: 1, assets: [] };
      });
  }

  private updateSelection(): void {
    for (const [id, outline] of this.outlines) {
      const selected = id === this.selectedId;
      outline.visible = selected;
      if (selected) {
        const group = this.groups.get(id);
        if (group) {
          outline.setFromObject(group);
        }
      }
    }

    if (this.selectedId && this.groups.has(this.selectedId)) {
      this.activeGroup = this.groups.get(this.selectedId) ?? null;
      if (!this.activeGroup) {
        this.transform.detach();
        return;
      }
      if (!this.outlines.has(this.selectedId)) {
        const outline = new ThreeBoxHelper(this.activeGroup, 0x56d9fa);
        outline.material.transparent = true;
        outline.material.opacity = 0.9;
        outline.material.depthTest = false;
        this.outlines.set(this.selectedId, outline);
        this.helperRoot.add(outline);
      }
      this.outlines.get(this.selectedId)!.visible = true;
      if (this.transform.object !== this.activeGroup) {
        this.transform.attach(this.activeGroup);
      }
      return;
    }

    this.activeGroup = null;
    this.transform.detach();
  }

  setPreview(preview: TeachingPreview | null): void {
    for (const child of [...this.previewRays.children]) { this.previewRays.remove(child); disposeTree(child); }
    if (preview?.source === 'geometry_preview') for (const segment of preview.rays) {
      const ray = new Line(geometryForLine([
        new Vector3(...teachingToRender(segment.start_teaching_mm)),
        new Vector3(...teachingToRender(segment.end_teaching_mm)),
      ]), new LineBasicMaterial({ color: RAY_COLOR, transparent: true, opacity: segment.power_fraction === 1 ? 0.9 : 0.38 }));
      this.previewRays.add(ray);
    }
    this.renderOnce();
  }

  setAxisHeight(heightMm: number): void {
    if (!Number.isFinite(heightMm) || heightMm === this.axisHeightMm) return;
    this.axisHeightMm = heightMm;
    const axis = this.scene.getObjectByName('Teaching optical axis');
    if (axis) axis.position.y = heightMm - 25;
    this.resetView();
  }

  poseAt(x:number,y:number):TeachingPose|null {
    const bounds=this.canvas.getBoundingClientRect();
    this.pointer.set(((x-bounds.left)/bounds.width)*2-1,-((y-bounds.top)/bounds.height)*2+1);
    this.raycaster.setFromCamera(this.pointer,this.camera);
    // Original QML picks an object, falling back to 0.5 units from clipNear.
    const hit=this.raycaster.intersectObjects([...this.groups.values()],true)[0]?.point
      ?? new Vector3(this.pointer.x,this.pointer.y,-1).unproject(this.camera).addScaledVector(this.raycaster.ray.direction,.5);
    return {x_mm:Math.max(0,Math.min(BOARD_LENGTH_MM,hit.x)),y_mm:Math.max(-BOARD_WIDTH_MM/2,Math.min(BOARD_WIDTH_MM/2,-hit.z)),z_mm:this.axisHeightMm,yaw_rad:0,pitch_rad:0,roll_rad:0};
  }

  private onCanvasClick = (event: MouseEvent): void => {
    if (this.skipCanvasSelection) {
      this.skipCanvasSelection = false;
      return;
    }
    const bounds = this.canvas.getBoundingClientRect();
    this.pointer.set(
      ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const intersections = this.raycaster.intersectObjects([...this.groups.values()], true);
    const componentId = intersections
      .map((hit) => findComponentId(hit.object))
      .find((value): value is string => Boolean(value)) ?? null;
    this.options.onSelect(componentId);
  };

  private onObjectChange = (): void => {
    if (!this.activeGroup) {
      return;
    }
    const componentId = String(this.activeGroup.userData.componentId ?? "");
    const component = this.componentById.get(componentId);
    if (!component) {
      return;
    }
    const pose = renderTransformToTeachingPose(
      [this.activeGroup.position.x, this.activeGroup.position.y, this.activeGroup.position.z],
      [this.activeGroup.quaternion.x, this.activeGroup.quaternion.y, this.activeGroup.quaternion.z, this.activeGroup.quaternion.w],
      1,
      component.kind,
    );
    pose.z_mm = Math.max(0, pose.z_mm);
    this.options.onPoseChange(componentId, pose);
  };

  private onDraggingChanged = (event: { value: unknown }): void => {
    this.orbit.enabled = !Boolean(event.value);
  };

  private onTransformMouseDown = (): void => {
    this.skipCanvasSelection = true;
    this.options.onDragStart?.();
  };

  private onTransformMouseUp = (): void => {
    this.options.onDragEnd?.();
    window.setTimeout(() => {
      this.skipCanvasSelection = false;
    }, 0);
  };

  private resize = (): void => {
    if (this.disposed) {
      return;
    }
    const bounds = this.canvas.parentElement?.getBoundingClientRect();
    if (!bounds || bounds.width <= 0 || bounds.height <= 0) {
      return;
    }
    this.camera.aspect = bounds.width / bounds.height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(bounds.width, bounds.height, false);
    this.renderOnce();
  };

  private renderOnce = (): void => {
    if (!this.disposed) {
      this.renderer.render(this.scene, this.camera);
    }
  };

  private renderLoop = (): void => {
    if (this.disposed) {
      return;
    }
    this.orbit.update();
    for (const outline of this.outlines.values()) {
      if (outline.visible) {
        outline.update();
      }
    }
    this.renderer.render(this.scene, this.camera);
    window.requestAnimationFrame(this.renderLoop);
  };
}

function geometryForLine(points: Vector3[]): BufferGeometry {
  return new BufferGeometry().setFromPoints(points);
}

function createBreadboardTexture(): CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = BOARD_LENGTH_MM * 2;
  canvas.height = BOARD_WIDTH_MM * 2;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("无法创建实验台纹理画布。");
  }

  context.fillStyle = "#D5DAE0";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = "#9AA4AF";
  context.lineWidth = 2;
  context.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);

  const pitch = 25;
  const scale = 2;
  const countersinkRadius = 3.6 * scale;
  const holeRadius = 2.6 * scale;
  for (let xIndex = 0; xIndex < BOARD_LENGTH_MM / pitch; xIndex += 1) {
    const x = (pitch / 2 + xIndex * pitch) * scale;
    for (let zIndex = 0; zIndex < BOARD_WIDTH_MM / pitch; zIndex += 1) {
      const y = (pitch / 2 + zIndex * pitch) * scale;
      context.beginPath();
      context.fillStyle = "#8B96A2";
      context.ellipse(x, y, countersinkRadius, countersinkRadius, 0, 0, Math.PI * 2);
      context.fill();
      context.beginPath();
      context.fillStyle = "#59636E";
      context.ellipse(x, y, holeRadius, holeRadius, 0, 0, Math.PI * 2);
      context.fill();
    }
  }

  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function housingSize(
  component: TeachingComponent,
  fallback: readonly [number, number, number],
): [number, number, number] {
  const dimensions = [...fallback] as [number, number, number];
  const centerThickness = Number(component.params.center_thickness_mm);
  const diameter = Number(component.params.diameter_mm);
  if ((component.kind === "lens" || component.kind === "cylindrical_lens") && Number.isFinite(centerThickness) && centerThickness > 0) {
    dimensions[0] = centerThickness;
  }
  if (Number.isFinite(diameter) && diameter > 0 && component.kind !== "fiber") {
    dimensions[1] = diameter;
    dimensions[2] = diameter;
  }
  return dimensions;
}

function fitAssetToHousing(
  model: Object3D,
  housingMm: readonly [number, number, number],
  anchor: AssetManifestEntry["anchor"],
): void {
  model.updateMatrixWorld(true);
  const bounds = new Box3().setFromObject(model);
  const minimum = bounds.min;
  const maximum = bounds.max;
  const size = bounds.getSize(new Vector3());
  if (size.x < 1e-6 || size.y < 1e-6 || size.z < 1e-6) {
    throw new Error("GLB has an empty or degenerate bounding box.");
  }
  const scaleX = housingMm[0] / size.x;
  const scaleY = housingMm[1] / size.y;
  const scaleZ = housingMm[2] / size.z;
  const offsetX = anchor === "output_face"
    ? -maximum.x * scaleX
    : anchor === "input_face"
      ? -minimum.x * scaleX
      : -0.5 * (minimum.x + maximum.x) * scaleX;
  const offsetY = -0.5 * (minimum.y + maximum.y) * scaleY;
  const offsetZ = anchor === "top"
    ? -maximum.z * scaleZ
    : anchor === "bottom"
      ? -minimum.z * scaleZ
      : -0.5 * (minimum.z + maximum.z) * scaleZ;
  model.scale.set(scaleX, scaleY, scaleZ);
  model.position.set(offsetX, offsetY, offsetZ);
}

function prepareMesh(root: Object3D): void {
  root.traverse((object) => {
    if (object instanceof Mesh) {
      object.castShadow = false;
      object.receiveShadow = false;
      object.frustumCulled = true;
    }
  });
}

function clearFallback(group: Group): void {
  for (const child of [...group.children]) {
    if (child.userData.generatedFallback) {
      group.remove(child);
      disposeTree(child);
    }
  }
}

function disposeFallback(group: Group): void {
  for (const child of [...group.children]) {
    if (child.userData.generatedFallback) {
      disposeTree(child);
    }
  }
}

function disposeTree(root: Object3D): void {
  root.traverse((object) => {
    if (object instanceof Mesh || object instanceof Line) {
      object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        material.dispose();
      }
    }
  });
}

function findComponentId(object: Object3D): string | null {
  let current: Object3D | null = object;
  while (current) {
    if (typeof current.userData.componentId === "string") {
      return current.userData.componentId;
    }
    current = current.parent;
  }
  return null;
}
