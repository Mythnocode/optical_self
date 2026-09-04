import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cylinder"; eulerRotation.z:90; scale:Qt.vector3d(0.29,0.38,0.29); materials:PrincipledMaterial{baseColor:"#303943";metalness:0.55;roughness:0.34} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-20,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.33,0.055,0.33); materials:PrincipledMaterial{baseColor:"#121A20";roughness:0.45} }
    Model { source:"#Cylinder"; position:Qt.vector3d(20,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.33,0.055,0.33); materials:PrincipledMaterial{baseColor:"#121A20";roughness:0.45} }
    Model { source:"#Cube"; position:Qt.vector3d(0,-24,0); scale:Qt.vector3d(0.36,0.19,0.26); materials:PrincipledMaterial{baseColor:"#6B7782";metalness:0.45;roughness:0.48} }
    // Representative post and base make the isolator read as a real mounted laboratory component.
    Model { source:"#Cylinder"; position:Qt.vector3d(0,-43.25,0); scale:Qt.vector3d(0.065,0.195,0.065); materials:PrincipledMaterial{baseColor:"#9AA7B1";metalness:0.62;roughness:0.36} }
    Model { source:"#Cube"; position:Qt.vector3d(0,-57.5,0); scale:Qt.vector3d(0.38,0.09,0.30); materials:PrincipledMaterial{baseColor:"#35414A";metalness:0.42;roughness:0.52} }
}
