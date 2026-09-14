using System;
using UnityEngine;

namespace OpticalBenchPrototype
{
    public sealed class OpticalComponent : MonoBehaviour
    {
        public OpticalComponentKind Kind;
        public string DisplayName;
        public event Action Changed;
        private Renderer[] renderers;
        private Material selectedMaterial;
        private Material normalMaterial;

        public void BuildVisual()
        {
            normalMaterial = OpticalBenchBootstrap.MaterialFor(BaseColor(), 0.35f);
            selectedMaterial = OpticalBenchBootstrap.MaterialFor(new Color(0.12f, 0.75f, 1f), 0.5f);
            GameObject baseObject = Primitive(PrimitiveType.Cylinder, "Mount", new Vector3(0f, -0.055f, 0f), new Vector3(0.12f, 0.04f, 0.12f), OpticalBenchBootstrap.MaterialFor(new Color(0.14f, 0.16f, 0.18f), 0.5f));
            baseObject.transform.SetParent(transform, false);
            GameObject body;
            switch (Kind)
            {
                case OpticalComponentKind.Laser:
                    body = Primitive(PrimitiveType.Cylinder, "Laser Body", new Vector3(0f, 0.02f, 0f), new Vector3(0.13f, 0.22f, 0.13f), normalMaterial);
                    break;
                case OpticalComponentKind.Mirror:
                    body = Primitive(PrimitiveType.Cylinder, "Mirror", new Vector3(0f, 0.08f, 0f), new Vector3(0.13f, 0.018f, 0.13f), normalMaterial);
                    body.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
                    break;
                case OpticalComponentKind.Splitter:
                    body = Primitive(PrimitiveType.Cube, "Beam Splitter", new Vector3(0f, 0.07f, 0f), new Vector3(0.12f, 0.12f, 0.12f), normalMaterial);
                    body.transform.localRotation = Quaternion.Euler(0f, 45f, 0f);
                    break;
                case OpticalComponentKind.Lens:
                    body = Primitive(PrimitiveType.Sphere, "Lens", new Vector3(0f, 0.10f, 0f), new Vector3(0.09f, 0.18f, 0.035f), normalMaterial);
                    break;
                case OpticalComponentKind.Fiber:
                    body = Primitive(PrimitiveType.Cylinder, "Fiber Stage", new Vector3(0f, 0.07f, 0f), new Vector3(0.16f, 0.12f, 0.16f), normalMaterial);
                    break;
                default:
                    body = Primitive(PrimitiveType.Cube, "Power Meter", new Vector3(0f, 0.06f, 0f), new Vector3(0.15f, 0.12f, 0.10f), normalMaterial);
                    break;
            }
            body.transform.SetParent(transform, false);
            renderers = GetComponentsInChildren<Renderer>();
        }

        public void NotifyChanged() => Changed?.Invoke();

        public void SetSelected(bool value)
        {
            if (renderers == null) return;
            foreach (Renderer item in renderers)
                if (item.gameObject.name != "Mount") item.material = value ? selectedMaterial : normalMaterial;
        }

        private Color BaseColor()
        {
            switch (Kind)
            {
                case OpticalComponentKind.Laser: return new Color(0.72f, 0.10f, 0.12f);
                case OpticalComponentKind.Mirror: return new Color(0.55f, 0.60f, 0.64f);
                case OpticalComponentKind.Splitter: return new Color(0.15f, 0.54f, 0.70f);
                case OpticalComponentKind.Lens: return new Color(0.08f, 0.48f, 0.70f);
                case OpticalComponentKind.Fiber: return new Color(0.30f, 0.38f, 0.45f);
                default: return new Color(0.20f, 0.46f, 0.24f);
            }
        }

        private static GameObject Primitive(PrimitiveType type, string name, Vector3 position, Vector3 scale, Material material)
        {
            GameObject result = GameObject.CreatePrimitive(type);
            result.name = name;
            result.transform.localPosition = position;
            result.transform.localScale = scale;
            result.GetComponent<Renderer>().material = material;
            return result;
        }
    }
}
