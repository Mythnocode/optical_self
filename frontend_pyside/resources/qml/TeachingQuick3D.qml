import QtQuick
import QtQuick3D
import QtQuick.Controls

Item {
    id: root
    property var scene: sceneBridge.scene
    property real yaw: 4
    property real pitch: 12
    property real distance: 1750
    property real panX: 0
    property real panY: 0
    property point lastPoint: Qt.point(0, 0)
    property bool draggingCamera: false
    property string activeNodeId: ""
    property bool rotatingNode: false
    property real nodeYaw: 0
    property real nodePitch: 0
    property real nodeRoll: 0
    property real nodeHeight: 82
    property real nodeSceneX: 0
    property real nodeSceneY: 0
    property bool pendingNodeSync: false
    property bool pendingOrientationSync: false
    property vector3d dragPlanePoint: Qt.vector3d(0, 0, 0)
    property real dragPlaneY: 82
    property vector3d grabOffset: Qt.vector3d(0, 0, 0)
    readonly property real primitiveSize: 100
    readonly property real sceneWidth: 1550
    readonly property real sceneDepth: 850
    readonly property real sceneTop: 0
    readonly property real defaultTargetY: 0

    onYawChanged: function() { root.updateCamera() }
    onPitchChanged: function() { root.updateCamera() }
    onDistanceChanged: function() { root.updateCamera() }
    onPanXChanged: function() { root.updateCamera() }
    onPanYChanged: function() { root.updateCamera() }

    function cameraTarget() {
        return Qt.vector3d(root.panX, root.panY + root.defaultTargetY, root.toZ(450))
    }

    function updateCamera() {
        var az = root.yaw * Math.PI / 180
        var el = root.pitch * Math.PI / 180
        var target = cameraTarget()
        camera.position = Qt.vector3d(
            target.x + root.distance * Math.cos(el) * Math.sin(az),
            target.y + root.distance * Math.sin(el),
            target.z + root.distance * Math.cos(el) * Math.cos(az)
        )
        camera.lookAt(target)
    }
    // 映射到 Y-up 世界坐标：X=右，Y=上(高度)，Z=深度(画布向下为负)。
    function toX(x) { return x - 800 }
    function toY(z) { return z }
    function toZ(y) { return 390 - y }

    View3D {
        id: view
        anchors.fill: parent
        camera: camera
        renderMode: View3D.Underlay
        environment: SceneEnvironment {
            clearColor: "#101820"
            backgroundMode: SceneEnvironment.Color
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        PerspectiveCamera {
            id: camera
            clipNear: 1
            clipFar: 10000
            Component.onCompleted: root.updateCamera()
        }

        DirectionalLight { eulerRotation.x: -42; eulerRotation.y: -30; brightness: 1.4 }
        PointLight { position: Qt.vector3d(-800, 700, 600); brightness: 2800; color: "#a9d8ff" }

        Model {
            source: "#Cube"
            position: Qt.vector3d(0, -17, root.toZ(450))
            scale: Qt.vector3d(root.sceneWidth / root.primitiveSize, 34 / root.primitiveSize, root.sceneDepth / root.primitiveSize)
            materials: PrincipledMaterial { baseColor: "#202b33"; metalness: 0.35; roughness: 0.5 }
        }

        Repeater3D {
            model: root.scene.nodes || []
            delegate: Node {
                required property var modelData
                position: Qt.vector3d(
                    root.toX(root.activeNodeId === modelData.id ? root.nodeSceneX : modelData.x),
                    root.toY(root.activeNodeId === modelData.id ? root.nodeHeight : modelData.z),
                    root.toZ(root.activeNodeId === modelData.id ? root.nodeSceneY : modelData.y)
                )
                eulerRotation: Qt.vector3d(
                    root.activeNodeId === modelData.id ? root.nodePitch : modelData.pitch,
                    -(root.activeNodeId === modelData.id ? root.nodeYaw : modelData.yaw),
                    root.activeNodeId === modelData.id ? root.nodeRoll : modelData.roll
                )
                opacity: modelData.enabled ? 1.0 : 0.28
                Model {
                    objectName: modelData.id
                    pickable: true
                    source: modelData.kind === "lens" ? "#Sphere" : modelData.kind === "mirror" ? "#Cylinder" : modelData.kind === "splitter" ? "#Cube" : "#Cylinder"
                    scale: root.componentScale(modelData.kind)
                    materials: PrincipledMaterial {
                        baseColor: modelData.selected ? "#42c8ff" : (modelData.kind === "laser" ? "#d63d43" : modelData.kind === "lens" ? "#3a9ed2" : "#59646c")
                        metalness: 0.45
                        roughness: 0.32
                        emissiveFactor: modelData.selected ? Qt.vector3d(0.05, 0.35, 0.6) : Qt.vector3d(0, 0, 0)
                    }
                }
            }
        }

        Repeater3D {
            model: root.scene.segments || []
            delegate: Node {
                required property var modelData
                property real sx: root.toX(modelData.startX)
                property real sy: root.toY(modelData.startZ)
                property real sz: root.toZ(modelData.startY)
                property real ex: root.toX(modelData.endX)
                property real ey: root.toY(modelData.endZ)
                property real ez: root.toZ(modelData.endY)
                property real dx: ex - sx
                property real dy: ey - sy
                property real dz: ez - sz
                property real length: Math.max(1, Math.sqrt(dx * dx + dy * dy + dz * dz))
                position: Qt.vector3d((sx + ex) * 0.5, (sy + ey) * 0.5, (sz + ez) * 0.5)
                eulerRotation.y: Math.atan2(dx, dz) * 180 / Math.PI
                eulerRotation.x: -Math.atan2(dy, Math.sqrt(dx * dx + dz * dz)) * 180 / Math.PI
                Model {
                    source: "#Cube"
                    scale: root.beamScale(modelData.power, length)
                    materials: PrincipledMaterial {
                        baseColor: "#ff4141"
                        emissiveFactor: Qt.vector3d(1.0, 0.04, 0.03)
                        opacity: modelData.chief ? 0.92 : 0.20
                        roughness: 0.35
                    }
                }
            }
        }
    }

    Timer {
        id: liveSyncTimer
        interval: 33
        repeat: false
        onTriggered: root.flushLiveNodeSync()
    }

    function flushLiveNodeSync() {
        if (root.activeNodeId === "") return
        if (root.pendingOrientationSync) {
            sceneBridge.set_orientation_live(root.activeNodeId, root.nodeYaw, root.nodePitch, root.nodeRoll)
            root.pendingOrientationSync = false
        } else if (root.pendingNodeSync) {
            sceneBridge.move_node_3d_live(root.activeNodeId, root.nodeSceneX, root.nodeSceneY, root.nodeHeight)
            root.pendingNodeSync = false
        }
    }

    function sceneNode(nodeId) {
        var nodes = root.scene.nodes || []
        for (var index = 0; index < nodes.length; index++)
            if (nodes[index].id === nodeId) return nodes[index]
        return null
    }

    function screenRay(mouse) {
        // 用近平面/远平面两个深度点构造穿过鼠标位置的视线射线。
        if (view.camera === null) return null
        var near = view.mapTo3DScene(Qt.vector3d(mouse.x, mouse.y, 0))
        var far = view.mapTo3DScene(Qt.vector3d(mouse.x, mouse.y, 1))
        var dir = far.minus(near)
        return { origin: near, dir: dir }
    }

    function rayPlaneY(ray, planeY) {
        // 求视线与 Y = planeY 水平面的交点；近平行时返回 null。
        if (ray === null) return null
        if (Math.abs(ray.dir.y) < 1.0e-6) return null
        var t = (planeY - ray.origin.y) / ray.dir.y
        if (t < 0) return null
        return ray.origin.plus(ray.dir.times(t))
    }

    function worldToScene(point) {
        return { x: point.x + 800, y: 390 - point.z }
    }

    function activatePick(mouse) {
        var hit = view.pick(mouse.x, mouse.y)
        if (!hit || !hit.objectHit || !hit.objectHit.objectName) return false
        var node = root.sceneNode(hit.objectHit.objectName)
        if (!node) return false
        root.activeNodeId = node.id
        root.pendingNodeSync = false
        root.pendingOrientationSync = false
        root.nodeYaw = node.yaw
        root.nodePitch = node.pitch
        root.nodeRoll = node.roll
        root.nodeHeight = node.z
        root.nodeSceneX = node.x
        root.nodeSceneY = node.y
        root.rotatingNode = (mouse.modifiers & Qt.ControlModifier) !== 0
        // 拖动平面固定在节点当前高度；记录抓取偏移，保证物体不漂移。
        root.dragPlaneY = root.toY(root.nodeHeight)
        var nodeWorld = Qt.vector3d(root.toX(root.nodeSceneX), root.dragPlaneY, root.toZ(root.nodeSceneY))
        var ray = root.screenRay(mouse)
        var planeHit = root.rayPlaneY(ray, root.dragPlaneY)
        if (planeHit) {
            root.dragPlanePoint = planeHit
            root.grabOffset = nodeWorld.minus(planeHit)
        } else {
            root.dragPlanePoint = nodeWorld
            root.grabOffset = Qt.vector3d(0, 0, 0)
        }
        sceneBridge.activate_node(node.id)
        return true
    }

    function moveActiveNode(mouse) {
        // 旋转模式：保持原增量语义。
        if (root.rotatingNode) {
            var dx = mouse.x - root.lastPoint.x
            var dy = mouse.y - root.lastPoint.y
            root.nodeYaw += dx * 0.6
            root.nodePitch = Math.max(-89, Math.min(89, root.nodePitch - dy * 0.35))
            root.pendingOrientationSync = true
            if (!liveSyncTimer.running) liveSyncTimer.start()
            root.lastPoint = Qt.point(mouse.x, mouse.y)
            return
        }
        // 平移模式：射线与拖动平面求交，物体贴住鼠标。
        var ray = root.screenRay(mouse)
        var planeHit = root.rayPlaneY(ray, root.dragPlaneY)
        if (planeHit) {
            var targetWorld = planeHit.plus(root.grabOffset)
            var scene = root.worldToScene(targetWorld)
            root.nodeSceneX = Math.max(45, Math.min(1555, scene.x))
            root.nodeSceneY = Math.max(70, Math.min(830, scene.y))
            root.pendingNodeSync = true
        }
        if (!liveSyncTimer.running) liveSyncTimer.start()
        root.lastPoint = Qt.point(mouse.x, mouse.y)
    }

    function componentScale(kind) {
        if (kind === "lens") return Qt.vector3d(0.62, 0.94, 0.30)
        if (kind === "mirror") return Qt.vector3d(0.66, 0.10, 0.66)
        if (kind === "splitter") return Qt.vector3d(0.74, 0.74, 0.74)
        if (kind === "fiber") return Qt.vector3d(0.90, 0.67, 0.80)
        if (kind === "power_meter") return Qt.vector3d(0.90, 0.50, 0.62)
        if (kind === "laser") return Qt.vector3d(0.84, 0.50, 0.72)
        return Qt.vector3d(0.80, 0.62, 0.72)
    }

    function beamScale(power, length) {
        var width = Math.max(1.8, power * 8.0) / root.primitiveSize
        return Qt.vector3d(width, width, Math.max(1, length) / root.primitiveSize)
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        onPressed: function(mouse) {
            root.lastPoint = Qt.point(mouse.x, mouse.y)
            root.activeNodeId = ""
            root.draggingCamera = false
            if (mouse.button === Qt.LeftButton) root.activatePick(mouse)
            else root.draggingCamera = true
        }
        onReleased: function(mouse) {
            if (mouse.button === Qt.LeftButton && root.activeNodeId !== "") {
                if (liveSyncTimer.running) liveSyncTimer.stop()
                root.flushLiveNodeSync()
                sceneBridge.commit_node_change(root.activeNodeId, root.rotatingNode ? "3D旋转" : "3D移动")
                root.activeNodeId = ""
            }
            root.draggingCamera = false
        }
        onPositionChanged: function(mouse) {
            if (root.activeNodeId !== "" && (pressedButtons & Qt.LeftButton)) {
                root.moveActiveNode(mouse)
                return
            }
            if (!root.draggingCamera) return
            var dx = mouse.x - root.lastPoint.x
            var dy = mouse.y - root.lastPoint.y
            if (pressedButtons & Qt.RightButton) {
                root.yaw += dx * 0.35
                root.pitch = Math.max(-5, Math.min(85, root.pitch - dy * 0.3))
            } else if (pressedButtons & Qt.MiddleButton) {
                root.panX -= dx * 1.5
                root.panY += dy * 1.5
            }
            root.lastPoint = Qt.point(mouse.x, mouse.y)
        }
        onWheel: function(wheel) {
            root.distance = Math.max(500, Math.min(5000, root.distance * (wheel.angleDelta.y > 0 ? 0.88 : 1.14)))
        }
    }

    Rectangle {
        anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 14
        color: "#cc101820"; radius: 4; width: statusText.implicitWidth + 20; height: statusText.implicitHeight + 12
        Text { id: statusText; anchors.centerIn: parent; color: "#d9edf7"; text: "Qt Quick 3D  |  generation " + root.scene.generation + "  |  " + (root.scene.segments || []).length + " beam segments" }
    }
}
