import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cylinder"; position:Qt.vector3d(-16,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.28,0.34,0.28); materials:PrincipledMaterial{baseColor:"#3E4A54";metalness:0.38;roughness:0.50} }
    Model { source:"#Cylinder"; position:Qt.vector3d(2,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.20,0.035,0.20); materials:PrincipledMaterial{baseColor:"#151D23";roughness:0.28} }
    Model { source:"#Cylinder"; position:Qt.vector3d(4,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.12,0.012,0.12); materials:PrincipledMaterial{baseColor:"#7CC5D0";emissiveFactor:Qt.vector3d(0.02,0.08,0.09);roughness:0.18} }
    Model { source:"#Cube"; position:Qt.vector3d(-16,-24.5,0); scale:Qt.vector3d(0.17,0.21,0.17); materials:PrincipledMaterial{baseColor:"#303B44";metalness:0.48;roughness:0.46} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-16,-44,0); scale:Qt.vector3d(0.07,0.18,0.07); materials:PrincipledMaterial{baseColor:"#9BA8B2";metalness:0.65;roughness:0.34} }
    Model { source:"#Cube"; position:Qt.vector3d(-16,-57,0); scale:Qt.vector3d(0.34,0.08,0.30); materials:PrincipledMaterial{baseColor:"#35414A";metalness:0.42;roughness:0.52} }
}
