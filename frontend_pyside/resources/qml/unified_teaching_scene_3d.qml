import QtQuick
import QtQuick3D
import QtQuick.Controls
import "teaching3d" as Teaching3D

Rectangle {
    id: root
    objectName: "unifiedTeaching3DRoot"
    color: "#F4F7FA"
    property string requestedPreset: "isometric"
    property int presetSerial: 0
    property var dragObject: null
    property string dragId: ""
    property vector3d dragGrabOffset: Qt.vector3d(0,0,0)
    property real dragPlaneY: 52
    property bool draggingDevice: false
    property bool dragMoved: false
    property double pressTimestamp: 0
    property bool orbiting: false
    property bool panning: false
    property bool analysisPanelsVisible: false
    // 左上角信息卡（当前实验结果 / 最终成像预览）：画布子节点承载时由宿主关闭
    property bool infoPanelsVisible: true

    // Diagnostics are opt-in so normal teaching sessions do not pay for extended
    // renderer statistics.  They are used by the automated 3D interaction gate.
    property bool diagnosticsEnabled: false
    property string diagnosticNodeId: ""
    property point diagnosticNodeScreen: Qt.point(-1, -1)
    readonly property int diagnosticFps: view.renderStats.fps
    readonly property real diagnosticFrameTime: view.renderStats.frameTime
    readonly property real diagnosticRenderTime: view.renderStats.renderTime
    readonly property int diagnosticDrawCallCount: Number(view.renderStats.drawCallCount)
    readonly property int diagnosticDrawVertexCount: Number(view.renderStats.drawVertexCount)
    readonly property int diagnosticRenderPassCount: view.renderStats.renderPassCount
    readonly property real diagnosticMeshDataMiB: Number(view.renderStats.meshDataSize) / (1024 * 1024)
    readonly property real diagnosticImageDataMiB: Number(view.renderStats.imageDataSize) / (1024 * 1024)
    readonly property real diagnosticCameraPivotX: cameraPivot.x
    readonly property real diagnosticCameraPivotY: cameraPivot.y
    readonly property real diagnosticCameraDistance: camera.z
    readonly property real diagnosticCameraAzimuth: -cameraPivot.eulerRotation.y
    readonly property real diagnosticCameraElevation: -cameraPivot.eulerRotation.x

    onDiagnosticsEnabledChanged: view.renderStats.extendedDataCollectionEnabled = diagnosticsEnabled

    function refreshDiagnosticNodeScreen() {
        diagnosticNodeScreen = Qt.point(-1, -1)
        var data = sceneBridge.nodes
        for (var index = 0; index < data.length; ++index) {
            var item = data[index]
            if (item.id === diagnosticNodeId) {
                var projected = view.mapFrom3DScene(Qt.vector3d(item.x, item.y, item.z))
                diagnosticNodeScreen = Qt.point(projected.x, projected.y)
                return
            }
        }
    }

    function diagnosticPickName(x, y) {
        var result = view.pick(x, y)
        if (result.objectHit && result.objectHit.objectName !== "")
            return result.objectHit.objectName
        return ""
    }

    function reportCamera() {
        var zoom = 1180 / camera.z
        sceneBridge.reportCameraState(-cameraPivot.eulerRotation.y, -cameraPivot.eulerRotation.x, zoom)
    }
    function applyPreset(name) {
        if (name === "top") { cameraPivot.eulerRotation.x=-89; cameraPivot.eulerRotation.y=0 }
        else if (name === "front" || name === "main_axis") { cameraPivot.eulerRotation.x=0; cameraPivot.eulerRotation.y=0 }
        else if (name === "side" || name === "branch") { cameraPivot.eulerRotation.x=0; cameraPivot.eulerRotation.y=-90 }
        else if (name === "paper") { cameraPivot.eulerRotation.x=-12; cameraPivot.eulerRotation.y=-4 }
        else { cameraPivot.eulerRotation.x=-18; cameraPivot.eulerRotation.y=-28 }
        cameraPivot.x=0; cameraPivot.y=0; camera.z=1180
        reportCamera()
    }
    function fitAll() {
        cameraPivot.x = 0; cameraPivot.y = 0
        camera.z = 1180
        reportCamera()
    }
    onPresetSerialChanged: applyPreset(requestedPreset)

    function screenRay(mouse) {
        if (view.camera === null) return null
        var nearPoint = view.mapTo3DScene(Qt.vector3d(mouse.x, mouse.y, 0))
        var farPoint = view.mapTo3DScene(Qt.vector3d(mouse.x, mouse.y, 1))
        var direction = farPoint.minus(nearPoint)
        return { origin: nearPoint, dir: direction }
    }
    function rayPlaneY(ray, planeY) {
        if (ray === null || Math.abs(ray.dir.y) < 1.0e-6) return null
        var t = (planeY - ray.origin.y) / ray.dir.y
        if (t < 0) return null
        return ray.origin.plus(ray.dir.times(t))
    }
    function clampWorldX(value) { return Math.max(-573.8, Math.min(573.8, value)) }
    function clampWorldZ(value) { return Math.max(-235.6, Math.min(235.6, value)) }

    function dx(a) { return a.x2-a.x1 }
    function dy(a) { return a.y2-a.y1 }
    function dz(a) { return a.z2-a.z1 }
    function length2d(a) { return Math.sqrt(dx(a)*dx(a)+dz(a)*dz(a)) }
    function length3d(a) { return Math.sqrt(dx(a)*dx(a)+dy(a)*dy(a)+dz(a)*dz(a)) }
    function yaw(a) { return -Math.atan2(dz(a), dx(a))*180/Math.PI }
    // Qt Quick3D primitive cylinders are aligned to local Y.  Rotate that axis
    // onto the full 3-D formal ray direction instead of flattening every ray to
    // the optical-table plane.
    function tiltFromY(a) {
        var len = Math.max(1.0e-9, length3d(a))
        return Math.acos(Math.max(-1, Math.min(1, dy(a)/len)))*180/Math.PI
    }

    View3D {
        id: view
        objectName: "teaching3dView"
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#F4F7FA"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }
        Node {
            id: cameraPivot
            eulerRotation.x: -16
            eulerRotation.y: -18
            PerspectiveCamera { id: camera; z: 1180; clipNear: 4; clipFar: 6000; fieldOfView: 39 }
        }
        camera: camera
        DirectionalLight { eulerRotation.x: -35; eulerRotation.y: -30; brightness: 1.05 }
        DirectionalLight { eulerRotation.x: 38; eulerRotation.y: 135; brightness: 0.42 }

        Model {
            source: "#Cube"; position: Qt.vector3d(0,-18,0); scale: Qt.vector3d(14.0,0.18,7.5)
            materials: PrincipledMaterial { baseColor: "#DCE5EA"; roughness: 0.92 }
        }
        Model {
            visible: sceneBridge.showAxis
            source: "#Cylinder"; position: Qt.vector3d(0,52,sceneBridge.railWorldZ); eulerRotation.z: 90; scale: Qt.vector3d(0.012,13.0,0.012)
            materials: PrincipledMaterial { baseColor:"#475467"; opacity:0.32; alphaMode:PrincipledMaterial.Blend }
        }

        // Formal chief-ray only. Abstract Gaussian envelope tubes were removed.
        Repeater3D {
            model: sceneBridge.envelopeSegments
            delegate: Model {
                required property var modelData
                visible: false
                objectName: "envelope:" + modelData.id
                pickable: false
                source: "#Cylinder"
                position: Qt.vector3d((modelData.x1+modelData.x2)/2, (modelData.y1+modelData.y2)/2, (modelData.z1+modelData.z2)/2)
                scale: Qt.vector3d(0.001, 0.001, 0.001)
                materials: PrincipledMaterial { baseColor: "#0E7490"; opacity: 0.0; alphaMode: PrincipledMaterial.Blend }
            }
        }

        Repeater3D {
            model: sceneBridge.structureEdges
            delegate: Model {
                required property var modelData
                visible: sceneBridge.showNodes
                objectName: "structure:" + modelData.id
                pickable: false
                source: "#Cylinder"
                position: Qt.vector3d((modelData.x1+modelData.x2)/2, (modelData.y1+modelData.y2)/2, (modelData.z1+modelData.z2)/2)
                eulerRotation.z: root.tiltFromY(modelData)
                eulerRotation.y: root.yaw(modelData)
                scale: Qt.vector3d(0.010, root.length3d(modelData)/100, 0.010)
                materials: PrincipledMaterial {
                    baseColor: "#334155"
                    opacity: 0.28
                    alphaMode: PrincipledMaterial.Blend
                    roughness: 0.65
                }
            }
        }

        Repeater3D {
            model: sceneBridge.previewEdges
            delegate: Model {
                required property var modelData
                visible: sceneBridge.showAxis && sceneBridge.showNodes
                objectName: "preview:" + modelData.id
                pickable: false
                source: "#Cylinder"
                position: Qt.vector3d((modelData.x1+modelData.x2)/2, (modelData.y1+modelData.y2)/2, (modelData.z1+modelData.z2)/2)
                eulerRotation.z: root.tiltFromY(modelData)
                eulerRotation.y: root.yaw(modelData)
                scale: Qt.vector3d(0.018, root.length3d(modelData)/100, 0.018)
                materials: PrincipledMaterial {
                    baseColor: "#0E7490"
                    opacity: 0.48
                    alphaMode: PrincipledMaterial.Blend
                    roughness: 0.35
                    emissiveFactor: Qt.vector3d(0.02, 0.10, 0.12)
                }
            }
        }

        // Formal solver rays only. Topology never becomes red light.
        Repeater3D {
            model: sceneBridge.edges
            delegate: Model {
                required property var modelData
                visible: sceneBridge.showRays
                objectName: "beam:" + modelData.id
                pickable: sceneBridge.placementActive && modelData.active
                source: "#Cylinder"
                position: Qt.vector3d((modelData.x1+modelData.x2)/2, (modelData.y1+modelData.y2)/2, (modelData.z1+modelData.z2)/2)
                eulerRotation.z: root.tiltFromY(modelData)
                eulerRotation.y: root.yaw(modelData)
                scale: Qt.vector3d(modelData.active ? (sceneBridge.placementActive ? 0.078 : 0.042) : 0.022, root.length3d(modelData)/100, modelData.active ? (sceneBridge.placementActive ? 0.078 : 0.042) : 0.022)
                materials: PrincipledMaterial {
                    baseColor: modelData.expired ? "#B45309" : (modelData.active ? "#FF0000" : "#667085")
                    opacity: root.draggingDevice ? (modelData.active ? 0.32 : 0.12) : (modelData.expired ? 0.28 : (modelData.active ? 0.95 : 0.30))
                    alphaMode: PrincipledMaterial.Blend
                    emissiveFactor: modelData.active ? Qt.vector3d(0.55,0.0,0.0) : Qt.vector3d(0,0,0)
                }
            }
        }

        // Movable I(x,y,z) teaching cross-section.  The disc is perpendicular to
        // the active beam segment and follows the same beam-radius state as 2D.
        Model {
            visible: root.analysisPanelsVisible && sceneBridge.sectionAvailable && !root.draggingDevice
            source: "#Cylinder"
            position: Qt.vector3d(sceneBridge.sectionX, sceneBridge.sectionY, sceneBridge.sectionZ)
            eulerRotation.z: 90
            eulerRotation.y: sceneBridge.sectionYaw
            scale: Qt.vector3d(Math.max(0.10, sceneBridge.sectionRadius/42), 0.045, Math.max(0.10, sceneBridge.sectionRadius/42))
            materials: PrincipledMaterial {
                baseColor: "#7C3AED"; opacity: 0.32; alphaMode: PrincipledMaterial.Blend
                roughness: 0.12; cullMode: Material.NoCulling
            }
        }

        Repeater3D {
            model: sceneBridge.nodes
            delegate: Teaching3D.OpticalAssetNode {
                deviceData: modelData
                visible: sceneBridge.showNodes
                useDetailed: sceneBridge.detailedAssetsEnabled
                locallyDragging: root.draggingDevice && root.dragId === modelData.id
            }
        }
    }

    MouseArea {
        id: interactionArea
        objectName: "teaching3dInteractionArea"
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        hoverEnabled: true
        property real lastX: 0
        property real lastY: 0
        onPressed: function(mouse) {
            lastX=mouse.x; lastY=mouse.y
            root.pressTimestamp = Date.now()
            root.orbiting=false; root.panning=false
            var shiftHeld = (mouse.modifiers & Qt.ShiftModifier) !== 0
            if (mouse.button === Qt.MiddleButton || (mouse.button === Qt.LeftButton && shiftHeld)) {
                root.panning=true
                return
            }
            if (mouse.button === Qt.RightButton) {
                root.orbiting=true
                return
            }
            if (mouse.button === Qt.LeftButton) {
                var pickResult=view.pick(mouse.x,mouse.y)
                if (pickResult.objectHit && pickResult.objectHit.objectName !== "") {
                    var objectName = pickResult.objectHit.objectName
                    if (objectName.indexOf("beam:") === 0) {
                        sceneBridge.activate(objectName)
                        return
                    }
                    if (sceneBridge.showNodes) {
                        // Do not activate/refresh the workbench while the mouse grab is being
                        // established.  In the integrated workbench activation synchronously
                        // refreshes the scene and can invalidate the picked delegate.  A plain
                        // click activates on release; a drag commits first and selects in the
                        // workbench move handler.
                        var dragTarget = pickResult.objectHit.dragOwner ? pickResult.objectHit.dragOwner : pickResult.objectHit
                        root.dragObject = dragTarget
                        root.dragId = objectName
                        root.dragPlaneY = dragTarget.position.y
                        root.dragMoved = false
                        var ray = root.screenRay(mouse)
                        var planeHit = root.rayPlaneY(ray, root.dragPlaneY)
                        if (planeHit) {
                            root.dragGrabOffset = dragTarget.position.minus(planeHit)
                            root.dragObject.localDragPosition = dragTarget.position
                            root.draggingDevice = true
                            return
                        }
                        root.dragObject = null; root.dragId = ""
                        sceneBridge.activate(objectName)
                        return
                    }
                }
                // Empty-space left drag follows common CAD behavior: orbit camera.
                root.orbiting=true
            }
        }
        onPositionChanged: function(mouse) {
            var mx=mouse.x-lastX; var my=mouse.y-lastY; lastX=mouse.x; lastY=mouse.y
            if ((mouse.buttons & Qt.LeftButton) && root.dragObject !== null && root.draggingDevice) {
                var ray = root.screenRay(mouse)
                var planeHit = root.rayPlaneY(ray, root.dragPlaneY)
                if (planeHit) {
                    var target = planeHit.plus(root.dragGrabOffset)
                    var nextPosition = Qt.vector3d(root.clampWorldX(target.x), root.dragPlaneY, root.clampWorldZ(target.z))
                    root.dragObject.localDragPosition = nextPosition
                    root.dragMoved = true
                }
            } else if (root.panning && (mouse.buttons & (Qt.MiddleButton | Qt.LeftButton))) {
                cameraPivot.x += mx*0.72; cameraPivot.y -= my*0.72
                root.reportCamera()
            } else if (root.orbiting && (mouse.buttons & (Qt.LeftButton | Qt.RightButton))) {
                cameraPivot.eulerRotation.y += mx*0.35
                cameraPivot.eulerRotation.x = Math.max(-85,Math.min(85,cameraPivot.eulerRotation.x+my*0.28))
                root.reportCamera()
            }
        }
        onReleased: function(mouse) {
            if (mouse.button === Qt.LeftButton && root.dragObject !== null) {
                var releasedId = root.dragId
                var releasedMoved = root.dragMoved
                var finalPosition = root.dragObject.localDragPosition
                var elapsed = Date.now() - root.pressTimestamp
                root.dragObject = null; root.dragId = ""; root.draggingDevice = false; root.dragMoved = false
                if (releasedMoved)
                    sceneBridge.moveNodeWorld(releasedId, finalPosition.x, finalPosition.z)
                else if (releasedId !== "") {
                    sceneBridge.activate(releasedId)
                    if (elapsed < 420) sceneBridge.activateDouble(releasedId)
                }
            }
            root.orbiting=false; root.panning=false
        }
        onCanceled: {
            root.dragObject = null; root.dragId = ""; root.draggingDevice = false; root.dragMoved = false
            root.orbiting=false; root.panning=false
        }
        onWheel: function(wheel) {
            camera.z=Math.max(360,Math.min(2800,camera.z*(wheel.angleDelta.y>0?0.90:1.11)))
            root.reportCamera()
            wheel.accepted=true
        }
    }

    // Accept the same component MIME payload as the 2-D engineering view.
    // The drop is intersected with the optical-table plane in QML, where the
    // active Quick3D camera is available, then converted by the bridge into the
    // single shared experiment coordinate system.
    DropArea {
        id: componentDropArea
        anchors.fill: parent
        z: 18
        keys: ["application/x-optical-teaching-component"]
        onDropped: function(drop) {
            var ray = root.screenRay({x: drop.x, y: drop.y})
            var hit = root.rayPlaneY(ray, 52)
            if (hit === null) {
                drop.accepted = false
                return
            }
            var kind = drop.getDataAsString("application/x-optical-teaching-component")
            if (kind === "") {
                drop.accepted = false
                return
            }
            sceneBridge.dropComponentWorld(kind, root.clampWorldX(hit.x), root.clampWorldZ(hit.z))
            drop.acceptProposedAction()
        }
    }

    Connections {
        target: sceneBridge
        function onRotateRequested(degrees) { cameraPivot.eulerRotation.y += degrees; root.reportCamera() }
        function onZoomRequested(factor) { camera.z=Math.max(420,Math.min(2600,camera.z*factor)); root.reportCamera() }
        function onResetRequested() {
            cameraPivot.eulerRotation.x=-16; cameraPivot.eulerRotation.y=-18
            root.fitAll()
        }
    }

    Row {
        visible: false  // QWidget shell owns compact camera commands; avoid duplicate controls.
        anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
        spacing: 5; z: 20
        Button { text:"等轴"; onClicked: root.applyPreset("isometric") }
        Button { text:"俯视"; onClicked: root.applyPreset("top") }
        Button { text:"正视"; onClicked: root.applyPreset("front") }
        Button { text:"侧视"; onClicked: root.applyPreset("side") }
        Button { text:"适应全部"; onClicked: root.fitAll() }
        Button { text: sceneBridge.detailedAssetsEnabled ? "简化器件" : "精细器件"; onClicked: sceneBridge.setDetailedAssetsEnabled(!sceneBridge.detailedAssetsEnabled) }
        Button { text:"重置"; onClicked: root.applyPreset("isometric") }
    }
    Text {
        visible: false  // Help moved to tooltips so the 3D stage remains unobstructed.
        anchors.right: parent.right; anchors.top: parent.top; anchors.topMargin: 52; anchors.rightMargin: 14
        text: "空白处左键拖动旋转 · Shift+左键/中键平移 · 滚轮缩放 · 精细器件由简化代理负责拖动"
        color: "#667085"; font.pixelSize: 12; z: 20
    }

    Row {
        anchors.right: parent.right; anchors.top: parent.top; anchors.rightMargin: 14; anchors.topMargin: 14
        spacing: 6; z: 30
        Repeater { model: ["搭建", "观察", "测量", "分析"]
            delegate: Button { text: modelData; height: 32; onClicked: sceneBridge.toolCategoryRequested(modelData) }
        }
    }

    Rectangle {
        id: toolCategoryPanel
        anchors.right: parent.right; anchors.top: parent.top; anchors.rightMargin: 14; anchors.topMargin: 54
        z: 30; width: 220; radius: 8
        color: "#F7FFFFFF"; border.color: "#98A2B3"
        visible: false
        Column { id: toolCategoryContent; anchors.fill: parent; anchors.margins: 8; spacing: 5 }
    }

    Rectangle {
        anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.leftMargin: 14; anchors.bottomMargin: 14
        z: 30; width: 214; height: 42; radius: 7; color: "#F7FFFFFF"; border.color: "#98A2B3"
        Row { anchors.centerIn: parent; spacing: 5
            Repeater { model: ["等轴", "俯视", "侧视"]
                delegate: Button { text: modelData; height: 28; onClicked: {
                    if (modelData === "俯视") sceneBridge.setCameraPreset("top")
                    else if (modelData === "侧视") sceneBridge.setCameraPreset("side")
                    else sceneBridge.setCameraPreset("isometric")
                }}
            }
        }
    }

    Button {
        anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.rightMargin: 82; anchors.bottomMargin: 112
        z: 30; text: "↑"; width: 38; height: 38
        onClicked: sceneBridge.nudgeSelected(0, -28)
    }
    Button {
        anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.rightMargin: 14; anchors.bottomMargin: 66
        z: 30; text: "→"; width: 38; height: 38
        onClicked: sceneBridge.nudgeSelected(28, 0)
    }
    Button {
        anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.rightMargin: 150; anchors.bottomMargin: 66
        z: 30; text: "←"; width: 38; height: 38
        onClicked: sceneBridge.nudgeSelected(-28, 0)
    }
    Button {
        anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.rightMargin: 82; anchors.bottomMargin: 14
        z: 30; text: "↓"; width: 38; height: 38
        onClicked: sceneBridge.nudgeSelected(0, 28)
    }

    Rectangle {
        anchors.left: parent.left; anchors.top: parent.top; anchors.leftMargin: 14; anchors.topMargin: 14
        visible: root.infoPanelsVisible
        z: 30; width: 300; height: 150; radius: 8
        color: "#F7FFFFFF"; border.color: "#8EA2B3"
        Column {
            anchors.fill: parent; anchors.margins: 12; spacing: 6
            Text { text: "当前实验结果"; color: "#101828"; font.pixelSize: 16; font.bold: true }
            Text {
                text: sceneBridge.resultHeadline
                color: sceneBridge.resultPhysicsStatus === "verified" ? "#15803D"
                     : sceneBridge.resultPhysicsStatus === "expired" ? "#B45309"
                     : sceneBridge.resultPhysicsStatus === "blocked" ? "#B91C1C"
                     : "#475569"
                font.pixelSize: 20; font.bold: true
            }
            Text { text: sceneBridge.resultDetail; color: "#344054"; font.pixelSize: 13; wrapMode: Text.WordWrap; width: parent.width }
            Text { text: sceneBridge.resultPowerLine; color: "#344054"; font.pixelSize: 13; visible: sceneBridge.resultPowerLine.length > 0 }
            Text {
                text: "效率：" + sceneBridge.resultSource + " · 光线：" + sceneBridge.resultStatus
                color: "#667085"; font.pixelSize: 11
            }
        }
    }

    Rectangle {
        id: imagingPreview
        anchors.left: parent.left; anchors.top: parent.top; anchors.leftMargin: 14; anchors.topMargin: 176
        visible: root.infoPanelsVisible
        z: 30; width: 300; height: 160; radius: 8
        color: "#10202A"; border.color: sceneBridge.imageReceiverHit ? "#FF4D4F" : "#708796"

        Text {
            anchors.left: parent.left; anchors.top: parent.top
            anchors.leftMargin: 10; anchors.topMargin: 8
            text: sceneBridge.imageReceiverAvailable && sceneBridge.imageReceiverLabel.length > 0
                  ? "最终成像预览 · " + sceneBridge.imageReceiverLabel
                  : "最终成像预览"
            color: "#E6F4F7"; font.pixelSize: 11; font.bold: true
        }

        // A spot exists only when the routed teaching beam actually reaches a
        // valid imaging detector.  This deliberately does not reuse fiber
        // coupling state: missing the camera must produce no camera image.
        Item {
            id: imageSpotHost
            visible: sceneBridge.imageReceiverHit
            anchors.centerIn: parent
            anchors.verticalCenterOffset: 8
            width: 150; height: 112
            property real rx: Math.max(sceneBridge.imageRadiusXUm, 0.001)
            property real ry: Math.max(sceneBridge.imageRadiusYUm, 0.001)
            property real major: Math.max(rx, ry)
            property real scaleX: Math.max(0.42, Math.min(1.0, rx / major))
            property real scaleY: Math.max(0.42, Math.min(1.0, ry / major))
            property real offsetX: Math.max(-28, Math.min(28, sceneBridge.imageCenterXUm * 2.0))
            property real offsetY: Math.max(-20, Math.min(20, sceneBridge.imageCenterYUm * 2.0))
            Item {
                anchors.centerIn: parent
                anchors.horizontalCenterOffset: imageSpotHost.offsetX
                anchors.verticalCenterOffset: imageSpotHost.offsetY
                width: parent.width; height: parent.height
                Rectangle {
                    anchors.centerIn: parent
                    width: 106 * imageSpotHost.scaleX; height: 82 * imageSpotHost.scaleY
                    radius: Math.min(width, height) / 2
                    color: "#5C0000"; opacity: 0.22
                }
                Rectangle {
                    anchors.centerIn: parent
                    width: 78 * imageSpotHost.scaleX; height: 61 * imageSpotHost.scaleY
                    radius: Math.min(width, height) / 2
                    color: "#C40000"; opacity: 0.40
                }
                Rectangle {
                    anchors.centerIn: parent
                    width: 50 * imageSpotHost.scaleX; height: 40 * imageSpotHost.scaleY
                    radius: Math.min(width, height) / 2
                    color: "#FF2020"; opacity: 0.70
                }
                Rectangle {
                    anchors.centerIn: parent
                    width: 20 * imageSpotHost.scaleX; height: 17 * imageSpotHost.scaleY
                    radius: Math.min(width, height) / 2
                    color: "#FFB3B3"; opacity: 0.98
                }
            }
        }

        Column {
            visible: !sceneBridge.imageReceiverHit
            anchors.centerIn: parent
            anchors.verticalCenterOffset: 10
            width: parent.width - 34
            spacing: 5
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: sceneBridge.imageReceiverAvailable ? "未接收到光" : "无成像相机"
                color: "#D0D5DD"; font.pixelSize: 16; font.bold: true
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                text: sceneBridge.imageStatus
                color: "#98A2B3"; font.pixelSize: 10
            }
        }

        Text {
            anchors.right: parent.right; anchors.bottom: parent.bottom
            anchors.rightMargin: 10; anchors.bottomMargin: 7
            text: sceneBridge.imageReceiverHit ? "感光面命中 · 教学预览" : "等待相机命中"
            color: sceneBridge.imageReceiverHit ? "#FF9A9A" : "#98A2B3"; font.pixelSize: 10
        }
    }

    // The legacy scene legend is intentionally removed; result overlays carry the useful status.
    Rectangle {
        id: sectionPanel
        visible: root.analysisPanelsVisible && sceneBridge.sectionAvailable
        anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.bottomMargin: 118; anchors.leftMargin: 12
        width: 330; height: 190; radius: 10
        color: "#F5FFFFFF"; border.color: "#98A2B3"
        Column {
            anchors.fill: parent; anchors.margins: 12; spacing: 7
            Text { text: "移动截面 I(x,y,z)"; color:"#101828"; font.pixelSize:16; font.bold:true }
            Text {
                color:"#475467"; font.pixelSize:13
                text: "当前位置 " + Math.round(sceneBridge.sectionFraction*100) + "%　光束半径 " + sceneBridge.sectionRadius.toFixed(2) + "　理想 " + sceneBridge.sectionIdealRadius.toFixed(2)
            }
            Slider {
                id: sectionSlider; width: parent.width; from:0; to:1; value:sceneBridge.sectionFraction
                onMoved: sceneBridge.setCrossSectionFraction(value)
            }
            Item {
                width: parent.width; height: 82
                Canvas {
                    id: sectionGaussianCanvas
                    anchors.centerIn: parent; width: 150; height: 78
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        var cx = width/2; var cy = height/2
                        var maxRadius = Math.max(sceneBridge.sectionRadius, sceneBridge.sectionIdealRadius, 1e-6)
                        var radius = Math.max(10, 31 * sceneBridge.sectionRadius/maxRadius)
                        var idealRadius = Math.max(10, 31 * sceneBridge.sectionIdealRadius/maxRadius)
                        var grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius)
                        grad.addColorStop(0.0, "rgba(21,151,168,0.95)")
                        grad.addColorStop(0.45, "rgba(21,151,168,0.52)")
                        grad.addColorStop(1.0, "rgba(21,151,168,0.02)")
                        ctx.fillStyle = grad
                        ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI*2); ctx.fill()
                        ctx.strokeStyle = "#64748B"; ctx.lineWidth = 2
                        ctx.beginPath(); ctx.arc(cx, cy, idealRadius, 0, Math.PI*2); ctx.stroke()
                        ctx.strokeStyle = "rgba(71,84,103,0.35)"; ctx.lineWidth = 1
                        ctx.beginPath(); ctx.moveTo(cx-36,cy); ctx.lineTo(cx+36,cy); ctx.moveTo(cx,cy-36); ctx.lineTo(cx,cy+36); ctx.stroke()
                    }
                    Connections { target: sceneBridge; function onAnalysisChanged() { sectionGaussianCanvas.requestPaint() } }
                }
                Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text:"青：I(x,y)\n灰：理想半径"; color:"#344054"; font.pixelSize:12 }
            }
        }
    }

    Rectangle {
        id: fiberPanel
        visible: root.analysisPanelsVisible && sceneBridge.fiberAvailable
        anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.bottomMargin: 118; anchors.rightMargin: 12
        width: 280; height: 190; radius: 10
        color: "#F5FFFFFF"; border.color: "#98A2B3"
        Column {
            anchors.fill: parent; anchors.margins: 12; spacing: 6
            Text { text:"光纤端面模场放大镜"; color:"#101828"; font.pixelSize:16; font.bold:true }
            Text {
                color:"#475467"; font.pixelSize:13
                text:"入射场半径 " + sceneBridge.fiberRadius.toFixed(2) + "　目标模场 " + sceneBridge.fiberIdealRadius.toFixed(2)
            }
            Item {
                width: parent.width; height: 105
                Canvas {
                    id: fiberModeCanvas
                    anchors.centerIn: parent; width: 150; height: 100
                    onPaint: {
                        var ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        var cx=width/2; var cy=height/2
                        var maxRadius=Math.max(sceneBridge.fiberRadius, sceneBridge.fiberIdealRadius, 1e-6)
                        var inputRadius=Math.max(12, 40*sceneBridge.fiberRadius/maxRadius)
                        var idealRadius=Math.max(12, 40*sceneBridge.fiberIdealRadius/maxRadius)
                        var ideal=ctx.createRadialGradient(cx,cy,0,cx,cy,idealRadius)
                        ideal.addColorStop(0.0,"rgba(37,99,235,0.42)")
                        ideal.addColorStop(0.58,"rgba(37,99,235,0.16)")
                        ideal.addColorStop(1.0,"rgba(37,99,235,0.01)")
                        ctx.fillStyle=ideal; ctx.beginPath(); ctx.arc(cx,cy,idealRadius,0,Math.PI*2); ctx.fill()
                        var incoming=ctx.createRadialGradient(cx,cy,0,cx,cy,inputRadius)
                        incoming.addColorStop(0.0,"rgba(21,151,168,0.88)")
                        incoming.addColorStop(0.48,"rgba(21,151,168,0.38)")
                        incoming.addColorStop(1.0,"rgba(21,151,168,0.01)")
                        ctx.fillStyle=incoming; ctx.beginPath(); ctx.arc(cx,cy,inputRadius,0,Math.PI*2); ctx.fill()
                        ctx.strokeStyle="#2563EB"; ctx.lineWidth=2; ctx.beginPath(); ctx.arc(cx,cy,idealRadius,0,Math.PI*2); ctx.stroke()
                        ctx.strokeStyle="#1597A8"; ctx.lineWidth=2; ctx.beginPath(); ctx.arc(cx,cy,inputRadius,0,Math.PI*2); ctx.stroke()
                        ctx.strokeStyle="rgba(71,84,103,0.30)"; ctx.lineWidth=1
                        ctx.beginPath(); ctx.moveTo(cx-45,cy); ctx.lineTo(cx+45,cy); ctx.moveTo(cx,cy-45); ctx.lineTo(cx,cy+45); ctx.stroke()
                    }
                    Connections { target: sceneBridge; function onAnalysisChanged() { fiberModeCanvas.requestPaint() } }
                }
                Text { anchors.right:parent.right; anchors.bottom:parent.bottom; text:"青：入射场　蓝：目标模场"; color:"#344054"; font.pixelSize:11 }
            }
            Text {
                color:"#344054"; font.pixelSize:13
                text:"教学接收效率：" + (sceneBridge.receiverEfficiency*100).toFixed(1) + "%"
            }
        }
    }
}
