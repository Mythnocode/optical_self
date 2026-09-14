using System;
using System.Collections.Generic;
using UnityEngine;

namespace OpticalBenchPrototype
{
    public enum OpticalComponentKind { Laser, Mirror, Splitter, Lens, Fiber, PowerMeter }

    public sealed class OpticalBenchBootstrap : MonoBehaviour
    {
        private readonly List<OpticalComponent> components = new List<OpticalComponent>();
        private readonly List<BeamSegment> baseSegments = new List<BeamSegment>();
        private BeamVisualSystem beams;
        private BenchCameraController cameraController;
        private OpticalComponent selected;
        private bool rotateMode;
        private int loadMultiplier = 1;
        private float frameTime;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void CreatePrototype()
        {
            if (FindObjectOfType<OpticalBenchBootstrap>() != null) return;
            new GameObject("Optical Bench Prototype").AddComponent<OpticalBenchBootstrap>();
        }

        private void Start()
        {
            Application.targetFrameRate = 120;
            QualitySettings.vSyncCount = 0;
            CreateCamera();
            CreateLighting();
            CreateBench();
            CreateComponents();
            beams = new GameObject("Beam Visual System").AddComponent<BeamVisualSystem>();
            RebuildBeams();
        }

        private void Update()
        {
            frameTime = Mathf.Lerp(frameTime, Time.unscaledDeltaTime, 0.1f);
            if (Input.GetKeyDown(KeyCode.R)) rotateMode = !rotateMode;
            if (Input.GetKeyDown(KeyCode.B))
            {
                loadMultiplier = loadMultiplier == 1 ? 25 : loadMultiplier == 25 ? 100 : 1;
                RebuildBeams();
            }
            HandleSelectionAndDrag();
        }

        private void CreateCamera()
        {
            GameObject cameraObject = new GameObject("Bench Camera");
            Camera camera = cameraObject.AddComponent<Camera>();
            camera.nearClipPlane = 0.01f;
            camera.farClipPlane = 100f;
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.025f, 0.04f, 0.06f);
            cameraController = cameraObject.AddComponent<BenchCameraController>();
            cameraController.Target = new Vector3(0f, 0.05f, 0.15f);
        }

        private static void CreateLighting()
        {
            GameObject lightObject = new GameObject("Key Light");
            Light light = lightObject.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.1f;
            light.color = new Color(0.76f, 0.86f, 1f);
            lightObject.transform.rotation = Quaternion.Euler(52f, -28f, 0f);
        }

        private static void CreateBench()
        {
            Material top = MaterialFor(new Color(0.10f, 0.14f, 0.17f), 0.15f);
            GameObject bench = GameObject.CreatePrimitive(PrimitiveType.Cube);
            bench.name = "Optical Table";
            bench.transform.localScale = new Vector3(2.0f, 0.08f, 1.05f);
            bench.transform.position = new Vector3(0f, -0.06f, 0.15f);
            bench.GetComponent<Renderer>().material = top;

            Material grid = MaterialFor(new Color(0.18f, 0.25f, 0.29f), 0.1f);
            for (int x = -9; x <= 9; x++)
            for (int z = -4; z <= 5; z++)
            {
                GameObject hole = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
                hole.transform.position = new Vector3(x * 0.1f, -0.014f, z * 0.1f + 0.15f);
                hole.transform.localScale = new Vector3(0.006f, 0.002f, 0.006f);
                hole.GetComponent<Renderer>().material = grid;
            }
        }

        private void CreateComponents()
        {
            AddComponent(OpticalComponentKind.Laser, "Laser", new Vector3(-0.78f, 0.08f, 0.15f));
            AddComponent(OpticalComponentKind.Mirror, "M1", new Vector3(-0.38f, 0.08f, 0.15f));
            AddComponent(OpticalComponentKind.Splitter, "BS1", new Vector3(-0.04f, 0.08f, 0.15f));
            AddComponent(OpticalComponentKind.Lens, "L1", new Vector3(0.30f, 0.08f, 0.15f));
            AddComponent(OpticalComponentKind.Fiber, "Fiber", new Vector3(0.70f, 0.08f, 0.15f));
            AddComponent(OpticalComponentKind.PowerMeter, "Monitor", new Vector3(-0.04f, 0.08f, 0.56f));

            Connect(0, 1, 1f); Connect(1, 2, 1f); Connect(2, 3, 0.95f);
            Connect(3, 4, 0.95f); Connect(2, 5, 0.05f);
        }

