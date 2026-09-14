using UnityEngine;

namespace OpticalBenchPrototype
{
    public sealed class BenchCameraController : MonoBehaviour
    {
        public Vector3 Target { get; set; }
        private float yaw = 32f;
        private float pitch = 28f;
        private float distance = 2.5f;
        private Vector3 pan;

        private void Start() => Apply();

        private void Update()
        {
            if (Input.GetMouseButton(1))
            {
                yaw += Input.GetAxis("Mouse X") * 180f * Time.unscaledDeltaTime;
                pitch = Mathf.Clamp(pitch - Input.GetAxis("Mouse Y") * 150f * Time.unscaledDeltaTime, 8f, 82f);
                Apply();
            }
            if (Input.GetMouseButton(2))
            {
                pan -= transform.right * Input.GetAxis("Mouse X") * distance * 0.7f * Time.unscaledDeltaTime;
                pan -= transform.up * Input.GetAxis("Mouse Y") * distance * 0.7f * Time.unscaledDeltaTime;
                Apply();
            }
            float wheel = Input.mouseScrollDelta.y;
            if (Mathf.Abs(wheel) > 0.001f)
            {
                distance = Mathf.Clamp(distance * (wheel > 0f ? 0.87f : 1.15f), 0.65f, 6f);
                Apply();
            }
        }

        private void Apply()
        {
            Quaternion rotation = Quaternion.Euler(pitch, yaw, 0f);
            transform.position = Target + pan - rotation * Vector3.forward * distance;
            transform.rotation = rotation;
        }
    }
}
