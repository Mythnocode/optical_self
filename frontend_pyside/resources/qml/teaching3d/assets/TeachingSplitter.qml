import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cube"; scale:Qt.vector3d(0.30,0.30,0.30); materials:PrincipledMaterial{baseColor:"#A8E0EA";opacity:0.30;alphaMode:PrincipledMaterial.Blend;roughness:0.08;cullMode:Material.NoCulling} }
    Model { source:"#Cube"; eulerRotation.y:45; scale:Qt.vector3d(0.015,0.28,0.39); materials:PrincipledMaterial{baseColor:"#7C3AED";opacity:0.34;alphaMode:PrincipledMaterial.Blend;roughness:0.10;cullMode:Material.NoCulling} }
    Model { source:"#Cube"; position:Qt.vector3d(0,-24,0); scale:Qt.vector3d(0.16,0.19,0.16); materials:PrincipledMaterial{baseColor:"#28343D";metalness:0.48;roughness:0.46} }
    Model { source:"#Cube"; position:Qt.vector3d(0,-38,0); scale:Qt.vector3d(0.45,0.09,0.38); materials:PrincipledMaterial{baseColor:"#313D47";metalness:0.45;roughness:0.50} }
    Model { source:"#Cylinder"; position:Qt.vector3d(0,-48,0); scale:Qt.vector3d(0.07,0.11,0.07); materials:PrincipledMaterial{baseColor:"#98A5AF";metalness:0.66;roughness:0.34} }
    Model { source:"#Cube"; position:Qt.vector3d(0,-57,0); scale:Qt.vector3d(0.34,0.08,0.30); materials:PrincipledMaterial{baseColor:"#3D4953";metalness:0.42;roughness:0.52} }
}
