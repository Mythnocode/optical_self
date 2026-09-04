import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cube"; scale:Qt.vector3d(0.40,0.35,0.40); materials:PrincipledMaterial{baseColor:"#8294A1";metalness:0.28;roughness:0.62} }
    Model { source:"#Cube"; position:Qt.vector3d(0,-26.5,0); scale:Qt.vector3d(0.16,0.19,0.16); materials:PrincipledMaterial{baseColor:"#33404A";metalness:0.46;roughness:0.48} }
    Model { source:"#Cylinder"; position:Qt.vector3d(0,-43,0); scale:Qt.vector3d(0.065,0.14,0.065); materials:PrincipledMaterial{baseColor:"#9AA7B1";metalness:0.62;roughness:0.36} }
    Model { source:"#Cube"; position:Qt.vector3d(0,-57,0); scale:Qt.vector3d(0.30,0.08,0.28); materials:PrincipledMaterial{baseColor:"#35414A";metalness:0.40;roughness:0.52} }
}
