import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cube"; position:Qt.vector3d(-20,0,0); scale:Qt.vector3d(0.46,0.40,0.50); materials:PrincipledMaterial{baseColor:"#5B6F7D";metalness:0.32;roughness:0.56} }
    Model { source:"#Cube"; position:Qt.vector3d(4,0,0); scale:Qt.vector3d(0.035,0.22,0.25); materials:PrincipledMaterial{baseColor:"#16232C";roughness:0.30} }
    Model { source:"#Cube"; position:Qt.vector3d(6,0,0); scale:Qt.vector3d(0.012,0.14,0.16); materials:PrincipledMaterial{baseColor:"#7DC9D4";emissiveFactor:Qt.vector3d(0.02,0.09,0.10);roughness:0.18} }
    Model { source:"#Cube"; position:Qt.vector3d(-20,-27.5,0); scale:Qt.vector3d(0.18,0.15,0.18); materials:PrincipledMaterial{baseColor:"#33404A";metalness:0.46;roughness:0.48} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-20,-44,0); scale:Qt.vector3d(0.07,0.18,0.07); materials:PrincipledMaterial{baseColor:"#9AA6B0";metalness:0.62;roughness:0.36} }
    Model { source:"#Cube"; position:Qt.vector3d(-20,-57,0); scale:Qt.vector3d(0.38,0.08,0.34); materials:PrincipledMaterial{baseColor:"#35414A";metalness:0.40;roughness:0.52} }
}
