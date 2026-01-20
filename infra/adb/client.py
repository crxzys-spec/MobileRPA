import base64
import re
import subprocess
import time
from pathlib import Path

from shared.errors import AdbError
from shared.text import is_ascii


UI_DUMP_PATH = "/sdcard/uidump.xml"


def adb_text_escape(text):
    escaped = []
    for ch in text:
        if ch == " ":
            escaped.append("%s")
        elif ch in "\\'\"&|<>;()$`":
            escaped.append("\\" + ch)
        else:
            escaped.append(ch)
    return "".join(escaped)




def extract_hierarchy(xml_text):
    if not xml_text:
        return None
    xml_text = xml_text.replace("\x00", "")
    match = re.search(r"<hierarchy[^>]*>.*</hierarchy>", xml_text, re.DOTALL)
    if not match:
        return None
    return match.group(0).strip()


class AdbClient:
    def __init__(self, adb_path="adb", device_id=None, ime_id=None, restore_ime=False):
        self.adb_path = adb_path
        self.device_id = device_id or None
        self.ime_id = ime_id or None
        self.restore_ime = bool(restore_ime)

    def _base_cmd(self):
        cmd = [self.adb_path]
        if self.device_id:
            cmd += ["-s", self.device_id]
        return cmd

    def run(self, args, timeout=30, check=True, text=True, input_data=None):
        cmd = self._base_cmd() + list(args)
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            timeout=timeout,
            text=text,
        )
        if check and result.returncode != 0:
            raise AdbError(
                "adb failed: {}\n{}".format(" ".join(cmd), result.stderr.strip())
            )
        return result

    def devices(self):
        return [
            device_id
            for device_id, status in self.list_devices()
            if status == "device"
        ]

    def list_devices(self):
        output = self.run(["devices"], timeout=10).stdout.splitlines()
        devices = []
        for line in output[1:]:
            parts = line.split()
            if len(parts) >= 2:
                devices.append((parts[0], parts[1]))
        return devices

    def shell(self, cmd, timeout=30, check=True):
        if isinstance(cmd, str):
            args = ["shell", cmd]
        else:
            args = ["shell"] + list(cmd)
        return self.run(args, timeout=timeout, check=check)

    def exec_out(self, cmd, timeout=30):
        if isinstance(cmd, str):
            args = ["exec-out", cmd]
        else:
            args = ["exec-out"] + list(cmd)
        return self.run(args, timeout=timeout, check=True, text=False)

    def wait_for_device(self, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            if self.devices():
                return
            time.sleep(1)
        raise AdbError("no adb devices found")

    def tap(self, x, y):
        self.shell(["input", "tap", str(x), str(y)])

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.shell(
            [
                "input",
                "swipe",
                str(x1),
                str(y1),
                str(x2),
                str(y2),
                str(duration_ms),
            ]
        )

    def keyevent(self, keycode):
        self.shell(["input", "keyevent", str(keycode)])

    def get_current_ime(self):
        result = self.shell(["settings", "get", "secure", "default_input_method"])
        ime = (result.stdout or "").strip()
        if not ime or ime == "null":
            return None
        return ime

    def enable_ime(self, ime_id):
        if not ime_id:
            return
        self.shell(["ime", "enable", ime_id])

    def set_ime(self, ime_id):
        if not ime_id:
            return
        self.shell(["ime", "set", ime_id])

    def _input_text_via_ime(self, text):
        if not self.ime_id:
            raise AdbError("adb ime id not configured")
        previous = None
        current = None
        if self.restore_ime:
            try:
                current = self.get_current_ime()
            except AdbError:
                current = None
            previous = current
        if current != self.ime_id:
            self.enable_ime(self.ime_id)
            self.set_ime(self.ime_id)
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        try:
            self.shell(
                ["am", "broadcast", "-a", "ADB_INPUT_B64", "--es", "msg", encoded]
            )
        finally:
            if self.restore_ime and previous and previous != self.ime_id:
                self.set_ime(previous)

    def input_text(self, text):
        if text is None:
            return
        text = str(text)
        if not text:
            return
        if is_ascii(text):
            escaped = adb_text_escape(text)
            self.shell(["input", "text", escaped])
            return
        if self.ime_id:
            try:
                self._input_text_via_ime(text)
                return
            except AdbError:
                pass
        try:
            self.shell(["cmd", "clipboard", "set", text])
            self.keyevent(279)
            return
        except AdbError as exc:
            try:
                escaped = adb_text_escape(text)
                self.shell(["input", "text", escaped])
                return
            except AdbError as final_exc:
                raise AdbError(
                    "failed to input non-ASCII text; enable clipboard or configure "
                    "ADB_IME_ID for an ADB keyboard IME on the device"
                ) from final_exc

    def start_app(self, package, activity=None):
        if activity:
            self.shell(["am", "start", "-n", "{}/{}".format(package, activity)])
        else:
            self.shell(
                [
                    "monkey",
                    "-p",
                    package,
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "1",
                ]
            )

    def screenshot(self, output_path):
        Path(output_path).write_bytes(self.screenshot_bytes())

    def screenshot_bytes(self):
        result = self.exec_out(["screencap", "-p"])
        return result.stdout


    def _dump_ui_direct(self):
        candidates = [
            ["uiautomator", "dump", "--compressed", "/dev/tty"],
            ["uiautomator", "dump", "/dev/tty"],
        ]
        for args in candidates:
            try:
                result = self.exec_out(args, timeout=30)
            except AdbError:
                continue
            xml_text = result.stdout.decode("utf-8", errors="replace")
            extracted = extract_hierarchy(xml_text)
            if extracted:
                return extracted
        return None

    def dump_ui(self):
        xml_text = self._dump_ui_direct()
        if xml_text:
            return xml_text
        self.shell(["uiautomator", "dump", UI_DUMP_PATH])
        result = self.exec_out(["cat", UI_DUMP_PATH])
        extracted = extract_hierarchy(
            result.stdout.decode("utf-8", errors="replace")
        )
        if not extracted:
            raise AdbError("failed to extract UI hierarchy")
        return extracted