        private void AddComponent(OpticalComponentKind kind, string label, Vector3 position)
        {
            GameObject root = new GameObject(label);
            root.transform.position = position;
            OpticalComponent component = root.AddComponent<OpticalComponent>();
            component.Kind = kind;
            component.DisplayName = label;
            component.Changed += RebuildBeams;
            component.BuildVisual();
            components.Add(component);
        }

        private void Connect(int start, int end, float power)
        {
            baseSegments.Add(new BeamSegment(components[start], components[end], power));
        }

        private void HandleSelectionAndDrag()
        {
            if (Input.GetMouseButtonDown(0))
            {
                Ray ray = Camera.main.ScreenPointToRay(Input.mousePosition);
                if (Physics.Raycast(ray, out RaycastHit hit))
                {
                    OpticalComponent component = hit.collider.GetComponentInParent<OpticalComponent>();
                    if (component != null) SetSelected(component);
                }
            }
            if (!Input.GetMouseButton(0) || selected == null) return;
            if (rotateMode)
            {
                selected.transform.Rotate(Vector3.up, Input.GetAxis("Mouse X") * 110f * Time.unscaledDeltaTime, Space.World);
                selected.NotifyChanged();
                return;
            }
            Plane plane = new Plane(Vector3.up, new Vector3(0f, 0.08f, 0f));
            Ray ray = Camera.main.ScreenPointToRay(Input.mousePosition);
            if (plane.Raycast(ray, out float distance))
            {
                Vector3 point = ray.GetPoint(distance);
                selected.transform.position = new Vector3(Mathf.Clamp(point.x, -0.9f, 0.9f), 0.08f, Mathf.Clamp(point.z, -0.25f, 0.7f));
                selected.NotifyChanged();
            }
        }

        private void SetSelected(OpticalComponent component)
        {
            if (selected != null) selected.SetSelected(false);
            selected = component;
            selected.SetSelected(true);
        }

        private void RebuildBeams()
        {
            if (beams == null) return;
            beams.Rebuild(baseSegments, loadMultiplier);
        }

        private void OnGUI()
        {
            GUIStyle title = new GUIStyle(GUI.skin.label) { fontSize = 22, fontStyle = FontStyle.Bold, normal = { textColor = Color.white } };
            GUIStyle text = new GUIStyle(GUI.skin.label) { fontSize = 14, normal = { textColor = new Color(0.78f, 0.88f, 0.94f) } };
            GUI.Label(new Rect(22, 18, 500, 30), "Optical Bench GPU Prototype", title);
            GUI.Label(new Rect(22, 52, 700, 24), $"{1f / Mathf.Max(frameTime, 0.0001f):F0} FPS   |   Beam load: {loadMultiplier}x   |   Selected: {(selected == null ? "none" : selected.DisplayName)}", text);
            GUI.Label(new Rect(22, 78, 900, 24), "Right drag: orbit   Middle drag: pan   Wheel: zoom   Left drag: move   R: rotate mode   B: beam load", text);
        }

        public static Material MaterialFor(Color color, float metallic)
        {
            Material material = new Material(Shader.Find("Standard"));
            material.color = color;
            material.SetFloat("_Metallic", metallic);
            material.SetFloat("_Glossiness", 0.55f);
            return material;
        }
    }

    public readonly struct BeamSegment
    {
        public readonly OpticalComponent Start;
        public readonly OpticalComponent End;
        public readonly float Power;
        public BeamSegment(OpticalComponent start, OpticalComponent end, float power) { Start = start; End = end; Power = power; }
    }
}
