import QtQuick
import QtQuick3D
Node {
    // Optical origin is at the output aperture (x = 0). Body extends upstream (-X).
    Model { source: "#Cube"; position: Qt.vector3d(-42, 0, 0); scale: Qt.vector3d(0.72,0.34,0.40); materials: PrincipledMaterial { baseColor:"#E7ECEF"; metalness:0.30; roughness:0.38 } }
    Model { source: "#Cylinder"; position: Qt.vector3d(-6,0,0); eulerRotation.z:90; scale: Qt.vector3d(0.20,0.18,0.20); materials: PrincipledMaterial { baseColor:"#202A33"; metalness:0.65; roughness:0.30 } }
    Model { source: "#Cylinder"; position: Qt.vector3d(1,0,0); eulerRotation.z:90; scale: Qt.vector3d(0.095,0.025,0.095); materials: PrincipledMaterial { baseColor:"#D94801"; emissiveFactor:Qt.vector3d(0.8,0.12,0.01); roughness:0.22 } }
    Model { source: "#Cube"; position: Qt.vector3d(-42,-28,0); scale: Qt.vector3d(0.46,0.10,0.30); materials: PrincipledMaterial { baseColor:"#2F3B46"; metalness:0.42; roughness:0.52 } }
    // Simplified mounting structure: the laser body is supported by two posts and a base plate, never floating above the optical table.
    Model { source: "#Cylinder"; position: Qt.vector3d(-56,-43,-17); scale: Qt.vector3d(0.065,0.20,0.065); materials: PrincipledMaterial { baseColor:"#9AA7B1"; metalness:0.62; roughness:0.36 } }
    Model { source: "#Cylinder"; position: Qt.vector3d(-28,-43,17); scale: Qt.vector3d(0.065,0.20,0.065); materials: PrincipledMaterial { baseColor:"#9AA7B1"; metalness:0.62; roughness:0.36 } }
    Model { source: "#Cube"; position: Qt.vector3d(-42,-57,0); scale: Qt.vector3d(0.62,0.08,0.42); materials: PrincipledMaterial { baseColor:"#35414A"; metalness:0.42; roughness:0.52 } }
}
