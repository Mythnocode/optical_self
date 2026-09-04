import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cube"; position:Qt.vector3d(-20,0,0); scale:Qt.vector3d(0.44,0.36,0.42); materials:PrincipledMaterial{baseColor:"#526674";metalness:0.34;roughness:0.55} }
    Model { source:"#Cylinder"; position:Qt.vector3d(4,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.22,0.08,0.22); materials:PrincipledMaterial{baseColor:"#1B252D";metalness:0.52;roughness:0.32} }
    Model { source:"#Cylinder"; position:Qt.vector3d(9,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.12,0.014,0.12); materials:PrincipledMaterial{baseColor:"#6FCAD6";emissiveFactor:Qt.vector3d(0.02,0.10,0.12);roughness:0.15} }
    Model { source:"#Cube"; position:Qt.vector3d(-20,-26.5,0); scale:Qt.vector3d(0.18,0.17,0.18); materials:PrincipledMaterial{baseColor:"#33404A";metalness:0.46;roughness:0.48} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-20,-44,0); scale:Qt.vector3d(0.07,0.18,0.07); materials:PrincipledMaterial{baseColor:"#9AA6B0";metalness:0.62;roughness:0.36} }
    Model { source:"#Cube"; position:Qt.vector3d(-20,-57,0); scale:Qt.vector3d(0.36,0.08,0.31); materials:PrincipledMaterial{baseColor:"#35414A";metalness:0.40;roughness:0.52} }
}
