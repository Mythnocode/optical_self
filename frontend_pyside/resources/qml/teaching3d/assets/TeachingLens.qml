import QtQuick
import QtQuick3D
Node {
    // Optical element.  Qt Quick3D's primitive cylinder is 100 units across
    // (radius 50); scale 0.34 ⇒ clear aperture radius ≈ 17.
    Model {
        source: "#Cylinder"
        eulerRotation.z: 90
        scale: Qt.vector3d(0.34, 0.055, 0.34)
        materials: PrincipledMaterial {
            baseColor: "#6DD5E7"; opacity: 0.42; alphaMode: PrincipledMaterial.Blend
            roughness: 0.08; cullMode: Material.NoCulling
        }
    }

    // Continuous lens cell: inner faces sit just outside the glass rim so the
    // frame visibly grips the optic instead of leaving a hollow floating ring.
    Model { source:"#Cube"; position:Qt.vector3d(0, 20,  0); scale:Qt.vector3d(0.10,0.08,0.42); materials:frameMaterial }
    Model { source:"#Cube"; position:Qt.vector3d(0,-20,  0); scale:Qt.vector3d(0.10,0.08,0.42); materials:frameMaterial }
    Model { source:"#Cube"; position:Qt.vector3d(0,  0, 20); scale:Qt.vector3d(0.10,0.42,0.08); materials:frameMaterial }
    Model { source:"#Cube"; position:Qt.vector3d(0,  0,-20); scale:Qt.vector3d(0.10,0.42,0.08); materials:frameMaterial }

    // Mechanical chain: cell → neck → post → base (foot at local y≈-61).
    Model { source:"#Cube";     position:Qt.vector3d(0,-28,0); scale:Qt.vector3d(0.14,0.12,0.28); materials:frameMaterial }
    Model { source:"#Cylinder"; position:Qt.vector3d(0,-43,0); scale:Qt.vector3d(0.075,0.18,0.075); materials:postMaterial }
    Model { source:"#Cube";     position:Qt.vector3d(0,-57,0); scale:Qt.vector3d(0.40,0.08,0.32); materials:baseMaterial }

    PrincipledMaterial { id: frameMaterial; baseColor:"#222C35"; metalness:0.55; roughness:0.38 }
    PrincipledMaterial { id: postMaterial; baseColor:"#9AA7B2"; metalness:0.65; roughness:0.34 }
    PrincipledMaterial { id: baseMaterial; baseColor:"#3A4650"; metalness:0.40; roughness:0.52 }
}
