import QtQuick
import QtQuick3D
import QtQuick3D.AssetUtils

Rectangle {
    id: root
    objectName: "teachingV2View3DRoot"
    color: "#C2C8D0"

    // The context object can be cleared while QML is being destroyed during
    // application shutdown. Keep bindings valid until the scene is gone.
    QtObject {
        id: nullBridge
        signal resetCameraRequested()
        signal topViewRequested()
        signal sceneChanged()
        property real beamStartX: 0
        property real beamEndX: 72
        property real axisHeight: 18
        property string selectedLabel: ""
        property string selectedPosition: ""
        property bool gizmoVisible: false
        property real gizmoX: 0
        property real gizmoY: 18
        property real gizmoZ: 0
        property real tableLength: 450
        property real tableWidth: 300
        property real tableThickness: 12.7
        property string boardAlbedo: ""
        property var rays: []
        property var nodes: []
        function dropKindAt(_kind, _x, _y, _z) {}
        function beginGizmoDrag(_mode, _axis, _ox, _oy, _oz, _dx, _dy, _dz) {}
        function selectComponent(_id) {}
        function updateGizmoDrag(_ox, _oy, _oz, _dx, _dy, _dz) {}
        function endGizmoDrag() {}
    }
    property var bridge: (typeof sceneBridge !== "undefined" && sceneBridge) ? sceneBridge : nullBridge

    // 三维移动夹具的尺寸（毫米，与场景同一单位）：轴长、末端箭头、虚线段。
    // 轴要长过镜架外径，否则虚线和箭头大多被镜架挡住。
    readonly property real gizmoAxisLength: 22
    readonly property real gizmoArrowLength: 4.0
    readonly property real gizmoArrowDiameter: 3.4
    readonly property real gizmoRodDiameter: 1.0
    readonly property real gizmoDashLength: 1.0
    readonly property real gizmoDashGap: 1.0
    readonly property int gizmoDashCount: 9
    // 每段虚线的中心位置：首段留 0.5 的间隙，末段停在箭头起点之前。
    readonly property var gizmoDashCenters: {
        var centers = []
        for (var i = 0; i < root.gizmoDashCount; ++i) {
            centers.push(0.5 + i * (root.gizmoDashLength + root.gizmoDashGap)
                         + root.gizmoDashLength * 0.5)
        }
        return centers
    }

    function lookTop() {
        view.camera = topCamera
        var midX = (bridge.beamStartX + bridge.beamEndX) * 0.5
        var spanX = Math.max(bridge.beamEndX - bridge.beamStartX, 72)
        topCamera.position = Qt.vector3d(midX, Math.max(bridge.axisHeight * 4.0, 90), 0)
        topCamera.eulerRotation = Qt.vector3d(-90, 0, 0)
        var mag = 110 / Math.max(spanX * 1.15, 80)
        topCamera.horizontalMagnification = mag
        topCamera.verticalMagnification = mag
        // 程序化换机位后浮标要重新落到新的屏幕位置，不能等鼠标事件。
        root.syncNameTag()
    }

    function useOrbitCamera() {
        view.camera = camera
    }

    function resetCamera() {
        root.useOrbitCamera()
        var midX = (bridge.beamStartX + bridge.beamEndX) * 0.5
        var spanX = Math.max(bridge.beamEndX - bridge.beamStartX, 72)
        cameraPivot.position = Qt.vector3d(midX, Math.max(bridge.axisHeight * 0.45, 8), 0)
        cameraPivot.eulerRotation.x = -22
        cameraPivot.eulerRotation.y = -38
        camera.z = Math.max(spanX * 2.55, 165)
        root.syncNameTag()
    }

    function screenRay(mouse) {
        var nearPoint = view.mapTo3DScene(Qt.vector3d(mouse.x, mouse.y, 0))
        var farPoint = view.mapTo3DScene(Qt.vector3d(mouse.x, mouse.y, 1))
        var direction = farPoint.minus(nearPoint)
        return { ox: nearPoint.x, oy: nearPoint.y, oz: nearPoint.z, dx: direction.x, dy: direction.y, dz: direction.z }
    }

    function placeDroppedKind(kind, px, py) {
        var hit = view.pick(px, py)
        var point = (hit && hit.scenePosition) ? hit.scenePosition : view.mapTo3DScene(Qt.vector3d(px, py, 0.5))
        bridge.dropKindAt(String(kind), point.x, point.y, point.z)
    }

    function syncNameTag() {
        var text = bridge.selectedPosition || ""
        nameTag.visible = bridge.gizmoVisible && text.length > 0
        if (!nameTag.visible)
            return
        nameTagLabel.text = text
        // 标签挂在竖直轴上端之上，不压住箭头。
        var p = view.mapFrom3DScene(Qt.vector3d(
            bridge.gizmoX, bridge.gizmoY + root.gizmoAxisLength + 6, bridge.gizmoZ))
        nameTag.x = p.x - nameTag.width * 0.5
        nameTag.y = p.y - 18
    }

    function dx(a) { return a.x2 - a.x1 }
    function dy(a) { return a.y2 - a.y1 }
    function dz(a) { return a.z2 - a.z1 }
    function length3d(a) {
        return Math.sqrt(dx(a) * dx(a) + dy(a) * dy(a) + dz(a) * dz(a))
    }

    Connections {
        target: bridge
        function onResetCameraRequested() { root.useOrbitCamera(); root.resetCamera() }
        function onTopViewRequested() { root.lookTop() }
        function onSceneChanged() { root.syncNameTag() }
    }

    Component.onCompleted: { root.resetCamera(); root.syncNameTag() }

    View3D {
        id: view
        objectName: "teachingV2Quick3DView"
        anchors.fill: parent
        camera: camera
        property bool boardReady: boardLoader.status === RuntimeLoader.Success
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#C2C8D0"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.Medium
            aoEnabled: false
        }

        Node {
            id: cameraPivot
            position: Qt.vector3d(36, 10, 0)
            eulerRotation.x: -24
            eulerRotation.y: -40
            PerspectiveCamera {
                id: camera
                z: 170
                clipNear: 1
                clipFar: 4000
                fieldOfView: 38
            }
        }

        OrthographicCamera {
            id: topCamera
            y: 110
            eulerRotation.x: -90
            clipNear: 1
            clipFar: 4000
            horizontalMagnification: 1.2
            verticalMagnification: 1.2
        }

        DirectionalLight {
            eulerRotation.x: -42
            eulerRotation.y: -28
            brightness: 1.02
            ambientColor: "#6a7380"
            castsShadow: false
        }
        DirectionalLight {
            eulerRotation.x: -18
            eulerRotation.y: 128
            brightness: 0.38
            ambientColor: "#000000"
            castsShadow: false
        }

        Model {
            pickable: false
            source: "#Cube"
            position: Qt.vector3d(bridge.tableLength * 0.5, -18, 0)
            scale: Qt.vector3d(8.0, 0.004, 8.0)
            materials: PrincipledMaterial { baseColor: "#9AA3AD"; roughness: 1.0; metalness: 0.0 }
        }

        Model {
            objectName: "table"
            pickable: false
            source: "#Cube"
            position: Qt.vector3d(bridge.tableLength * 0.5, -bridge.tableThickness * 0.5, 0)
            scale: Qt.vector3d(
                Math.max(bridge.tableLength, 40) / 100.0,
                Math.max(bridge.tableThickness, 2) / 100.0,
                Math.max(bridge.tableWidth, 40) / 100.0
            )
            materials: PrincipledMaterial {
                baseColor: "#D7DCE2"
                baseColorMap: Texture { source: bridge.boardAlbedo }
                metalness: 0.55
                roughness: 0.42
                specularAmount: 0.34
            }
        }
        Node {
            visible: false
            RuntimeLoader { id: boardLoader; source: "" }
        }

        Repeater3D {
            model: bridge.rays
            delegate: Model {
                required property var modelData
                objectName: "ray:" + modelData.id
                pickable: false
                source: "#Cylinder"
                position: Qt.vector3d((modelData.x1 + modelData.x2) / 2, (modelData.y1 + modelData.y2) / 2, (modelData.z1 + modelData.z2) / 2)
                rotation: Qt.quaternion(modelData.qw, modelData.qx, modelData.qy, modelData.qz)
                scale: Qt.vector3d(
                    Math.max(modelData.radius || 0.55, 0.35) / 50.0,
                    Math.max(root.length3d(modelData), 1) / 100.0,
                    Math.max(modelData.radius || 0.55, 0.35) / 50.0
                )
                materials: PrincipledMaterial {
                    baseColor: "#EF4444"
                    opacity: 0.28 + 0.42 * modelData.power
                    alphaMode: PrincipledMaterial.Blend
                    emissiveFactor: Qt.vector3d(0.85, 0.12, 0.08)
                }
            }
        }

        Repeater3D {
            model: bridge.nodes
            delegate: Node {
                required property var modelData
                property bool stemReady: stemLoader.status === RuntimeLoader.Success
                property bool bodyReady: bodyLoader.status === RuntimeLoader.Success
                property bool stageReady: stageLoader.status === RuntimeLoader.Success
                property bool baseReady: baseLoader.status === RuntimeLoader.Success
                property bool mountReady: mountLoader.status === RuntimeLoader.Success
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                Model {
                    objectName: "node:" + modelData.id
                    pickable: true
                    source: "#Cylinder"
                    y: -(modelData.stemDrop + Math.max(modelData.stemHeight, 4)) * 0.5
                    scale: Qt.vector3d(
                        Math.max(modelData.stemPlaceholderS * 1.35, 0.09),
                        Math.max(modelData.stemDrop + modelData.stemHeight, 12) / 100.0,
                        Math.max(modelData.stemPlaceholderS * 1.35, 0.09)
                    )
                    materials: PrincipledMaterial {
                        baseColor: "#ffffff"
                        opacity: 0
                        alphaMode: PrincipledMaterial.Blend
                    }
                }
                Model {
                    visible: modelData.id === bridge.selectedId
                    pickable: false
                    source: "#Cylinder"
                    scale: Qt.vector3d(
                        (Math.max(modelData.diameterMm, 6) + 4.0) / 100.0,
                        0.014,
                        (Math.max(modelData.diameterMm, 6) + 4.0) / 100.0
                    )
                    materials: PrincipledMaterial {
                        baseColor: "#F59E0B"
                        opacity: 0.4
                        alphaMode: PrincipledMaterial.Blend
                    }
                }
                Node {
                    visible: modelData.hasPostBase === true
                    y: -modelData.y
                    Node {
                        eulerRotation.x: -90
                        Node {
                            position: Qt.vector3d(modelData.baseMeshOx, modelData.baseMeshOy, modelData.baseMeshOz)
                            scale: Qt.vector3d(modelData.baseMeshSx, modelData.baseMeshSy, modelData.baseMeshSz)
                            RuntimeLoader {
                                id: baseLoader
                                visible: baseReady
                                source: modelData.hasBaseMesh === true ? modelData.baseMeshSource : ""
                            }
                        }
                    }
                    Node {
                        visible: !baseReady
                        y: modelData.baseH * 0.5
                        Model {
                            pickable: false
                            source: "#Cube"
                            scale: Qt.vector3d(modelData.baseSx, modelData.baseSy, modelData.baseSz)
                            materials: PrincipledMaterial { baseColor: "#2A3036"; roughness: 0.68; metalness: 0.14 }
                        }
                        Model {
                            pickable: false
                            source: "#Cylinder"
                            y: modelData.baseH * 0.5 + modelData.holderH * 0.5
                            scale: Qt.vector3d(modelData.holderS, modelData.holderH / 100.0, modelData.holderS)
                            materials: PrincipledMaterial { baseColor: "#343A42"; roughness: 0.52; metalness: 0.22 }
                        }
                        Model {
                            pickable: false
                            source: "#Cylinder"
                            x: 12
                            y: modelData.baseH * 0.5 + modelData.holderH * 0.55
                            eulerRotation.z: 90
                            scale: Qt.vector3d(modelData.screwS, modelData.screwLen, modelData.screwS)
                            materials: PrincipledMaterial { baseColor: "#C5C9CE"; roughness: 0.3; metalness: 0.68 }
                        }
                    }
                }
                Model {
                    visible: modelData.hasMountPad === true
                    pickable: false
                    source: "#Cube"
                    y: -(modelData.stemDrop - modelData.padHeight * 0.5)
                    scale: Qt.vector3d(modelData.padSx, modelData.padSy, modelData.padSz)
                    materials: PrincipledMaterial { baseColor: "#2F353C"; roughness: 0.62; metalness: 0.16 }
                }
                Node {
                    y: -modelData.stemDrop
                    visible: modelData.stemHeight > 1
                    Model {
                        objectName: "node:" + modelData.id
                        pickable: true
                        visible: !stemReady
                        source: "#Cylinder"
                        position: Qt.vector3d(0, -modelData.stemHeight * 0.5, 0)
                        scale: Qt.vector3d(modelData.stemPlaceholderS, Math.max(modelData.stemHeight, 0.2) / 100.0, modelData.stemPlaceholderS)
                        materials: PrincipledMaterial { baseColor: "#8B95A0"; roughness: 0.38; metalness: 0.42 }
                    }
                    Node {
                        eulerRotation.x: -90
                        Node {
                            position: Qt.vector3d(modelData.stemOx, modelData.stemOy, modelData.stemOz)
                            scale: Qt.vector3d(modelData.stemSx, modelData.stemSy, modelData.stemSz)
                            RuntimeLoader {
                                id: stemLoader
                                visible: stemReady
                                source: modelData.hasStemMesh === true ? modelData.stemMeshSource : ""
                            }
                        }
                    }
                }
                Node {
                    rotation: Qt.quaternion(modelData.qw, modelData.qx, modelData.qy, modelData.qz)
                    Model {
                        visible: modelData.mountStyle === "ring" && !mountReady
                        pickable: false
                        source: "#Cube"
                        y: modelData.cheekY
                        scale: Qt.vector3d(modelData.cheekSx, modelData.cheekSy, modelData.cheekSz)
                        materials: PrincipledMaterial { baseColor: "#1F242A"; roughness: 0.58; metalness: 0.12 }
                    }
                    Model {
                        visible: modelData.mountStyle === "ring" && !mountReady
                        pickable: false
                        source: "#Cube"
                        y: -modelData.cheekY
                        scale: Qt.vector3d(modelData.cheekSx, modelData.cheekSy, modelData.cheekSz)
                        materials: PrincipledMaterial { baseColor: "#1F242A"; roughness: 0.58; metalness: 0.12 }
                    }
                    Model {
                        visible: modelData.mountStyle === "ring" && !mountReady
                        pickable: false
                        source: "#Cube"
                        z: modelData.saddleZ
                        scale: Qt.vector3d(modelData.saddleSx, modelData.saddleSy, modelData.saddleSz)
                        materials: PrincipledMaterial { baseColor: "#1F242A"; roughness: 0.58; metalness: 0.12 }
                    }
                    Model {
                        visible: false
                        pickable: false
                        source: "#Cube"
                        x: modelData.ringBackX
                        scale: Qt.vector3d(modelData.ringBackSx, modelData.ringBackSy, modelData.ringBackSz)
                        materials: PrincipledMaterial { baseColor: "#1F242A"; roughness: 0.58; metalness: 0.12 }
                    }
                    Model {
                        visible: modelData.mountStyle === "km" && !mountReady
                        pickable: false
                        source: "#Cube"
                        x: modelData.kmX
                        scale: Qt.vector3d(modelData.kmSx, modelData.kmSy, modelData.kmSz)
                        materials: PrincipledMaterial { baseColor: "#1C2127"; roughness: 0.55; metalness: 0.14 }
                    }
                    Model {
                        visible: modelData.mountStyle === "km" && !mountReady
                        pickable: false
                        source: "#Cylinder"
                        x: modelData.knobX
                        y: modelData.knobY
                        z: modelData.knobZ
                        eulerRotation.z: 90
                        scale: Qt.vector3d(modelData.knobS, modelData.knobLen, modelData.knobS)
                        materials: PrincipledMaterial { baseColor: "#C5C9CE"; roughness: 0.28; metalness: 0.72 }
                    }
                    Model {
                        visible: modelData.mountStyle === "km" && !mountReady
                        pickable: false
                        source: "#Cylinder"
                        x: modelData.knobX
                        y: -modelData.knobY
                        z: modelData.knobZ
                        eulerRotation.z: 90
                        scale: Qt.vector3d(modelData.knobS, modelData.knobLen, modelData.knobS)
                        materials: PrincipledMaterial { baseColor: "#C5C9CE"; roughness: 0.28; metalness: 0.72 }
                    }
                    Model {
                        visible: modelData.mountStyle === "clamp" && !mountReady
                        pickable: false
                        source: "#Cube"
                        x: modelData.clampX
                        z: modelData.clampZ
                        scale: Qt.vector3d(modelData.clampSx, modelData.clampSy, modelData.clampSz)
                        materials: PrincipledMaterial { baseColor: "#252B32"; roughness: 0.56; metalness: 0.16 }
                    }
                    Model {
                        visible: modelData.mountStyle === "clamp" && !mountReady
                        pickable: false
                        source: "#Cube"
                        x: modelData.clampX
                        y: modelData.jawY
                        z: modelData.clampZ + 2
                        scale: Qt.vector3d(modelData.clampSx, modelData.jawSy, modelData.jawSz)
                        materials: PrincipledMaterial { baseColor: "#252B32"; roughness: 0.56; metalness: 0.16 }
                    }
                    Model {
                        visible: modelData.mountStyle === "clamp" && !mountReady
                        pickable: false
                        source: "#Cube"
                        x: modelData.clampX
                        y: -modelData.jawY
                        z: modelData.clampZ + 2
                        scale: Qt.vector3d(modelData.clampSx, modelData.jawSy, modelData.jawSz)
                        materials: PrincipledMaterial { baseColor: "#252B32"; roughness: 0.56; metalness: 0.16 }
                    }
                    Model {
                        visible: modelData.mountStyle === "plate" && !mountReady
                        pickable: false
                        source: "#Cube"
                        z: modelData.plateZ
                        scale: Qt.vector3d(modelData.plateSx, modelData.plateSy, modelData.plateSz)
                        materials: PrincipledMaterial { baseColor: "#252B32"; roughness: 0.56; metalness: 0.16 }
                    }
                    Model {
                        objectName: "node:" + modelData.id
                        pickable: true
                        source: "#Sphere"
                        scale: Qt.vector3d(modelData.pickS, modelData.pickS, modelData.pickS)
                        materials: PrincipledMaterial {
                            baseColor: "#ffffff"
                            opacity: 0
                            alphaMode: PrincipledMaterial.Blend
                        }
                    }
                    Node {
                        position: Qt.vector3d(modelData.mountOx, modelData.mountOy, modelData.mountOz)
                        scale: Qt.vector3d(modelData.mountSx, modelData.mountSy, modelData.mountSz)
                        RuntimeLoader {
                            id: mountLoader
                            visible: mountReady
                            source: modelData.hasMountMesh === true ? modelData.mountMeshSource : ""
                        }
                    }
                    Node {
                        position: Qt.vector3d(modelData.meshOx, modelData.meshOy, modelData.meshOz)
                        scale: Qt.vector3d(modelData.sx, modelData.sy, modelData.sz)
                        RuntimeLoader {
                            id: bodyLoader
                            visible: bodyReady
                            source: modelData.hasBodyMesh === true ? modelData.meshSource : ""
                        }
                    }
                    Node {
                        position: Qt.vector3d(modelData.stageOx, modelData.stageOy, modelData.stageOz)
                        scale: Qt.vector3d(modelData.stageSx, modelData.stageSy, modelData.stageSz)
                        RuntimeLoader {
                            id: stageLoader
                            visible: stageReady
                            source: modelData.hasStageMesh === true ? modelData.stageMeshSource : ""
                        }
                    }
                    Model {
                        objectName: "node:" + modelData.id
                        pickable: true
                        visible: !bodyReady
                        source: modelData.shape === "cube" ? "#Cube" : "#Cylinder"
                        position: Qt.vector3d(modelData.fallbackOx, modelData.fallbackOy, modelData.fallbackOz)
                        scale: Qt.vector3d(modelData.fallbackSx, modelData.fallbackSy, modelData.fallbackSz)
                        materials: PrincipledMaterial {
                            baseColor: modelData.id === bridge.selectedId ? "#D97706" : modelData.color
                            roughness: 0.62
                            metalness: 0.05
                        }
                    }
                }
            }
        }

        Node {
            id: gizmo
            visible: bridge.gizmoVisible
            position: Qt.vector3d(bridge.gizmoX, bridge.gizmoY, bridge.gizmoZ)

            // 每条轴画成"虚线 + 末端箭头"。Quick3D 内置 #Cone 的底面在原点、
            // 尖端朝 +Y 且高 100，所以把锥体放在 (轴长 − 箭头长) 处、按箭头长
            // 缩放，尖端正好落在轴端；旋转沿用原来圆柱的朝向。
            // 拾取仍靠一根不可见的整根圆柱，虚线之间的空隙不会漏点。
            Repeater3D {
                model: root.gizmoDashCenters
                delegate: Model {
                    required property var modelData
                    pickable: false
                    source: "#Cylinder"
                    position: Qt.vector3d(modelData, 0, 0)
                    eulerRotation.z: -90
                    scale: Qt.vector3d(root.gizmoRodDiameter / 100, root.gizmoDashLength / 100, root.gizmoRodDiameter / 100)
                    materials: PrincipledMaterial {
                        baseColor: "#FACC15"
                        roughness: 0.35
                        emissiveFactor: Qt.vector3d(0.92, 0.78, 0.12)
                    }
                }
            }
            Model {
                objectName: "gizmo:axis:x"
                pickable: false
                source: "#Cone"
                position: Qt.vector3d(root.gizmoAxisLength - root.gizmoArrowLength, 0, 0)
                eulerRotation.z: -90
                scale: Qt.vector3d(
                    root.gizmoArrowDiameter / 100,
                    root.gizmoArrowLength / 100,
                    root.gizmoArrowDiameter / 100
                )
                materials: PrincipledMaterial {
                    baseColor: "#FACC15"
                    roughness: 0.35
                    emissiveFactor: Qt.vector3d(0.92, 0.78, 0.12)
                }
            }
            Model {
                objectName: "gizmo:axis:x"
                pickable: true
                source: "#Cylinder"
                position: Qt.vector3d(root.gizmoAxisLength * 0.5, 0, 0)
                eulerRotation.z: -90
                scale: Qt.vector3d(0.02, root.gizmoAxisLength / 100, 0.02)
                materials: PrincipledMaterial {
                    baseColor: "#ffffff"
                    opacity: 0
                    alphaMode: PrincipledMaterial.Blend
                }
            }

            Repeater3D {
                model: root.gizmoDashCenters
                delegate: Model {
                    required property var modelData
                    pickable: false
                    source: "#Cylinder"
                    position: Qt.vector3d(0, modelData, 0)
                    scale: Qt.vector3d(root.gizmoRodDiameter / 100, root.gizmoDashLength / 100, root.gizmoRodDiameter / 100)
                    materials: PrincipledMaterial { baseColor: "#2563EB"; roughness: 0.45 }
                }
            }
            Model {
                objectName: "gizmo:axis:z"
                pickable: false
                source: "#Cone"
                position: Qt.vector3d(0, root.gizmoAxisLength - root.gizmoArrowLength, 0)
                scale: Qt.vector3d(
                    root.gizmoArrowDiameter / 100,
                    root.gizmoArrowLength / 100,
                    root.gizmoArrowDiameter / 100
                )
                materials: PrincipledMaterial { baseColor: "#2563EB"; roughness: 0.45 }
            }
            Model {
                objectName: "gizmo:axis:z"
                pickable: true
                source: "#Cylinder"
                position: Qt.vector3d(0, root.gizmoAxisLength * 0.5, 0)
                scale: Qt.vector3d(0.02, root.gizmoAxisLength / 100, 0.02)
                materials: PrincipledMaterial {
                    baseColor: "#ffffff"
                    opacity: 0
                    alphaMode: PrincipledMaterial.Blend
                }
            }

            Repeater3D {
                model: root.gizmoDashCenters
                delegate: Model {
                    required property var modelData
                    pickable: false
                    source: "#Cylinder"
                    position: Qt.vector3d(0, 0, -modelData)
                    eulerRotation.x: -90
                    scale: Qt.vector3d(root.gizmoRodDiameter / 100, root.gizmoDashLength / 100, root.gizmoRodDiameter / 100)
                    materials: PrincipledMaterial { baseColor: "#16A34A"; roughness: 0.45 }
                }
            }
            Model {
                objectName: "gizmo:axis:y"
                pickable: false
                source: "#Cone"
                position: Qt.vector3d(0, 0, -(root.gizmoAxisLength - root.gizmoArrowLength))
                eulerRotation.x: -90
                scale: Qt.vector3d(
                    root.gizmoArrowDiameter / 100,
                    root.gizmoArrowLength / 100,
                    root.gizmoArrowDiameter / 100
                )
                materials: PrincipledMaterial { baseColor: "#16A34A"; roughness: 0.45 }
            }
            Model {
                objectName: "gizmo:axis:y"
                pickable: true
                source: "#Cylinder"
                position: Qt.vector3d(0, 0, -root.gizmoAxisLength * 0.5)
                eulerRotation.x: -90
                scale: Qt.vector3d(0.02, root.gizmoAxisLength / 100, 0.02)
                materials: PrincipledMaterial {
                    baseColor: "#ffffff"
                    opacity: 0
                    alphaMode: PrincipledMaterial.Blend
                }
            }
            Model {
                visible: false
                objectName: "gizmo:plane:xy"
                pickable: false
                source: "#Cube"
                position: Qt.vector3d(8, 0, -8)
                scale: Qt.vector3d(0.10, 0.010, 0.10)
                materials: PrincipledMaterial { baseColor: "#F59E0B"; opacity: 0.38; alphaMode: PrincipledMaterial.Blend }
            }
            Model {
                visible: false
                objectName: "gizmo:plane:xz"
                pickable: false
                source: "#Cube"
                position: Qt.vector3d(6, 6, 0)
                scale: Qt.vector3d(0.07, 0.07, 0.008)
                materials: PrincipledMaterial { baseColor: "#A855F7"; opacity: 0.32; alphaMode: PrincipledMaterial.Blend }
            }
            Model {
                visible: false
                objectName: "gizmo:plane:yz"
                pickable: false
                source: "#Cube"
                position: Qt.vector3d(0, 6, -6)
                scale: Qt.vector3d(0.008, 0.07, 0.07)
                materials: PrincipledMaterial { baseColor: "#0EA5E9"; opacity: 0.32; alphaMode: PrincipledMaterial.Blend }
            }
        }
    }

    MouseArea {
        id: interaction
        z: 2
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        hoverEnabled: true
        property real lastX: 0
        property real lastY: 0
        property bool orbiting: false
        property bool panning: false
        property bool draggingGizmo: false

        onPressed: function(mouse) {
            lastX = mouse.x
            lastY = mouse.y
            orbiting = false
            panning = false
            draggingGizmo = false
            var shiftHeld = (mouse.modifiers & Qt.ShiftModifier) !== 0
            if (mouse.button === Qt.MiddleButton || (mouse.button === Qt.LeftButton && shiftHeld)) {
                panning = true
                return
            }
            if (mouse.button === Qt.RightButton) {
                root.useOrbitCamera()
                orbiting = true
                return
            }
            var hit = view.pick(mouse.x, mouse.y)
            var name = (hit.objectHit && hit.objectHit.objectName) ? hit.objectHit.objectName : ""
            var ctrlHeld = (mouse.modifiers & Qt.ControlModifier) !== 0
            if (name.indexOf("gizmo:") === 0) {
                var parts = name.split(":")
                var ray = root.screenRay(mouse)
                var mode = parts[1]
                if (ctrlHeld && mode === "axis")
                    mode = "rotate"
                bridge.beginGizmoDrag(mode, parts[2], ray.ox, ray.oy, ray.oz, ray.dx, ray.dy, ray.dz)
                draggingGizmo = true
                return
            }
            if (name.indexOf("node:") === 0) {
                bridge.selectComponent(name.substring(5))
                var bodyRay = root.screenRay(mouse)
                bridge.beginGizmoDrag("plane", "xy", bodyRay.ox, bodyRay.oy, bodyRay.oz, bodyRay.dx, bodyRay.dy, bodyRay.dz)
                draggingGizmo = true
                root.syncNameTag()
                return
            }
            root.useOrbitCamera()
            orbiting = true
        }

        onPositionChanged: function(mouse) {
            var mx = mouse.x - lastX
            var my = mouse.y - lastY
            lastX = mouse.x
            lastY = mouse.y
            if (draggingGizmo) {
                var ray = root.screenRay(mouse)
                bridge.updateGizmoDrag(ray.ox, ray.oy, ray.oz, ray.dx, ray.dy, ray.dz)
                root.syncNameTag()
                return
            }
            if (orbiting) {
                root.useOrbitCamera()
                cameraPivot.eulerRotation.y += mx * 0.45
                cameraPivot.eulerRotation.x = Math.max(-89, Math.min(-4, cameraPivot.eulerRotation.x + my * 0.35))
            } else if (panning) {
                cameraPivot.x -= mx * 0.18
                cameraPivot.y += my * 0.18
            }
            root.syncNameTag()
        }

        onReleased: function(mouse) {
            if (draggingGizmo)
                bridge.endGizmoDrag()
            draggingGizmo = false
            orbiting = false
            panning = false
        }

        onWheel: function(wheel) {
            if (draggingGizmo)
                return
            var factor = wheel.angleDelta.y > 0 ? 0.9 : 1.12
            camera.z = Math.max(80, Math.min(480, camera.z * factor))
            root.syncNameTag()
        }
    }

    Rectangle {
        id: nameTag
        visible: false
        enabled: false
        z: 4
        radius: 4
        color: "#E8EEF4"
        border.color: "#64748B"
        border.width: 1
        width: nameTagLabel.implicitWidth + 14
        height: 22
        Text {
            id: nameTagLabel
            anchors.centerIn: parent
            color: "#0F172A"
            font.pixelSize: 12
            font.family: "Microsoft YaHei UI"
        }
    }
}
