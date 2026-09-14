import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cylinder"; eulerRotation.z:90; scale:Qt.vector3d(0.27,0.04,0.27); materials:PrincipledMaterial{baseColor:"#87D5DF";opacity:0.36;alphaMode:PrincipledMaterial.Blend;roughness:0.08;cullMode:Material.NoCulling} }
    Model { source:"#Cube"; position:Qt.vector3d(0,31,0); scale:Qt.vector3d(0.08,0.08,0.36); materials:PrincipledMaterial{baseColor:"#2A343C";metalness:0.50;roughness:0.42} }
    Model { source:"#Cube"; position:Qt.vector3d(0,-31,0); scale:Qt.vector3d(0.08,0.08,0.36); materials:PrincipledMaterial{baseColor:"#2A343C";metalness:0.50;roughness:0.42} }
    Model { source:"#Cylinder"; position:Qt.vector3d(0,-43,0); scale:Qt.vector3d(0.065,0.14,0.065); materials:PrincipledMaterial{baseColor:"#99A7B1";metalness:0.64;roughness:0.35} }
    Model { source:"#Cube"; position:Qt.vector3d(0,-57,0); scale:Qt.vector3d(0.32,0.08,0.28); materials:PrincipledMaterial{baseColor:"#36424B";metalness:0.40;roughness:0.52} }
}
