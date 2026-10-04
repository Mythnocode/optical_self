import { readdir, readFile, writeFile } from "node:fs/promises";
import { basename, extname, join, resolve } from "node:path";

const assetsDirectory = resolve(
  process.cwd(),
  process.argv[2] ?? "frontend_pyside/features/teaching_v2/assets",
);
const outputPath = resolve(
  process.cwd(),
  process.argv[3] ?? "docs/migration/teaching-glb-inventory.md",
);

const files = (await readdir(assetsDirectory))
  .filter((file) => extname(file).toLowerCase() === ".glb")
  .sort((left, right) => left.localeCompare(right));
const rows = [];

for (const file of files) {
  const bytes = await readFile(join(assetsDirectory, file));
  const document = parseGlbJson(bytes, file);
  const bounds = measureSceneBounds(document, file);
  const textures = (document.textures ?? []).length;
  const imageTypes = [...new Set((document.images ?? []).map((image) => image.mimeType ?? "unknown"))];
  rows.push({
    file,
    bytes: bytes.byteLength,
    meshes: (document.meshes ?? []).length,
    textures,
    imageTypes: imageTypes.join(", ") || "—",
    min: bounds?.min,
    max: bounds?.max,
    size: bounds?.size,
  });
}

const lines = [
  "# Teaching GLB inventory",
  "",
  `Captured: ${new Date().toISOString().slice(0, 10)}`,
  `Source: \`${assetsDirectory}\``,
  `Assets: ${rows.length}`,
  "",
  "AABBs include the default glTF scene's node transforms and primitive POSITION accessor bounds. Values use the source mesh coordinate frame; verify units and axis anchors before assigning a renderer manifest entry.",
  "",
  "| Asset | Size | Meshes | Textures | AABB min | AABB max | Dimensions |",
  "|---|---:|---:|---:|---|---|---|",
  ...rows.map((row) => [
    `\`${row.file}\``,
    `${(row.bytes / 1024).toFixed(1)} KiB`,
    String(row.meshes),
    row.textures ? `${row.textures} (${row.imageTypes})` : "0",
    formatVector(row.min),
    formatVector(row.max),
    formatVector(row.size),
  ].join(" | ").replace(/^/, "| ").concat(" |")),
  "",
  "The first Three.js slice copies only breadboard, laser, lens, and fiber. The remaining GLBs stay in the legacy asset directory until their kind, mount anchor, and optical axis are validated in the next asset-migration phase.",
  "",
];

await writeFile(outputPath, lines.join("\n"), "utf8");
console.log(`Inventoried ${rows.length} GLBs -> ${outputPath}`);

function parseGlbJson(bytes, file) {
  if (bytes.toString("ascii", 0, 4) !== "glTF" || bytes.readUInt32LE(4) !== 2) {
    throw new Error(`${basename(file)} is not a GLB 2.0 file.`);
  }
  const jsonLength = bytes.readUInt32LE(12);
  const jsonType = bytes.toString("ascii", 16, 20);
  if (jsonType !== "JSON" || 20 + jsonLength > bytes.byteLength) {
    throw new Error(`${basename(file)} has an invalid JSON chunk.`);
  }
  return JSON.parse(bytes.toString("utf8", 20, 20 + jsonLength));
}

function measureSceneBounds(document, file) {
  const scene = document.scenes?.[document.scene ?? 0] ?? document.scenes?.[0];
  const hasParent = new Set((document.nodes ?? []).flatMap((node) => node.children ?? []));
  const roots = scene?.nodes ?? (document.nodes ?? [])
    .map((_, index) => index)
    .filter((index) => !hasParent.has(index));
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  let found = false;

  const visit = (nodeIndex, parentMatrix, ancestry) => {
    if (ancestry.has(nodeIndex)) {
      throw new Error(`${basename(file)} contains a node cycle.`);
    }
    const node = document.nodes[nodeIndex];
    if (!node) {
      return;
    }
    const world = multiplyMatrices(parentMatrix, nodeMatrix(node));
    if (node.mesh !== undefined) {
      const mesh = document.meshes?.[node.mesh];
      for (const primitive of mesh?.primitives ?? []) {
        const accessorIndex = primitive.attributes?.POSITION;
        const accessor = accessorIndex === undefined ? undefined : document.accessors?.[accessorIndex];
        if (!accessor?.min || !accessor?.max) {
          continue;
        }
        found = true;
        for (let mask = 0; mask < 8; mask += 1) {
          const point = [
            mask & 1 ? accessor.max[0] : accessor.min[0],
            mask & 2 ? accessor.max[1] : accessor.min[1],
            mask & 4 ? accessor.max[2] : accessor.min[2],
          ];
          const transformed = transformPoint(world, point);
          for (let axis = 0; axis < 3; axis += 1) {
            min[axis] = Math.min(min[axis], transformed[axis]);
            max[axis] = Math.max(max[axis], transformed[axis]);
          }
        }
      }
    }
    const nextAncestry = new Set(ancestry).add(nodeIndex);
    for (const child of node.children ?? []) {
      visit(child, world, nextAncestry);
    }
  };

  for (const root of roots) {
    visit(root, identityMatrix(), new Set());
  }
  if (!found) {
    return null;
  }
  return { min, max, size: max.map((value, index) => value - min[index]) };
}

function nodeMatrix(node) {
  if (node.matrix?.length === 16) {
    return node.matrix;
  }
  const [x, y, z, w] = node.rotation ?? [0, 0, 0, 1];
  const [sx, sy, sz] = node.scale ?? [1, 1, 1];
  const [tx, ty, tz] = node.translation ?? [0, 0, 0];
  const x2 = x + x;
  const y2 = y + y;
  const z2 = z + z;
  const xx = x * x2;
  const xy = x * y2;
  const xz = x * z2;
  const yy = y * y2;
  const yz = y * z2;
  const zz = z * z2;
  const wx = w * x2;
  const wy = w * y2;
  const wz = w * z2;
  return [
    (1 - (yy + zz)) * sx, (xy + wz) * sx, (xz - wy) * sx, 0,
    (xy - wz) * sy, (1 - (xx + zz)) * sy, (yz + wx) * sy, 0,
    (xz + wy) * sz, (yz - wx) * sz, (1 - (xx + yy)) * sz, 0,
    tx, ty, tz, 1,
  ];
}

function multiplyMatrices(left, right) {
  const result = new Array(16).fill(0);
  for (let column = 0; column < 4; column += 1) {
    for (let row = 0; row < 4; row += 1) {
      for (let index = 0; index < 4; index += 1) {
        result[column * 4 + row] += left[index * 4 + row] * right[column * 4 + index];
      }
    }
  }
  return result;
}

function transformPoint(matrix, point) {
  const [x, y, z] = point;
  const w = matrix[3] * x + matrix[7] * y + matrix[11] * z + matrix[15];
  const divisor = w && w !== 1 ? w : 1;
  return [
    (matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12]) / divisor,
    (matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13]) / divisor,
    (matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14]) / divisor,
  ];
}

function identityMatrix() {
  return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
}

function formatVector(vector) {
  return vector ? `(${vector.map((value) => Number(value.toFixed(3))).join(", ")})` : "unavailable";
}
