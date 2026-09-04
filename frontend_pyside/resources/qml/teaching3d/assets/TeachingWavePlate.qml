import QtQuick
import QtQuick3D
Node {
    // Disk radius ≈ 17 (scale 0.34 × mesh radius 50).  Clamps sit on that rim
    // so the optic never reads as a free-floating chip above the post.
    Model {
        source: "#Cylinder"
        eulerRotation.z: 90
        scale: Qt.vector3d(0.34, 0.04, 0.34)
        materials: PrincipledMaterial {
            baseColor: "#87D5DF"; opacity: 0.42; alphaMode: PrincipledMaterial.Blend
            roughness: 0.08; cullMode: Material.NoCulling
        }
    }
    Model { source:"#Cube"; position:Qt.vector3d(0, 19, 0); scale:Qt.vector3d(0.09,0.08,0.40); materials:frameMaterial }
    Model { source:"#Cube"; position:Qt.vector3d(0,-19, 0); scale:Qt.vector3d(0.09,0.08,0.40); materials:frameMaterial }
    Model { source:"#Cube"; position:Qt.vector3d(0,  0, 19); scale:Qt.vector3d(0.09,0.40,0.08); materials:frameMaterial }
    Model { source:"#Cube"; position:Qt.vector3d(0,  0,-19); scale:Qt.vector3d(0.09,0.40,0.08); materials:frameMaterial }
    Model { source:"#Cube";     position:Qt.vector3d(0,-28,0); scale:Qt.vector3d(0.14,0.12,0.22); materials:frameMaterial }
    Model { source:"#Cylinder"; position:Qt.vector3d(0,-43,0); scale:Qt.vector3d(0.065,0.16,0.065); materials:postMaterial }
    Model { source:"#Cube";     position:Qt.vector3d(0,-57,0); scale:Qt.vector3d(0.32,0.08,0.28); materials:baseMaterial }

    PrincipledMaterial { id: frameMaterial; baseColor:"#2A343C"; metalness:0.50; roughness:0.42 }
    PrincipledMaterial { id: postMaterial; baseColor:"#99A7B1"; metalness:0.64; roughness:0.35 }
    PrincipledMaterial { id: baseMaterial; baseColor:"#36424B"; metalness:0.40; roughness:0.52 }
}
