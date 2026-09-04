import QtQuick
import QtQuick3D
Node {
    // Fiber ferrule/entrance is centered on x=0; stage body stays behind it.
    Model { source:"#Cylinder"; position:Qt.vector3d(-8,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.14,0.22,0.14); materials:PrincipledMaterial{baseColor:"#202B33";metalness:0.58;roughness:0.34} }
    Model { source:"#Cylinder"; position:Qt.vector3d(1,0,0); eulerRotation.z:90; scale:Qt.vector3d(0.055,0.035,0.055); materials:PrincipledMaterial{baseColor:"#7ED7E7";emissiveFactor:Qt.vector3d(0.02,0.16,0.19);roughness:0.16} }
    Model { source:"#Cube"; position:Qt.vector3d(-26,-15,0); scale:Qt.vector3d(0.42,0.35,0.44); materials:PrincipledMaterial{baseColor:"#3A4650";metalness:0.48;roughness:0.45} }
    // Visible pedestal closes the last sub-unit gap between the five-axis body and post.
    Model { source:"#Cube"; position:Qt.vector3d(-26,-33,0); scale:Qt.vector3d(0.22,0.06,0.24); materials:PrincipledMaterial{baseColor:"#33404A";metalness:0.48;roughness:0.46} }
    // Connector stems make both adjustment knobs visibly part of the stage body.
    Model { source:"#Cylinder"; position:Qt.vector3d(-30,14,20); eulerRotation.x:90; scale:Qt.vector3d(0.045,0.14,0.045); materials:PrincipledMaterial{baseColor:"#66747E";metalness:0.45;roughness:0.38} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-30,-8,22); eulerRotation.x:90; scale:Qt.vector3d(0.045,0.16,0.045); materials:PrincipledMaterial{baseColor:"#66747E";metalness:0.45;roughness:0.38} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-30,18,32); eulerRotation.x:90; scale:Qt.vector3d(0.07,0.18,0.07); materials:PrincipledMaterial{baseColor:"#151D23";roughness:0.36} }
    Model { source:"#Cylinder"; position:Qt.vector3d(-30,-8,35); eulerRotation.x:90; scale:Qt.vector3d(0.07,0.18,0.07); materials:PrincipledMaterial{baseColor:"#151D23";roughness:0.36} }
    Model { source:"#Cube"; position:Qt.vector3d(-26,-57.5,0); scale:Qt.vector3d(0.52,0.09,0.50); materials:PrincipledMaterial{baseColor:"#252F37";metalness:0.46;roughness:0.50} }
    // The five-axis stage sits on a visible support post above its table base.
    Model { source:"#Cylinder"; position:Qt.vector3d(-26,-43.25,0); scale:Qt.vector3d(0.08,0.195,0.08); materials:PrincipledMaterial{baseColor:"#9AA7B1";metalness:0.62;roughness:0.36} }
}
