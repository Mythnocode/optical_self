import QtQuick
import QtQuick3D
Node {
    // Cylindrical optic: thin plate in YZ.  Clamps grip the short edges.
    Model {
        source: "#Cube"
        scale: Qt.vector3d(0.055, 0.34, 0.22)
        materials: PrincipledMaterial {
            baseColor: "#7CD3E0"; opacity: 0.40; alphaMode: PrincipledMaterial.Blend
            roughness: 0.08; cullMode: Material.NoCulling
        }
    }
    Model { source:"#Cube"; position:Qt.vector3d(0, 19, 0); scale:Qt.vector3d(0.08,0.08,0.28); materials:frameMaterial }
    Model { source:"#Cube"; position:Qt.vector3d(0,-19, 0); scale:Qt.vector3d(0.08,0.08,0.28); materials:frameMaterial }
    Model { source:"#Cube";     position:Qt.vector3d(0,-28,0); scale:Qt.vector3d(0.12,0.12,0.20); materials:frameMaterial }
    Model { source:"#Cylinder"; position:Qt.vector3d(0,-43,0); scale:Qt.vector3d(0.06,0.16,0.06); materials:postMaterial }
    Model { source:"#Cube";     position:Qt.vector3d(0,-57,0); scale:Qt.vector3d(0.34,0.08,0.28); materials:baseMaterial }

    PrincipledMaterial { id: frameMaterial; baseColor:"#263039"; metalness:0.50; roughness:0.42 }
    PrincipledMaterial { id: postMaterial; baseColor:"#9AA7B1"; metalness:0.62; roughness:0.36 }
    PrincipledMaterial { id: baseMaterial; baseColor:"#35414A"; metalness:0.40; roughness:0.52 }
}
