import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cylinder"; eulerRotation.z:90; scale:Qt.vector3d(0.31,0.045,0.31); materials:PrincipledMaterial{baseColor:"#DDE4EA";metalness:0.92;roughness:0.12} }
    Model { source:"#Cube"; position:Qt.vector3d(-8,0,0); scale:Qt.vector3d(0.12,0.48,0.43); materials:PrincipledMaterial{baseColor:"#252E36";metalness:0.52;roughness:0.42} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-12,25,18); eulerRotation.x:90; scale:Qt.vector3d(0.045,0.11,0.045); materials:PrincipledMaterial{baseColor:"#66747E";metalness:0.45;roughness:0.38} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-12,-3,24); eulerRotation.x:90; scale:Qt.vector3d(0.045,0.14,0.045); materials:PrincipledMaterial{baseColor:"#66747E";metalness:0.45;roughness:0.38} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-12,31,29); eulerRotation.x:90; scale:Qt.vector3d(0.075,0.16,0.075); materials:PrincipledMaterial{baseColor:"#11181E";roughness:0.40} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-12,-5,38); eulerRotation.x:90; scale:Qt.vector3d(0.075,0.16,0.075); materials:PrincipledMaterial{baseColor:"#11181E";roughness:0.40} }
    Model { source:"#Cube"; position:Qt.vector3d(-12,-30,0); scale:Qt.vector3d(0.16,0.12,0.16); materials:PrincipledMaterial{baseColor:"#2C3740";metalness:0.50;roughness:0.44} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-12,-43,0); scale:Qt.vector3d(0.075,0.14,0.075); materials:PrincipledMaterial{baseColor:"#98A6B1";metalness:0.68;roughness:0.34} }
    Model { source:"#Cube"; position:Qt.vector3d(-12,-57,0); scale:Qt.vector3d(0.35,0.08,0.30); materials:PrincipledMaterial{baseColor:"#394650";metalness:0.42;roughness:0.52} }
}
