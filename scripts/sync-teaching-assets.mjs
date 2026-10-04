import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, extname, join, resolve } from "node:path";

const repositoryRoot = process.cwd();
const sourceDirectory = resolve(
  repositoryRoot,
  process.argv[2] ?? "frontend_pyside/features/teaching_v2/assets",
);
const destinationDirectory = resolve(
  repositoryRoot,
  process.argv[3] ?? "frontend_web/public/assets/teaching",
);
const manifestPath = join(destinationDirectory, "assets-manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));

await mkdir(destinationDirectory, { recursive: true });
let externalizedImages = 0;

for (const asset of manifest.assets) {
  const inputPath = join(sourceDirectory, asset.file);
  const outputPath = join(destinationDirectory, asset.file);
  const chunks = parseGlb(await readFile(inputPath), asset.file);

  for (let index = 0; index < (chunks.document.images ?? []).length; index += 1) {
    const image = chunks.document.images[index];
    if (image.bufferView === undefined) {
      continue;
    }
    const bufferView = chunks.document.bufferViews?.[image.bufferView];
    if (!bufferView || bufferView.buffer !== 0 || !chunks.binary) {
      throw new Error(`${asset.file} has an unsupported embedded image buffer view.`);
    }
    const mimeType = image.mimeType;
    const extension = extensionForMimeType(mimeType, asset.file);
    const start = bufferView.byteOffset ?? 0;
    const end = start + bufferView.byteLength;
    if (end > chunks.binary.byteLength) {
      throw new Error(`${asset.file} image ${index} exceeds the binary chunk.`);
    }
    const textureFile = `${basename(asset.file, extname(asset.file))}-texture-${index + 1}.${extension}`;
    await writeFile(join(destinationDirectory, textureFile), chunks.binary.subarray(start, end));
    image.uri = textureFile;
    delete image.bufferView;
    externalizedImages += 1;
  }

  await writeFile(outputPath, encodeGlb(chunks));
}

console.log(`Synced ${manifest.assets.length} Teaching GLBs; externalized ${externalizedImages} embedded textures.`);

function parseGlb(bytes, file) {
  if (bytes.toString("ascii", 0, 4) !== "glTF" || bytes.readUInt32LE(4) !== 2) {
    throw new Error(`${file} is not a GLB 2.0 file.`);
  }
  if (bytes.readUInt32LE(8) !== bytes.byteLength) {
    throw new Error(`${file} has an invalid total length.`);
  }

  const chunks = [];
  let offset = 12;
  while (offset + 8 <= bytes.byteLength) {
    const length = bytes.readUInt32LE(offset);
    const type = bytes.toString("ascii", offset + 4, offset + 8);
    const start = offset + 8;
    const end = start + length;
    if (end > bytes.byteLength) {
      throw new Error(`${file} contains an invalid ${type} chunk.`);
    }
    chunks.push({ type, data: bytes.subarray(start, end) });
    offset = end;
  }

  const jsonChunk = chunks.find((chunk) => chunk.type === "JSON");
  if (!jsonChunk) {
    throw new Error(`${file} has no JSON chunk.`);
  }
  return {
    chunks,
    document: JSON.parse(jsonChunk.data.toString("utf8")),
    binary: chunks.find((chunk) => chunk.type === "BIN\0")?.data,
  };
}

function encodeGlb(parsed) {
  const encodedChunks = parsed.chunks.map((chunk) => {
    if (chunk.type !== "JSON") {
      return chunk;
    }
    const json = Buffer.from(JSON.stringify(parsed.document), "utf8");
    const padding = (4 - (json.byteLength % 4)) % 4;
    return { type: chunk.type, data: Buffer.concat([json, Buffer.alloc(padding, 0x20)]) };
  });

  const chunkBytes = encodedChunks.map(({ type, data }) => {
    const header = Buffer.alloc(8);
    header.writeUInt32LE(data.byteLength, 0);
    header.write(type, 4, 4, "ascii");
    return Buffer.concat([header, data]);
  });
  const length = 12 + chunkBytes.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const header = Buffer.alloc(12);
  header.write("glTF", 0, 4, "ascii");
  header.writeUInt32LE(2, 4);
  header.writeUInt32LE(length, 8);
  return Buffer.concat([header, ...chunkBytes]);
}

function extensionForMimeType(mimeType, file) {
  const extensions = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
  };
  const extension = extensions[mimeType];
  if (!extension) {
    throw new Error(`${file} uses an unsupported embedded texture type: ${mimeType ?? "unknown"}.`);
  }
  return extension;
}
