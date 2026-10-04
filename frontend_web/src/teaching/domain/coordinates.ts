import type { TeachingPose } from "./scene-types.js";
import type { ComponentKind } from "./component-catalog.js";

export type Vec3 = readonly [number, number, number];
export type QuaternionXyzw = readonly [number, number, number, number];
export type Matrix3 = readonly [Vec3, Vec3, Vec3];

export const DEFAULT_AXIS_HEIGHT_MM = 25;
export const DEFAULT_RENDER_UNITS_PER_MM = 1;
export const MIRROR_RUNTIME_FOLD_RAD = Math.PI / 4;

const TEACHING_TO_RENDER: Matrix3 = [
  [1, 0, 0],
  [0, 0, 1],
  [0, -1, 0],
];
const RENDER_TO_TEACHING: Matrix3 = [
  [1, 0, 0],
  [0, 0, -1],
  [0, 1, 0],
];

export function teachingToRender(point: Vec3, unitsPerMm = DEFAULT_RENDER_UNITS_PER_MM): Vec3 {
  return [point[0] * unitsPerMm, point[2] * unitsPerMm, -point[1] * unitsPerMm];
}

export function renderToTeaching(point: Vec3, unitsPerMm = DEFAULT_RENDER_UNITS_PER_MM): Vec3 {
  const scale = Math.max(Math.abs(unitsPerMm), 1e-12);
  return [point[0] / scale, -point[2] / scale, point[1] / scale];
}

export function teachingToEngine(point: Vec3, axisHeightMm = DEFAULT_AXIS_HEIGHT_MM): Vec3 {
  return [point[1], point[2] - axisHeightMm, point[0]];
}

export function engineToTeaching(point: Vec3, axisHeightMm = DEFAULT_AXIS_HEIGHT_MM): Vec3 {
  return [point[2], point[0], point[1] + axisHeightMm];
}

export function teachingDirectionToRender(direction: Vec3): Vec3 {
  return [direction[0], direction[2], -direction[1]];
}

export function teachingOrientationToRenderQuaternion(
  pose: Pick<TeachingPose, "yaw_rad" | "pitch_rad" | "roll_rad">,
  kind?: ComponentKind,
): QuaternionXyzw {
  const yaw = pose.yaw_rad + (kind === "mirror" ? MIRROR_RUNTIME_FOLD_RAD : 0);
  const teachingRotation = multiplyMatrix3(
    rotationZ(yaw),
    multiplyMatrix3(rotationY(-pose.pitch_rad), rotationX(pose.roll_rad)),
  );
  const renderRotation = multiplyMatrix3(TEACHING_TO_RENDER, teachingRotation);
  const [w, x, y, z] = quaternionFromMatrix3(renderRotation);
  return [x, y, z, w];
}

export function renderTransformToTeachingPose(
  position: Vec3,
  quaternionXyzw: QuaternionXyzw,
  unitsPerMm = DEFAULT_RENDER_UNITS_PER_MM,
  kind?: ComponentKind,
): TeachingPose {
  const [x, y, z] = renderToTeaching(position, unitsPerMm);
  const [qx, qy, qz, qw] = normalizeQuaternion(quaternionXyzw);
  const renderRotation = matrix3FromQuaternion(qw, qx, qy, qz);
  const teachingRotation = multiplyMatrix3(RENDER_TO_TEACHING, renderRotation);
  let yaw: number;
  let pitch: number;
  let roll: number;
  const sinBeta = clamp(-teachingRotation[2][0], -1, 1);
  const beta = Math.asin(sinBeta);
  const cosBeta = Math.cos(beta);
  if (Math.abs(cosBeta) < 1e-8) {
    yaw = Math.atan2(-teachingRotation[0][1], teachingRotation[1][1]);
    pitch = -beta;
    roll = 0;
  } else {
    yaw = Math.atan2(teachingRotation[1][0], teachingRotation[0][0]);
    pitch = -beta;
    roll = Math.atan2(teachingRotation[2][1], teachingRotation[2][2]);
  }
  if (kind === "mirror") {
    yaw -= MIRROR_RUNTIME_FOLD_RAD;
  }
  return {
    x_mm: x,
    y_mm: y,
    z_mm: z,
    yaw_rad: yaw,
    pitch_rad: pitch,
    roll_rad: roll,
  };
}

