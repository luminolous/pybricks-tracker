# Hub program (MicroPython, Pybricks). Never imported on the laptop.
# Static, no Jinja. Probes every port and reports the PUP device id.
# Protocol: .claude/docs/protocol.md, lines R and P.
#
# No watchdog: this program constructs no motors and never drives.

from pybricks.iodevices import PUPDevice
from pybricks.parameters import Port

PROTO_VERSION = 1

print("R,SCAN,{}".format(PROTO_VERSION))

for name, port in (
    ("A", Port.A),
    ("B", Port.B),
    ("C", Port.C),
    ("D", Port.D),
    ("E", Port.E),
    ("F", Port.F),
):
    device_id = 0
    try:
        device_id = PUPDevice(port).info()["id"]
    except OSError:
        device_id = 0
    print("P,{},{}".format(name, device_id))

print("P,DONE,0")
