import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cylinder"; eulerRotation.z:90; scale:Qt.vector3d(0.30,0.045,0.30); materials:PrincipledMaterial{baseColor:"#1D252B";metalness:0.46;roughness:0.50} }
    Model { source:"#Cylinder"; position:Qt.vector3d(3,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.11,0.012,0.11); materials:PrincipledMaterial{baseColor:"#A8E1EA";opacity:0.10;alphaMode:PrincipledMaterial.Blend;roughness:0.16} }
    // Continuous holder -> clamp -> post -> base chain.
    Model { source:"#Cube"; position:Qt.vector3d(0,-27,0); scale:Qt.vector3d(0.16,0.24,0.16); materials:PrincipledMaterial{baseColor:"#2E3942";metalness:0.48;roughness:0.46} }
    Model { source:"#Cylinder"; position:Qt.vector3d(0,-46,0); scale:Qt.vector3d(0.065,0.14,0.065); materials:PrincipledMaterial{baseColor:"#97A5AF";metalness:0.64;roughness:0.35} }
    Model { source:"#Cube"; position:Qt.vector3d(0,-57,0); scale:Qt.vector3d(0.34,0.08,0.28); materials:PrincipledMaterial{baseColor:"#35414A";metalness:0.40;roughness:0.52} }
    Model { source:"#Cylinder"; position:Qt.vector3d(0,27,27); eulerRotation.x:90; scale:Qt.vector3d(0.045,0.14,0.045); materials:PrincipledMaterial{baseColor:"#11181D";roughness:0.42} }
}
