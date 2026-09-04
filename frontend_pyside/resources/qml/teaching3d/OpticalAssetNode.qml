import QtQuick
import QtQuick3D

Node {
    id: root
    property var deviceData: ({})
    property vector3d localDragPosition: Qt.vector3d(deviceData.x, deviceData.y, deviceData.z)
    property bool locallyDragging: false
    property bool assetLoadFailed: false
    property bool useDetailed: true
    property bool visualReady: visualLoader.status === Loader3D.Ready

    objectName: "asset:" + deviceData.id
    position: locallyDragging ? localDragPosition : Qt.vector3d(deviceData.x, deviceData.y, deviceData.z)
    eulerRotation.y: deviceData.rotation

    onDeviceDataChanged: root.assetLoadFailed = false

    Loader3D {
        id: visualLoader
        objectName: "visualLoader:" + deviceData.id
        active: root.useDetailed && deviceData.assetQml !== "" && !root.assetLoadFailed
        source: root.useDetailed ? deviceData.assetQml : ""
        asynchronous: true
        onStatusChanged: {
            if (status === Loader3D.Error)
                root.assetLoadFailed = true
        }
    }

    // Primitive fallback remains available if an asset is missing or fails to load.
    Model {
        visible: deviceData.assetQml === "" || !root.useDetailed || root.assetLoadFailed
                || visualLoader.status !== Loader3D.Ready
        source: deviceData.fallbackSource
        eulerRotation.z: deviceData.fallbackRotateZ
        scale: Qt.vector3d(deviceData.fallbackX, deviceData.fallbackY, deviceData.fallbackZ)
        materials: PrincipledMaterial {
            baseColor: deviceData.selected ? "#155EEF" : "#8CA0AF"
            roughness: 0.72
        }
    }

    // Cheap pick proxy: interaction cost is independent of visual model complexity.
    Model {
        id: pickProxy
        objectName: deviceData.id
        property var dragOwner: root
        pickable: true
        source: "#Cube"
        scale: Qt.vector3d(deviceData.pickX, deviceData.pickY, deviceData.pickZ)
        materials: PrincipledMaterial {
            baseColor: "#FFFFFF"
            opacity: 0.002
            alphaMode: PrincipledMaterial.Blend
        }
    }

    // Selection is a separate visual layer and does not require changing the loaded asset.
    Model {
        visible: deviceData.selected
        source: "#Cylinder"
        // Ground-plane selection marker: never float below the optical body.
        // Blue means selection; orange is reserved for candidate/preview state.
        position: Qt.vector3d(0, -61, 0)
        scale: Qt.vector3d(Math.max(0.32, deviceData.pickX * 0.72), 0.008, Math.max(0.32, deviceData.pickZ * 0.72))
        materials: PrincipledMaterial {
            baseColor: "#155EEF"
            opacity: 0.28
            alphaMode: PrincipledMaterial.Blend
            emissiveFactor: Qt.vector3d(0.08, 0.18, 0.38)
        }
    }
}
