using System.Collections.Generic;
using UnityEngine;

namespace OpticalBenchPrototype
{
    public sealed class BeamVisualSystem : MonoBehaviour
    {
        private MeshFilter meshFilter;
        private MeshRenderer meshRenderer;

        private void Awake()
        {
            meshFilter = gameObject.AddComponent<MeshFilter>();
            meshRenderer = gameObject.AddComponent<MeshRenderer>();
            Material material = new Material(Shader.Find("Unlit/Color"));
            material.color = new Color(1f, 0.12f, 0.10f, 0.92f);
            meshRenderer.material = material;
        }

        public void Rebuild(IReadOnlyList<BeamSegment> baseSegments, int multiplier)
        {
            List<Vector3> vertices = new List<Vector3>(baseSegments.Count * multiplier * 4);
            List<int> triangles = new List<int>(baseSegments.Count * multiplier * 6);
            for (int copy = 0; copy < multiplier; copy++)
            {
                float offset = copy == 0 ? 0f : (copy % 10 - 5) * 0.0015f;
                foreach (BeamSegment segment in baseSegments)
                    AddRibbon(vertices, triangles, segment.Start.transform.position + Vector3.up * 0.04f + Vector3.right * offset, segment.End.transform.position + Vector3.up * 0.04f + Vector3.right * offset, segment.Power);
            }
            Mesh mesh = new Mesh { name = "Merged Beam Mesh" };
            if (vertices.Count > 65535) mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
            mesh.SetVertices(vertices);
            mesh.SetTriangles(triangles, 0);
            mesh.RecalculateBounds();
            meshFilter.sharedMesh = mesh;
        }

        private static void AddRibbon(List<Vector3> vertices, List<int> triangles, Vector3 start, Vector3 end, float power)
        {
            Vector3 direction = end - start;
            if (direction.sqrMagnitude < 0.0000001f) return;
            Vector3 widthAxis = Vector3.Cross(direction.normalized, Vector3.up);
            if (widthAxis.sqrMagnitude < 0.001f) widthAxis = Vector3.right;
            float width = Mathf.Lerp(0.004f, 0.012f, Mathf.Clamp01(power));
            widthAxis = widthAxis.normalized * width;
            int index = vertices.Count;
            vertices.Add(start - widthAxis); vertices.Add(start + widthAxis);
            vertices.Add(end + widthAxis); vertices.Add(end - widthAxis);
            triangles.Add(index); triangles.Add(index + 1); triangles.Add(index + 2);
            triangles.Add(index); triangles.Add(index + 2); triangles.Add(index + 3);
        }
    }
}
