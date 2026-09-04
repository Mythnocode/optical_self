import QtQuick
import QtQuick3D
Node {
    Model { source:"#Cube"; position:Qt.vector3d(-5,-57,0); scale:Qt.vector3d(0.82,0.08,0.22); materials:PrincipledMaterial{baseColor:"#35414A";metalness:0.43;roughness:0.50} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-32,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.22,0.04,0.22); materials:PrincipledMaterial{baseColor:"#75CFDC";opacity:0.40;alphaMode:PrincipledMaterial.Blend;roughness:0.08} }
    Model { source:"#Cylinder"; position:Qt.vector3d(36,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.34,0.04,0.34); materials:PrincipledMaterial{baseColor:"#75CFDC";opacity:0.40;alphaMode:PrincipledMaterial.Blend;roughness:0.08} }
    Model { source:"#Cube"; position:Qt.vector3d(-32,0,0); scale:Qt.vector3d(0.08,0.55,0.34); materials:PrincipledMaterial{baseColor:"#28323A";opacity:0.65;alphaMode:PrincipledMaterial.Blend;roughness:0.45} }
    Model { source:"#Cube"; position:Qt.vector3d(36,0,0); scale:Qt.vector3d(0.08,0.67,0.46); materials:PrincipledMaterial{baseColor:"#28323A";opacity:0.65;alphaMode:PrincipledMaterial.Blend;roughness:0.45} }
    Model { source:"#Cube"; position:Qt.vector3d(-32,-32.25,0); scale:Qt.vector3d(0.15,0.095,0.15); materials:PrincipledMaterial{baseColor:"#33404A";metalness:0.46;roughness:0.48} }
    Model { source:"#Cube"; position:Qt.vector3d(36,-35.25,0); scale:Qt.vector3d(0.15,0.035,0.15); materials:PrincipledMaterial{baseColor:"#33404A";metalness:0.46;roughness:0.48} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-32,-45,0); scale:Qt.vector3d(0.055,0.16,0.055); materials:PrincipledMaterial{baseColor:"#9AA7B1";metalness:0.62;roughness:0.36} }
    Model { source:"#Cylinder"; position:Qt.vector3d(36,-45,0); scale:Qt.vector3d(0.055,0.16,0.055); materials:PrincipledMaterial{baseColor:"#9AA7B1";metalness:0.62;roughness:0.36} }
}
