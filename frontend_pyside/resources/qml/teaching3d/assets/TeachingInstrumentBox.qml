import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cube"; position:Qt.vector3d(-12,0,0); scale:Qt.vector3d(0.56,0.44,0.58); materials:PrincipledMaterial{baseColor:"#566B78";metalness:0.26;roughness:0.60} }
    Model { source:"#Cube"; position:Qt.vector3d(18,4,0); scale:Qt.vector3d(0.02,0.24,0.34); materials:PrincipledMaterial{baseColor:"#12242B";emissiveFactor:Qt.vector3d(0.01,0.08,0.08);roughness:0.24} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-12,-44,0); scale:Qt.vector3d(0.07,0.16,0.07); materials:PrincipledMaterial{baseColor:"#98A6B0";metalness:0.62;roughness:0.36} }
    Model { source:"#Cube"; position:Qt.vector3d(-12,-57,0); scale:Qt.vector3d(0.38,0.08,0.34); materials:PrincipledMaterial{baseColor:"#35414A";metalness:0.40;roughness:0.52} }
}
