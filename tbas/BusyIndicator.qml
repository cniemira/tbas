import QtQuick 2.4
import QtQuick.Controls 1.3

BusyIndicator {
    function start() {
        busyIndication.running = true
    }
    function stop() {
        busyIndication.running = false
    }

    id: busyIndication
    height: 16
    width: 16
    y: 2
}
