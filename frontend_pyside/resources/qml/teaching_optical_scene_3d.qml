import QtQuick
import QtQuick3D

Rectangle {
    id: root
    color: "#F4F7FA"

    function selected(key) { return teachingBridge.focusKey === key }
    function beamDx() { return teachingBridge.fiberX - 50.0 }
    function beamDy() { return teachingBridge.fiberY }
    function beamDz() { return teachingBridge.fiberZ - 60.0 }
    function beamLength() { return Math.sqrt(beamDx()*beamDx()+beamDy()*beamDy()+beamDz()*beamDz()) }
    function beamZRotation() { return -Math.atan2(beamDy(), beamDx()) * 180 / Math.PI }
    function beamYRotation() { return Math.atan2(beamDz(), beamDx()) * 180 / Math.PI }

    View3D {
        id: view
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#F4F7FA"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        Node {
            id: cameraPivot
            eulerRotation.x: -18
            eulerRotation.y: -22
            PerspectiveCamera {
                id: camera
                z: 1050
                clipNear: 5
                clipFar: 5000
                fieldOfView: 42
            }
        }
        camera: camera

        DirectionalLight { eulerRotation.x: -35; eulerRotation.y: -25; brightness: 1.1 }
        DirectionalLight { eulerRotation.x: 40; eulerRotation.y: 130; brightness: 0.45 }

        // Optical table: true 3D geometry, not a painted background image.
        Model {
            source: "#Cube"
            position: Qt.vector3d(0, -25, 0)
            scale: Qt.vector3d(10.5, 0.18, 4.6)
            materials: PrincipledMaterial { baseColor: "#DCE5EA"; roughness: 0.9 }
        }

        // Optical axis reference.
        Model {
            visible: teachingBridge.showAxis
            source: "#Cylinder"
            position: Qt.vector3d(0, 60, 0)
            eulerRotation.z: 90
            scale: Qt.vector3d(0.012, 9.2, 0.012)
            materials: PrincipledMaterial { baseColor: "#6B7280"; opacity: 0.35; alphaMode: PrincipledMaterial.Blend }
        }

        // Main ray: two true 3D segments. The second segment follows fiber offsets.
        Model {
            visible: teachingBridge.showMainRay
            source: "#Cylinder"
            position: Qt.vector3d(-200, 60, 0)
            eulerRotation.z: 90
            scale: Qt.vector3d(0.026, 5.0, 0.026)
            materials: PrincipledMaterial { baseColor: "#E65A00"; emissiveFactor: Qt.vector3d(0.5,0.15,0.02) }
        }
        Node {
            visible: teachingBridge.showMainRay
            position: Qt.vector3d(50, 60, 0)
            eulerRotation.z: root.beamZRotation()
            eulerRotation.y: root.beamYRotation()
            Model {
                source: "#Cylinder"
                position.x: root.beamLength()/2
                eulerRotation.z: 90
                scale: Qt.vector3d(0.027, root.beamLength()/100, 0.027)
                materials: PrincipledMaterial { baseColor: "#E65A00"; emissiveFactor: Qt.vector3d(0.55,0.17,0.02) }
            }
        }

        // Gaussian envelope. Cyan transparent solid makes focusing/defocusing readable from any camera angle.
        Model {
            visible: teachingBridge.showEnvelope
            source: "#Cylinder"
            position: Qt.vector3d(-200, 60, 0)
            eulerRotation.z: 90
            scale: Qt.vector3d(teachingBridge.inputRadius/50, 5.0, teachingBridge.inputRadius/50)
            materials: PrincipledMaterial {
                baseColor: "#1597A8"; opacity: 0.17; alphaMode: PrincipledMaterial.Blend
                roughness: 0.2; cullMode: Material.NoCulling
            }
        }
        Node {
            visible: teachingBridge.showEnvelope
            position: Qt.vector3d(50, 60, 0)
            eulerRotation.z: root.beamZRotation()
            eulerRotation.y: root.beamYRotation()
            Model {
                source: "#Cone"
                position.x: root.beamLength()/2
                eulerRotation.z: -90
                scale: Qt.vector3d(Math.max(teachingBridge.inputRadius, teachingBridge.endRadius)/38,
                                   root.beamLength()/100,
                                   Math.max(teachingBridge.inputRadius, teachingBridge.endRadius)/38)
                materials: PrincipledMaterial {
                    baseColor: "#1597A8"; opacity: 0.20; alphaMode: PrincipledMaterial.Blend
                    roughness: 0.15; cullMode: Material.NoCulling
                }
            }
        }

        // Laser
        Model {
            objectName: "laser"; pickable: true; source: "#Cube"; position: Qt.vector3d(-450,60,0)
            scale: Qt.vector3d(0.72,0.45,0.45)
            materials: PrincipledMaterial { baseColor: root.selected("laser") ? "#F59E0B" : "#B9DDF5" }
        }
        // Isolator
        Model {
            objectName: "isolator"; pickable: true; source: "#Cylinder"; position: Qt.vector3d(-295,60,0)
            eulerRotation.z: 90; scale: Qt.vector3d(0.28,0.46,0.28)
            materials: PrincipledMaterial { baseColor: root.selected("isolator") ? "#F59E0B" : "#8DB9D5" }
        }
        // Beamsplitter
        Model {
            objectName: "splitter"; pickable: true; source: "#Cube"; position: Qt.vector3d(-140,60,0)
            eulerRotation.y: 45; scale: Qt.vector3d(0.38,0.50,0.10)
            materials: PrincipledMaterial { baseColor: root.selected("splitter") ? "#F59E0B" : "#85D0E6"; opacity:0.60; alphaMode:PrincipledMaterial.Blend }
        }
        // Lens: transparent real cylinder, oriented perpendicular to optical X axis.
        Model {
            objectName: "lens"; pickable: true; source: "#Cylinder"; position: Qt.vector3d(50,60,0)
            eulerRotation.z: 90; scale: Qt.vector3d(0.52,0.08,0.52)
            materials: PrincipledMaterial { baseColor: root.selected("lens") ? "#F59E0B" : "#55B7D6"; opacity:0.42; alphaMode:PrincipledMaterial.Blend; roughness:0.12 }
        }
        // Fiber assembly follows shared teaching state.
        Model {
            objectName: "fiber"; pickable: true; source: "#Cylinder"
            position: Qt.vector3d(teachingBridge.fiberX, teachingBridge.fiberZ, teachingBridge.fiberY)
            eulerRotation.z: 90; scale: Qt.vector3d(0.22,0.42,0.22)
            materials: PrincipledMaterial { baseColor: root.selected("fiber") ? "#F59E0B" : "#64748B" }
        }
        Model {
            objectName: "output"; pickable: true; source: "#Cube"; position: Qt.vector3d(455,60,0)
            scale: Qt.vector3d(0.45,0.5,0.55)
            materials: PrincipledMaterial { baseColor: root.selected("output") ? "#F59E0B" : "#A7B4C2" }
        }
    }

    // Camera interaction stays entirely in QML/GPU and never submits physics.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        property real lastX: 0
        property real lastY: 0
        onPressed: function(mouse) {
            lastX = mouse.x; lastY = mouse.y
            if (mouse.button === Qt.LeftButton) {
                var hit = view.pick(mouse.x, mouse.y)
                if (hit.objectHit && hit.objectHit.objectName !== "")
                    teachingBridge.activateObject(hit.objectHit.objectName)
            }
        }
        onPositionChanged: function(mouse) {
            var dx = mouse.x-lastX; var dy = mouse.y-lastY; lastX=mouse.x; lastY=mouse.y
            if (mouse.buttons & Qt.RightButton) {
                cameraPivot.eulerRotation.y += dx*0.35
                cameraPivot.eulerRotation.x = Math.max(-78, Math.min(25, cameraPivot.eulerRotation.x+dy*0.25))
            } else if (mouse.buttons & Qt.MiddleButton) {
                cameraPivot.x += dx*0.65; cameraPivot.y -= dy*0.65
            }
        }
        onWheel: function(wheel) {
            camera.z = Math.max(420, Math.min(2200, camera.z * (wheel.angleDelta.y > 0 ? 0.90 : 1.11)))
            wheel.accepted = true
        }
    }

    Connections {
        target: teachingBridge
        function onViewNameChanged() {
            var name = teachingBridge.viewName
            if (name === "top") { cameraPivot.eulerRotation.x=-78; cameraPivot.eulerRotation.y=0; camera.z=1100 }
            else if (name === "front") { cameraPivot.eulerRotation.x=0; cameraPivot.eulerRotation.y=0; camera.z=1050 }
            else if (name === "axis") { cameraPivot.eulerRotation.x=0; cameraPivot.eulerRotation.y=-88; camera.z=900 }
            else { cameraPivot.eulerRotation.x=-18; cameraPivot.eulerRotation.y=-22; camera.z=1050 }
            cameraPivot.x=0; cameraPivot.y=0
        }
    }

    Rectangle {
        anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 12
        radius: 7; color: "#EFFFFFFF"; border.color: "#94A3B8"
        width: infoText.implicitWidth+24; height: 58
        Text { id: infoText; anchors.centerIn: parent; color:"#1F2937"; font.pixelSize:15
            text: "真实 3D 光路\n橙色：主光线　青色：Gaussian 包络" }
    }
}
