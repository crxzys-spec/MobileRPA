import re
import time
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET

from shared.errors import AdbError


class UiAutomatorParser:
    def parse_bounds(self, bounds: str) -> Optional[Tuple[int, int, int, int]]:
        match = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
        if not match:
            return None
        left, top, right, bottom = (int(group) for group in match.groups())
        return left, top, right, bottom

    def iter_nodes(self, xml_text: str) -> Iterable[Dict[str, str]]:
        root = ET.fromstring(xml_text)
        for node in root.iter():
            if node.tag != "node":
                continue
            yield {
                "text": node.attrib.get("text", ""),
                "resource_id": node.attrib.get("resource-id", ""),
                "class": node.attrib.get("class", ""),
                "content_desc": node.attrib.get("content-desc", ""),
                "bounds": node.attrib.get("bounds", ""),
            }

    def find_nodes(self, xml_text: str, text: str, exact: bool = True) -> List[Dict[str, str]]:
        matches: List[Dict[str, str]] = []
        for node in self.iter_nodes(xml_text):
            candidates = [node["text"], node["content_desc"]]
            for candidate in candidates:
                if not candidate:
                    continue
                if exact and candidate == text:
                    matches.append(node)
                    break
                if not exact and text in candidate:
                    matches.append(node)
                    break
        return matches


DEFAULT_PARSER = UiAutomatorParser()


def parse_bounds(bounds: str) -> Optional[Tuple[int, int, int, int]]:
    return DEFAULT_PARSER.parse_bounds(bounds)


def iter_nodes(xml_text: str) -> Iterable[Dict[str, str]]:
    return DEFAULT_PARSER.iter_nodes(xml_text)


def find_nodes(xml_text: str, text: str, exact: bool = True) -> List[Dict[str, str]]:
    return DEFAULT_PARSER.find_nodes(xml_text, text, exact=exact)


def wait_for_text(adb, text: str, exact: bool = True, timeout: float = 10, interval: float = 0.5):
    start = time.time()
    while time.time() - start < timeout:
        xml_text = adb.dump_ui()
        matches = find_nodes(xml_text, text, exact=exact)
        if matches:
            return matches[0]
        time.sleep(interval)
    return None


def tap_node(adb, node, parser: Optional[UiAutomatorParser] = None):
    parser = parser or DEFAULT_PARSER
    bounds = parser.parse_bounds(node.get("bounds"))
    if not bounds:
        raise AdbError("node has no bounds: {}".format(node))
    left, top, right, bottom = bounds
    x = (left + right) // 2
    y = (top + bottom) // 2
    adb.tap(x, y)
