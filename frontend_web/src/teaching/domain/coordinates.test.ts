import golden from "../../../../tests/golden/teaching_coordinates.json";
import { describe, expect, it } from "vitest";
import {
  engineToTeaching,
  renderToTeaching,
  renderTransformToTeachingPose,
  teachingOrientationToRenderQuaternion,
  teachingToEngine,
  teachingToRender,
  type QuaternionXyzw,
  type Vec3,
} from "./coordinates.js";
import type { ComponentKind } from "./component-catalog.js";

describe("Teaching coordinate contract", () => {
  it("matches the frozen Python render poses and quaternions", () => {
    for (const item of golden.cases) {
      const position = teachingToRender([item.pose.x_mm, item.pose.y_mm, item.pose.z_mm]);
      const kind = item.kind as ComponentKind;
      const quaternion = teachingOrientationToRenderQuaternion(item.pose, kind);
      expectClose(position, item.render_position);
      expectClose(quaternion, item.render_quaternion_xyzw);
    }
  });

  it("round-trips points between teaching, render, and engine frames", () => {
    const teaching = [72.5, -8.25, 31] as const;
    expectClose(renderToTeaching(teachingToRender(teaching)), teaching);
    expectClose(engineToTeaching(teachingToEngine(teaching)), teaching);
  });

  it("writes a Three transform back into the same teaching pose", () => {
    for (const item of golden.cases) {
      const actual = renderTransformToTeachingPose(
        item.render_position as unknown as Vec3,
        item.render_quaternion_xyzw as unknown as QuaternionXyzw,
        1,
        item.kind as ComponentKind,
      );
      expectClose(
        [actual.x_mm, actual.y_mm, actual.z_mm, actual.yaw_rad, actual.pitch_rad, actual.roll_rad],
        [item.pose.x_mm, item.pose.y_mm, item.pose.z_mm, item.pose.yaw_rad, item.pose.pitch_rad, item.pose.roll_rad],
      );
    }
  });
});

function expectClose(actual: readonly number[], expected: readonly number[]): void {
  expect(actual).toHaveLength(expected.length);
  actual.forEach((value, index) => {
    expect(value).toBeCloseTo(expected[index], 9);
  });
}
