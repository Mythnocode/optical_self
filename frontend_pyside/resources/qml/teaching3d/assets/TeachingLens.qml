import QtQuick
import QtQuick3D
Node {
    // Optical element.  Qt Quick3D's primitive cylinder is 100 units across;
    // after the rotation/scale below the clear optic is about 68 units in Y/Z.
    Model {
        source: "#Cylinder"
        eulerRotation.z: 90
        scale: Qt.vector3d(0.34, 0.055, 0.34)
        materials: PrincipledMaterial {
            baseColor: "#6DD5E7"; opacity: 0.42; alphaMode: PrincipledMaterial.Blend
            roughness: 0.08; cullMode: Material.NoCulling
        }
    }

    // Continuous lens cell.  Inner faces sit at roughly +/-32 while the glass
    // radius is ~34, so the frame visibly grips the optic instead of looking
    // like two detached clips beside a floating lens.
    Model { source:"#Cube"; position:Qt.vector3d(0, 36,  0); scale:Qt.vector3d(0.10,0.08,0.80); materials:frameMaterial }
    Model { source:"#Cube"; position:Qt.vector3d(0,-36,  0); scale:Qt.vector3d(0.10,0.08,0.80); materials:frameMaterial }
    Model { source:"#Cube"; position:Qt.vector3d(0,  0, 36); scale:Qt.vector3d(0.10,0.64,0.08); materials:frameMaterial }
    Model { source:"#Cube"; position:Qt.vector3d(0,  0,-36); scale:Qt.vector3d(0.10,0.64,0.08); materials:frameMaterial }

    // Mechanical chain is intentionally continuous and uses the same table
    // mounting datum as the other teaching assets.  The base bottom sits on the
    // optical-table top (world y ~= -9 when the asset root is y=52), so the
    // lens can no longer read as a floating optic or a stand buried in the table.
    Model { source:"#Cube";     position:Qt.vector3d(0,-40,0); scale:Qt.vector3d(0.14,0.10,0.28); materials:frameMaterial }
    Model { source:"#Cylinder"; position:Qt.vector3d(0,-45,0); scale:Qt.vector3d(0.075,0.20,0.075); materials:postMaterial }
    Model { source:"#Cube";     position:Qt.vector3d(0,-57,0); scale:Qt.vector3d(0.40,0.08,0.32); materials:baseMaterial }

    PrincipledMaterial { id: frameMaterial; baseColor:"#222C35"; metalness:0.55; roughness:0.38 }
    PrincipledMaterial { id: postMaterial; baseColor:"#9AA7B2"; metalness:0.65; roughness:0.34 }
    PrincipledMaterial { id: baseMaterial; baseColor:"#3A4650"; metalness:0.40; roughness:0.52 }
}