export function teachingRotationMatrix(
  pose: Pick<TeachingPose, "yaw_rad" | "pitch_rad" | "roll_rad">,
  kind?: ComponentKind,
): Matrix3 {
  const yaw = pose.yaw_rad + (kind === "mirror" ? MIRROR_RUNTIME_FOLD_RAD : 0);
  return multiplyMatrix3(
    rotationZ(yaw),
    multiplyMatrix3(rotationY(-pose.pitch_rad), rotationX(pose.roll_rad)),
  );
}

function rotationX(angle: number): Matrix3 {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return [[1, 0, 0], [0, cosine, -sine], [0, sine, cosine]];
}

function rotationY(angle: number): Matrix3 {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return [[cosine, 0, sine], [0, 1, 0], [-sine, 0, cosine]];
}

function rotationZ(angle: number): Matrix3 {
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  return [[cosine, -sine, 0], [sine, cosine, 0], [0, 0, 1]];
}

function multiplyMatrix3(left: Matrix3, right: Matrix3): Matrix3 {
  return [0, 1, 2].map((row) => [0, 1, 2].map((column) => (
    left[row][0] * right[0][column]
    + left[row][1] * right[1][column]
    + left[row][2] * right[2][column]
  )) as unknown as Vec3) as unknown as Matrix3;
}

function quaternionFromMatrix3(matrix: Matrix3): readonly [number, number, number, number] {
  const m00 = matrix[0][0];
  const m01 = matrix[0][1];
  const m02 = matrix[0][2];
  const m10 = matrix[1][0];
  const m11 = matrix[1][1];
  const m12 = matrix[1][2];
  const m20 = matrix[2][0];
  const m21 = matrix[2][1];
  const m22 = matrix[2][2];
  const trace = m00 + m11 + m22;
  let w: number;
  let x: number;
  let y: number;
  let z: number;

  if (trace > 0) {
    const scale = Math.sqrt(trace + 1) * 2;
    w = 0.25 * scale;
    x = (m21 - m12) / scale;
    y = (m02 - m20) / scale;
    z = (m10 - m01) / scale;
  } else if (m00 > m11 && m00 > m22) {
    const scale = Math.sqrt(1 + m00 - m11 - m22) * 2;
    w = (m21 - m12) / scale;
    x = 0.25 * scale;
    y = (m01 + m10) / scale;
    z = (m02 + m20) / scale;
  } else if (m11 > m22) {
    const scale = Math.sqrt(1 + m11 - m00 - m22) * 2;
    w = (m02 - m20) / scale;
    x = (m01 + m10) / scale;
    y = 0.25 * scale;
    z = (m12 + m21) / scale;
  } else {
    const scale = Math.sqrt(1 + m22 - m00 - m11) * 2;
    w = (m10 - m01) / scale;
    x = (m02 + m20) / scale;
    y = (m12 + m21) / scale;
    z = 0.25 * scale;
  }
  const normalized = normalizeQuaternion([x, y, z, w]);
  return [normalized[3], normalized[0], normalized[1], normalized[2]];
}

function matrix3FromQuaternion(w: number, x: number, y: number, z: number): Matrix3 {
  const xx = x * x;
  const yy = y * y;
  const zz = z * z;
  const xy = x * y;
  const xz = x * z;
  const yz = y * z;
  const wx = w * x;
  const wy = w * y;
  const wz = w * z;
  return [
    [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
    [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
    [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
  ];
}

function normalizeQuaternion(quaternion: readonly [number, number, number, number]): [number, number, number, number] {
  const length = Math.hypot(...quaternion);
  if (!Number.isFinite(length) || length < 1e-18) {
    throw new Error("Quaternion must contain finite, non-zero values.");
  }
  return quaternion.map((value) => value / length) as [number, number, number, number];
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
