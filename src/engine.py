# engine.py
#
# Copyright 2026 MM 喵了个
#
# SPDX-License-Identifier: LGPL-3.0-or-later

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass, field
from gettext import gettext as _
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst, GLib
    Gst.init(None)
    HAS_GST = True
except Exception:
    HAS_GST = False


def parse_version_tuple(ver_str: Any) -> Tuple[int, ...]:
    """将版本字符串解析为数字元组以便比较（如 '1.0.1' -> (1, 0, 1)）"""
    nums = [int(x) for x in re.findall(r"\d+", str(ver_str or ""))]
    return tuple(nums) if nums else (0,)


def compare_versions(v1: Any, v2: Any) -> int:
    """比较两个版本号。v1 > v2 返回 1；v1 == v2 返回 0；v1 < v2 返回 -1"""
    t1 = parse_version_tuple(v1)
    t2 = parse_version_tuple(v2)
    max_len = max(len(t1), len(t2))
    t1 += (0,) * (max_len - len(t1))
    t2 += (0,) * (max_len - len(t2))
    if t1 > t2:
        return 1
    elif t1 < t2:
        return -1
    return 0


@dataclass
class AudioSegment:
    name: str
    path: str


@dataclass
class PackInfo:
    id: str
    name: str
    path: str
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def version(self) -> str:
        return str(self.config.get("version", "1.0.0"))

    @property
    def city(self) -> str:
        return str(self.config.get("city", ""))

    @property
    def system_type(self) -> str:
        return str(self.config.get("system_type", ""))

    @property
    def description(self) -> str:
        return str(self.config.get("description", ""))


class PackManager:
    """基于 pack.json 声明驱动的多语音包管理器与广播流水线引擎"""

    def __init__(self, packs_root: Optional[str] = None):
        self.packs_root = packs_root or self.get_user_packs_dir()
        self.available_packs: List[PackInfo] = []
        self.current_pack: Optional[PackInfo] = None

        self.stations: List[str] = []
        self.lines: List[str] = []
        self.ads: List[str] = []
        self.transfers: List[str] = []
        self.chimes: List[str] = []
        self.intros: List[str] = []
        self.intro_items: List[Dict[str, str]] = []

        self._files: Dict[str, Dict[str, str]] = {}
        self.discover_packs()

    @staticmethod
    def get_user_packs_dir() -> str:
        """获取遵循 XDG 规范的用户本地语音包存储目录"""
        env_dir = os.environ.get("NEXTSTOP_USER_PACKS_DIR") or os.environ.get("NEXTSTOP_PACKS_DIR")
        if env_dir:
            os.makedirs(env_dir, exist_ok=True)
            return os.path.abspath(env_dir)

        try:
            from gi.repository import GLib
            user_data = GLib.get_user_data_dir()
        except Exception:
            user_data = os.path.expanduser("~/.local/share")

        d = os.path.join(user_data, "nextstop", "packs")
        os.makedirs(d, exist_ok=True)
        return os.path.abspath(d)

    def get_search_dirs(self) -> List[str]:
        """获取所有参与扫描的语音包目录"""
        dirs = [self.get_user_packs_dir()]
        env_dir = os.environ.get("NEXTSTOP_PACKS_DIR")
        if env_dir and os.path.isdir(env_dir):
            abs_env = os.path.abspath(env_dir)
            if abs_env not in dirs:
                dirs.append(abs_env)
        return dirs

    def discover_packs(self):
        """扫描所有可用目录下的报站语音包"""
        self.available_packs = []
        seen_ids = set()

        for search_dir in self.get_search_dirs():
            if not os.path.isdir(search_dir):
                continue

            for entry in sorted(os.listdir(search_dir)):
                pack_path = os.path.join(search_dir, entry)
                if not os.path.isdir(pack_path):
                    continue
                manifest_path = os.path.join(pack_path, "pack.json")
                if not os.path.isfile(manifest_path):
                    continue

                cfg: Dict[str, Any] = {}
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                except Exception:
                    cfg = {}

                pack_id = cfg.get("id", entry)
                if pack_id in seen_ids:
                    continue
                seen_ids.add(pack_id)
                pack_name = cfg.get("name", entry)
                self.available_packs.append(PackInfo(id=pack_id, name=pack_name, path=pack_path, config=cfg))

        if self.available_packs:
            if not self.current_pack or not any(p.id == self.current_pack.id for p in self.available_packs):
                self.load_pack(self.available_packs[0].id)
        else:
            self.current_pack = None
            self.stations = []
            self.lines = []
            self.ads = []
            self.transfers = []
            self.chimes = []
            self.intros = []
            self.intro_items = []
            self._files = {}

    def inspect_zip_pack(self, zip_path: str) -> Tuple[bool, Dict[str, Any]]:
        """预读 zip 包中的 pack.json，检查元数据并与已安装包对比版本"""
        if not os.path.isfile(zip_path):
            return False, {"error": _("Specified ZIP file does not exist")}

        if not zipfile.is_zipfile(zip_path):
            return False, {"error": _("Selected file is not a valid ZIP archive (packs must be .zip format)")}

        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                names = z.namelist()
                pack_json_candidates = [
                    n for n in names
                    if os.path.basename(n).lower() == "pack.json" and not n.startswith("__MACOSX")
                ]
                if not pack_json_candidates:
                    return False, {"error": _("No pack.json found inside the archive, cannot recognize as a NextStop pack")}

                pack_json_candidates.sort(key=lambda s: s.count("/"))
                target_json = pack_json_candidates[0]

                raw_data = z.read(target_json)
                try:
                    cfg = json.loads(raw_data.decode("utf-8"))
                except Exception as e:
                    return False, {"error": _("Failed to parse pack.json: {e}").format(e=e)}

                pack_name = cfg.get("name", "")
                pack_id = cfg.get("id", "")
                if not pack_id:
                    parent_dir = os.path.dirname(target_json)
                    if parent_dir:
                        pack_id = os.path.basename(parent_dir)
                    else:
                        pack_id = os.path.splitext(os.path.basename(zip_path))[0]

                pack_id = re.sub(r"[^\w\-.]", "_", pack_id).strip("_") or "imported_pack"
                new_version = str(cfg.get("version", "1.0.0"))

                existing = next((p for p in self.available_packs if p.id == pack_id), None)
                if existing:
                    old_version = existing.version
                    cmp_res = compare_versions(new_version, old_version)
                else:
                    old_version = ""
                    cmp_res = None

                return True, {
                    "id": pack_id,
                    "name": pack_name or pack_id,
                    "version": new_version,
                    "existing": existing,
                    "existing_version": old_version,
                    "cmp": cmp_res,
                    "config": cfg,
                }
        except Exception as e:
            return False, {"error": _("Failed to inspect zip archive: {e}").format(e=e)}

    def import_zip_pack(self, zip_path: str) -> Tuple[bool, str, str]:
        """从 ZIP 压缩包导入语音包至用户数据目录

        Returns:
            (success, pack_id, message)
        """
        if not os.path.isfile(zip_path):
            return False, "", _("Specified ZIP file does not exist")

        if not zipfile.is_zipfile(zip_path):
            return False, "", _("Selected file is not a valid ZIP archive (packs must be .zip format)")

        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                names = z.namelist()
                pack_json_candidates = [
                    n for n in names
                    if os.path.basename(n).lower() == "pack.json" and not n.startswith("__MACOSX")
                ]
                if not pack_json_candidates:
                    return False, "", _("No pack.json found inside the archive, cannot recognize as a NextStop pack")

                # 选取路径深度最短的 pack.json
                pack_json_candidates.sort(key=lambda s: s.count("/"))
                target_json = pack_json_candidates[0]

                raw_data = z.read(target_json)
                try:
                    cfg = json.loads(raw_data.decode("utf-8"))
                except Exception as e:
                    return False, "", _("Failed to parse pack.json: {e}").format(e=e)

                pack_name = cfg.get("name", "")
                pack_id = cfg.get("id", "")
                if not pack_id:
                    parent_dir = os.path.dirname(target_json)
                    if parent_dir:
                        pack_id = os.path.basename(parent_dir)
                    else:
                        pack_id = os.path.splitext(os.path.basename(zip_path))[0]

                pack_id = re.sub(r"[^\w\-.]", "_", pack_id).strip("_") or "imported_pack"
                new_version = str(cfg.get("version", "1.0.0"))

                existing = next((p for p in self.available_packs if p.id == pack_id), None)
                is_update = existing is not None

                prefix = os.path.dirname(target_json)
                if prefix and not prefix.endswith("/"):
                    prefix += "/"

                user_packs = self.get_user_packs_dir()
                dest_dir = os.path.join(user_packs, pack_id)
                dest_dir_real = os.path.abspath(dest_dir)

                if os.path.exists(dest_dir):
                    shutil.rmtree(dest_dir)
                os.makedirs(dest_dir, exist_ok=True)

                for member in z.infolist():
                    m_name = member.filename
                    if m_name.startswith("__MACOSX"):
                        continue
                    if prefix:
                        if not m_name.startswith(prefix):
                            continue
                        rel_name = m_name[len(prefix):]
                    else:
                        rel_name = m_name

                    if not rel_name:
                        continue

                    target_file = os.path.abspath(os.path.join(dest_dir, rel_name))
                    if not target_file.startswith(dest_dir_real):
                        raise RuntimeError(_("Illegal path traversal detected in archive: {name}").format(name=m_name))

                    if member.is_dir():
                        os.makedirs(target_file, exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(target_file), exist_ok=True)
                        with z.open(member) as s_fp, open(target_file, "wb") as d_fp:
                            shutil.copyfileobj(s_fp, d_fp)

            self.discover_packs()
            self.load_pack(pack_id)
            display_name = pack_name or pack_id
            if is_update:
                return True, pack_id, _("Successfully updated announcement pack: {name} (v{version})").format(
                    name=display_name, version=new_version
                )
            return True, pack_id, _("Successfully imported announcement pack: {name}").format(name=display_name)

        except Exception as e:
            return False, "", _("Failed to import pack: {e}").format(e=e)

    def delete_pack(self, pack_id: str) -> Tuple[bool, str]:
        """删除指定的用户本地语音包"""
        pack = next((p for p in self.available_packs if p.id == pack_id), None)
        if not pack:
            return False, _("Specified pack not found")

        user_packs = os.path.abspath(self.get_user_packs_dir())
        pack_path = os.path.abspath(pack.path)
        if not pack_path.startswith(user_packs):
            return False, _("Can only delete user-imported packs")

        try:
            shutil.rmtree(pack_path)
            self.discover_packs()
            return True, _("Deleted announcement pack: {name}").format(name=pack.name)
        except Exception as e:
            return False, _("Failed to delete pack: {e}").format(e=e)

    def load_pack(self, pack_id: str) -> bool:
        """加载或重新扫描指定的语音包"""
        target = None
        for p in self.available_packs:
            if p.id == pack_id or p.name == pack_id:
                target = p
                break
        if not target:
            return False

        # 重新读取 pack.json 以支持热刷新
        manifest_path = os.path.join(target.path, "pack.json")
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    target.config = json.load(f)
                    target.name = target.config.get("name", target.name)
            except Exception:
                pass

        self.current_pack = target
        self._scan_pack_files(target)
        return True

    def reload_current_pack(self):
        """热刷新当前语音包目录（无需重启应用即可识别新剪辑的音频）"""
        current_id = self.current_pack.id if self.current_pack else None
        self.discover_packs()
        if current_id:
            self.load_pack(current_id)

    def _scan_pack_files(self, pack: PackInfo):
        self._files = {}
        pack_dir = pack.path
        for sub in sorted(os.listdir(pack_dir)):
            sub_dir = os.path.join(pack_dir, sub)
            if not os.path.isdir(sub_dir):
                continue
            self._files[sub] = {}
            for fname in sorted(os.listdir(sub_dir)):
                if fname.lower().endswith((".flac", ".wav", ".mp3", ".ogg")):
                    stem = os.path.splitext(fname)[0]
                    self._files[sub][stem] = os.path.join(sub_dir, fname)

        cfg = pack.config
        dirs_cfg = cfg.get("directories", {})
        st_dir = dirs_cfg.get("stations", "站名")
        ln_dir = dirs_cfg.get("lines", "线路名")
        ad_dir = dirs_cfg.get("ads", "广告")

        intro_dir = dirs_cfg.get("intros", "站点介绍")
        intro_files = self._files.get(intro_dir, {})

        self.stations = sorted(list(self._files.get(st_dir, {}).keys()))
        self.lines = sorted(list(self._files.get(ln_dir, {}).keys()))
        self.ads = ["无广告"] + sorted(list(self._files.get(ad_dir, {}).keys()))

        # 读取站点介绍（从 pack.json 或自动扫描“站点介绍”目录）
        self.intro_items = []
        seen_files = set()
        for item in cfg.get("intros", []):
            lbl = item.get("label", "")
            f_rel = item.get("file", "")
            if lbl and f_rel:
                self.intro_items.append({"label": lbl, "file": f_rel})
                seen_files.add(f_rel)
                seen_files.add(os.path.basename(f_rel))

        for stem, abs_path in intro_files.items():
            if stem not in seen_files:
                lbl = stem
                for st in self.stations:
                    st_clean = st[:-1] if st.endswith("站") else st
                    if st_clean and st_clean in stem:
                        lbl = st_clean
                        break
                self.intro_items.append({"label": lbl, "file": f"{intro_dir}/{stem}"})

        self.intros = [it["label"] for it in self.intro_items]

        # 读取提示音配置
        chimes_cfg = cfg.get("chimes", [])
        if chimes_cfg:
            self.chimes = [c.get("label", "提示音") for c in chimes_cfg]
        else:
            self.chimes = []

        # 读取换乘配置
        transfers_cfg = cfg.get("transfers", [])
        if transfers_cfg:
            self.transfers = [t.get("label", "") for t in transfers_cfg if t.get("label")]
        else:
            self.transfers = []

    @property
    def config(self) -> Dict[str, Any]:
        return self.current_pack.config if self.current_pack else {}

    def get_switches(self, placement: Optional[str] = None) -> List[Dict[str, Any]]:
        switches = self.config.get("switches", [])
        if placement is None:
            return switches
        return [s for s in switches if s.get("placement") == placement]

    def get_station_triggers(self) -> List[Dict[str, Any]]:
        return self.config.get("station_triggers", [])

    def get_matching_triggers(self, station_name: str) -> List[Dict[str, Any]]:
        if not station_name:
            return []
        st = station_name.strip()
        matched = []
        for trig in self.get_station_triggers():
            keywords = trig.get("keywords", [])
            if any(kw in st for kw in keywords):
                matched.append(trig)
        return matched

    def get_quick_clips(self) -> List[Dict[str, Any]]:
        return self.config.get("quick_clips", [])

    def resolve_rel_file(self, rel_spec: str) -> Optional[str]:
        """解析形如 '站前广播/车辆启动，请扶好坐好' 的相对引用"""
        if not rel_spec or "/" not in rel_spec:
            return None
        cat, key = rel_spec.split("/", 1)
        return self.get_file(cat, key)

    def get_file(self, category: str, key: str) -> Optional[str]:
        cat_dict = self._files.get(category, {})
        if key in cat_dict:
            return cat_dict[key]
        for k, v in cat_dict.items():
            if k.startswith(key):
                return v
        candidates = [k for k in cat_dict.keys() if key in k]
        if candidates:
            best = min(candidates, key=len)
            return cat_dict[best]
        return None

    def get_station_audio(self, station_name: str) -> Optional[str]:
        """智能查找站点音频（支持 带/不带 '站' 后缀）"""
        if not station_name:
            return None
        st = station_name.strip()
        st_dir = self.config.get("directories", {}).get("stations", "站名")
        f = self.get_file(st_dir, st)
        if not f and not st.endswith("站"):
            f = self.get_file(st_dir, st + "站")
        if not f and st.endswith("站"):
            f = self.get_file(st_dir, st[:-1])
        return f

    def get_line_audio(self, line_name: str) -> Optional[str]:
        """智能查找线路音频（支持带/不带空格或 '路' 后缀）"""
        if not line_name:
            return None
        ln = line_name.strip()
        ln_dir = self.config.get("directories", {}).get("lines", "线路名")
        f = self.get_file(ln_dir, ln)
        if f:
            return f
        # 忽略空格匹配（如输入 "1路" 匹配 "1 路无人售票车"）
        norm_ln = ln.replace(" ", "")
        cat_dict = self._files.get(ln_dir, {})
        for k, v in cat_dict.items():
            norm_k = k.replace(" ", "")
            if norm_k == norm_ln or norm_k.startswith(norm_ln):
                return v
        if not norm_ln.endswith("路"):
            norm_ln_lu = norm_ln + "路"
            for k, v in cat_dict.items():
                norm_k = k.replace(" ", "")
                if norm_k == norm_ln_lu or norm_k.startswith(norm_ln_lu):
                    return v
        return None

    def get_intro_audio(self, query: str) -> Optional[Tuple[str, str]]:
        """智能查找站点特色介绍录音，返回 (显示标签, 音频路径)"""
        if not query:
            return None
        q = query.strip()
        intro_dir = self.config.get("directories", {}).get("intros", "站点介绍")

        # 1. 优先从 intro_items 匹配 label 或 file
        for item in self.intro_items:
            lbl = item.get("label", "")
            f_rel = item.get("file", "")
            if q == lbl or q in lbl or lbl in q:
                resolved = self.resolve_rel_file(f_rel)
                if resolved:
                    return (lbl, resolved)
            if q in f_rel:
                resolved = self.resolve_rel_file(f_rel)
                if resolved:
                    return (lbl or q, resolved)

        # 2. 从扫描到的“站点介绍”目录文件模糊匹配
        cat_dict = self._files.get(intro_dir, {})
        if q in cat_dict:
            return (q, cat_dict[q])

        q_clean = q[:-1] if q.endswith("站") else q
        for stem, path in cat_dict.items():
            if q in stem or q_clean in stem or stem in q:
                return (q_clean, path)

        return None

    def resolve_chime(self, chime_label: str) -> Optional[AudioSegment]:
        for c in self.config.get("chimes", []):
            if c.get("label") == chime_label:
                f = self.resolve_rel_file(c.get("file", ""))
                if f:
                    return AudioSegment("进站叮咚", f)
        f = self.get_file("到站广播", "提示音2" if "2" in chime_label else "提示音1")
        return AudioSegment("进站叮咚", f) if f else None

    def resolve_transfer_segments(self, transfer_input: Any, switch_states: Dict[str, bool]) -> List[AudioSegment]:
        if isinstance(transfer_input, str):
            transfer_labels = [transfer_input] if transfer_input and transfer_input != "无换乘" else []
        elif isinstance(transfer_input, (list, tuple)):
            transfer_labels = [l for l in transfer_input if l and l != "无换乘"]
        else:
            transfer_labels = []

        segs: List[AudioSegment] = []
        if not transfer_labels:
            f_alight = self.get_file("站前广播", "请携带好随身物品，准备下车")
            if f_alight:
                segs.append(AudioSegment("下车准备", f_alight))
            return segs

        f_prefix = self.get_file("地铁换乘", "有转乘")
        if f_prefix:
            segs.append(AudioSegment("换乘引导", f_prefix))

        for line_label in transfer_labels:
            f_line = None
            for t in self.config.get("transfers", []):
                if t.get("label") == line_label and t.get("file"):
                    f_line = self.resolve_rel_file(t["file"])
                    break
            if not f_line:
                f_line = self.get_file("地铁换乘", line_label)
            if f_line:
                segs.append(AudioSegment(line_label, f_line))

        # 判断是否启用 225 路式换乘尾音
        if switch_states.get("transfer_225_style", False):
            f_p = self.get_file("地铁换乘", "的乘客")
            f_r = self.get_file("地铁换乘", "请准备下车")
            f_a = self.get_file("站前广播", "请携带好随身物品，准备下车")
            if f_p: segs.append(AudioSegment("的乘客", f_p))
            if f_r: segs.append(AudioSegment("请准备下车", f_r))
            if f_a: segs.append(AudioSegment("下车准备", f_a))
        else:
            f_suffix = self.get_file("地铁换乘", "的乘客，请携带好随身物品，准备下车")
            if f_suffix:
                segs.append(AudioSegment("换乘下车准备", f_suffix))
            else:
                f_r = self.get_file("地铁换乘", "请准备下车")
                if f_r: segs.append(AudioSegment("换乘准备", f_r))

        return segs

    def execute_pipeline(
        self,
        pipeline_name: str,
        slots: Dict[str, str],
        switch_states: Dict[str, bool],
        trigger_states: Optional[Dict[str, bool]] = None,
    ) -> List[AudioSegment]:
        """根据 pack.json 中的 pipelines 定义动态拼装广播序列"""
        trigger_states = trigger_states or {}
        pipelines = self.config.get("pipelines", {})
        steps = pipelines.get(pipeline_name, [])
        if not steps:
            return []

        queue: List[AudioSegment] = []
        ln_dir = self.config.get("directories", {}).get("lines", "线路名")
        ad_dir = self.config.get("directories", {}).get("ads", "广告")

        for step in steps:
            cond = step.get("when")
            if cond:
                if cond.startswith("!"):
                    if switch_states.get(cond[1:], False):
                        continue
                else:
                    if not switch_states.get(cond, False):
                        continue

            stype = step.get("type", "file")
            if stype == "file":
                f = self.resolve_rel_file(step.get("file", ""))
                if f:
                    queue.append(AudioSegment(step.get("label", _("Announcement Segment")), f))

            elif stype == "station":
                slot_key = step.get("slot", "station")
                st_name = slots.get(slot_key, "")
                f_st = self.get_station_audio(st_name)
                if not f_st:
                    return []
                queue.append(AudioSegment(_("Station: {name}").format(name=st_name), f_st))

            elif stype == "line":
                slot_key = step.get("slot", "line")
                line_name = slots.get(slot_key, "")
                f_ln = self.get_line_audio(line_name)
                if not f_ln:
                    return []
                queue.append(AudioSegment(_("Route: {name}").format(name=line_name), f_ln))

            elif stype == "chime":
                slot_key = step.get("slot", "chime")
                chime_seg = self.resolve_chime(slots.get(slot_key, "提示音 1"))
                if chime_seg:
                    queue.append(chime_seg)

            elif stype == "ad":
                slot_key = step.get("slot", "ad")
                ad_name = slots.get(slot_key, "无广告")
                if ad_name and ad_name != "无广告":
                    f_ad = self.get_file(ad_dir, ad_name)
                    if f_ad:
                        queue.append(AudioSegment(_("Commercial: {name}").format(name=ad_name), f_ad))

            elif stype == "transfer":
                slot_key = step.get("slot", "transfer")
                transfer_data = slots.get(slot_key, [])
                queue.extend(self.resolve_transfer_segments(transfer_data, switch_states))

            elif stype == "intro":
                slot_key = step.get("slot", "intro")
                intro_val = slots.get(slot_key, "")
                if intro_val and intro_val not in ("无", "无介绍", "不插播", "不插播介绍"):
                    intro_match = self.get_intro_audio(intro_val)
                    if intro_match:
                        intro_label, f_intro = intro_match
                        queue.append(AudioSegment(_("Station Intro: {name}").format(name=intro_label), f_intro))

            elif stype == "trigger":
                trig_id = step.get("trigger_id", "")
                if trigger_states.get(trig_id, False):
                    for trig in self.get_station_triggers():
                        if trig.get("id") == trig_id:
                            f_tr = self.resolve_rel_file(trig.get("file", ""))
                            if f_tr:
                                queue.append(AudioSegment(trig.get("label", trig.get("title", _("Special Intro"))), f_tr))

        return queue


class AudioPlayer:
    """基于 GStreamer 的流式平滑播放器（支持暂停、停止、跳过当前片段、内外报双声道扬声器路由）"""

    def __init__(self):
        self.playbin = None
        self.queue: List[AudioSegment] = []
        self.current_index: int = -1
        self.current_title: str = ""
        self.current_channel: str = "inside"
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.is_muted: bool = False

        self.inside_device_id: str = "default"
        self.outside_device_id: str = "default"
        self._cached_devices: List[Dict[str, Any]] = []

        self.on_segment_start: Optional[Callable[[str, int, int, str], None]] = None
        self.on_pause_changed: Optional[Callable[[bool], None]] = None
        self.on_finished: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

        self.load_preferences()

        self.device_monitor = None
        if HAS_GST:
            self.playbin = Gst.ElementFactory.make("playbin", "nextstop-player")
            if self.playbin:
                bus = self.playbin.get_bus()
                bus.add_signal_watch()
                bus.connect("message", self._on_bus_message)
            try:
                self.device_monitor = Gst.DeviceMonitor.new()
                self.device_monitor.add_filter("Audio/Sink", None)
                self.device_monitor.start()
            except Exception:
                self.device_monitor = None

    def _get_prefs_path(self) -> str:
        if HAS_GST and GLib is not None:
            cfg_root = GLib.get_user_config_dir()
        else:
            cfg_root = os.path.expanduser("~/.config")
        return os.path.join(cfg_root, "nextstop", "preferences.json")

    def load_preferences(self):
        path = self._get_prefs_path()
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.inside_device_id = data.get("inside_device_id", "default") or "default"
                self.outside_device_id = data.get("outside_device_id", "default") or "default"
            except Exception:
                pass

    def save_preferences(self):
        path = self._get_prefs_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "inside_device_id": self.inside_device_id,
                        "outside_device_id": self.outside_device_id,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass

    def _run_pactl(self, args: List[str], prefer_host: bool = False) -> Optional[str]:
        """调用 pactl 查询或切换 PipeWire / PulseAudio 声卡端口与配置文件"""
        env = dict(os.environ)
        env["LC_ALL"] = "C"

        rt_base = "/var/lib/flatpak/runtime/org.gnome.Platform/x86_64/50/active/files"
        ld_bin = os.path.join(rt_base, "lib64", "ld-linux-x86-64.so.2")
        lib_dir = os.path.join(rt_base, "lib", "x86_64-linux-gnu")
        pa_lib_dir = os.path.join(lib_dir, "pulseaudio")
        rt_pactl = os.path.join(rt_base, "bin", "pactl")

        candidate_cmds: List[List[str]] = []
        in_flatpak = os.path.exists("/.flatpak-info")
        flatpak_spawn = shutil.which("flatpak-spawn")

        if prefer_host and in_flatpak and flatpak_spawn:
            # WirePlumber 限制了 Flatpak 沙盒内的客户端修改声卡 Profile（返回“拒绝访问”），
            # 因此切换声卡 Profile / Port 时通过 flatpak-spawn --host 在宿主会话执行
            candidate_cmds.append([flatpak_spawn, "--host", "--env=LC_ALL=C", "pactl"] + args)
            candidate_cmds.append(
                [
                    flatpak_spawn,
                    "--host",
                    "--env=LC_ALL=C",
                    ld_bin,
                    "--library-path",
                    f"{lib_dir}:{pa_lib_dir}",
                    rt_pactl,
                ]
                + args
            )

        pactl_bin = shutil.which("pactl")
        if pactl_bin:
            candidate_cmds.append([pactl_bin] + args)
        elif os.path.isfile(ld_bin) and os.path.isfile(rt_pactl):
            candidate_cmds.append(
                [ld_bin, "--library-path", f"{lib_dir}:{pa_lib_dir}", rt_pactl] + args
            )

        for cmd in candidate_cmds:
            try:
                res = subprocess.run(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2.5,
                )
                if res.returncode == 0:
                    return res.stdout
            except Exception:
                continue
        return None

    def _run_pactl_json(self, subcmd: str) -> Any:
        out = self._run_pactl(["--format=json", "list", subcmd])
        if not out:
            return None
        idx = out.find("[")
        if idx < 0:
            return None
        try:
            return json.loads(out[idx:])
        except Exception:
            return None

    def list_output_devices(self) -> List[Dict[str, Any]]:
        """枚举系统可用音频输出设备（包含同声卡下的 Speaker / Headphones 独立端口及各输出 Sink）"""
        result: List[Dict[str, Any]] = [
            {"id": "default", "name": _("System Default Device"), "gst_device": None}
        ]
        seen_ids = {"default"}
        covered_cards = set()

        # 1. 优先通过 PipeWire-Pulse (pactl) 扫描声卡的所有输出端口（如 Speaker 与 Headphones）
        cards = self._run_pactl_json("cards")
        if isinstance(cards, list):
            for card in cards:
                card_name = card.get("name", "")
                if not card_name:
                    continue
                props = card.get("properties", {}) or {}
                card_desc = (
                    props.get("device.description")
                    or props.get("device.product.name")
                    or props.get("alsa.card_name")
                    or card_name
                )
                profiles = card.get("profiles", {}) or {}
                ports = card.get("ports", {}) or {}

                for port_name, port_info in ports.items():
                    if not isinstance(port_info, dict):
                        continue
                    if port_info.get("availability") == "not available":
                        continue

                    p_props = port_info.get("properties", {}) or {}
                    p_type = (p_props.get("port.type") or "").lower()
                    if (
                        port_name.startswith("[In]")
                        or "input" in port_name.lower()
                        or p_type == "mic"
                    ):
                        continue

                    # 筛选包含输出通道（sinks > 0）且可用的最高优先级 Profile
                    candidate_profiles = []
                    for prof_name in port_info.get("profiles", []) or []:
                        prof_data = profiles.get(prof_name, {})
                        if isinstance(prof_data, dict):
                            if prof_data.get("sinks", 0) > 0 and prof_data.get("available", True) is not False:
                                candidate_profiles.append((prof_data.get("priority", 0), prof_name))

                    if not candidate_profiles:
                        continue

                    candidate_profiles.sort(key=lambda x: x[0], reverse=True)
                    best_profile = candidate_profiles[0][1]
                    port_desc = port_info.get("description") or port_name
                    dev_id = f"card_port:{card_name}|{port_name}|{best_profile}"
                    if dev_id not in seen_ids:
                        seen_ids.add(dev_id)
                        covered_cards.add(card_name)
                        result.append(
                            {
                                "id": dev_id,
                                "name": f"{port_desc} - {card_desc}",
                                "gst_device": None,
                            }
                        )

        # 2. 补充不属于上述声卡端口的独立 Sink（如蓝牙虚拟设备、网络音频、独立无端口声卡等）
        sinks = self._run_pactl_json("sinks")
        if isinstance(sinks, list):
            for sink in sinks:
                sink_name = sink.get("name", "")
                if not sink_name:
                    continue
                s_props = sink.get("properties", {}) or {}
                parent_card = s_props.get("device.name", "")
                if parent_card and parent_card in covered_cards:
                    continue
                sink_desc = sink.get("description") or s_props.get("node.nick") or sink_name
                dev_id = f"sink:{sink_name}"
                if dev_id not in seen_ids:
                    seen_ids.add(dev_id)
                    result.append(
                        {
                            "id": dev_id,
                            "name": sink_desc,
                            "gst_device": None,
                        }
                    )

        # 3. 若 pactl 未返回设备，回退使用长驻 GStreamer DeviceMonitor
        if len(result) == 1 and HAS_GST and self.device_monitor is not None:
            try:
                devices = self.device_monitor.get_devices() or []
                for dev in devices:
                    disp_name = dev.get_display_name() or dev.get_name() or _("Audio Output Device")
                    dev_id = dev.get_name() or disp_name
                    props = dev.get_properties()
                    if props:
                        for key in ("node.name", "object.serial"):
                            val = props.get_string(key)
                            if val:
                                dev_id = val
                                break
                    if dev_id not in seen_ids:
                        seen_ids.add(dev_id)
                        result.append(
                            {
                                "id": dev_id,
                                "name": disp_name,
                                "gst_device": dev,
                            }
                        )
            except Exception:
                pass

        self._cached_devices = result
        return result

    def _apply_channel_sink(self, channel: str):
        """根据广播通道（inside 内报 / outside 外报）切换 PipeWire 端口/配置文件与 GStreamer 输出扬声器"""
        if not self.playbin or not HAS_GST:
            return

        target_id = self.outside_device_id if channel == "outside" else self.inside_device_id
        if not target_id or target_id == "default":
            self.playbin.set_property("audio-sink", None)
            return

        # 处理声卡端口路由（如在同声卡的 Speaker 与 Headphones 之间自动切换）
        if target_id.startswith("card_port:"):
            parts = target_id[len("card_port:"):].split("|", 2)
            if len(parts) == 3:
                card_name, port_name, profile_name = parts
                cards = self._run_pactl_json("cards")
                profile_changed = False
                if isinstance(cards, list):
                    for c in cards:
                        if c.get("name") == card_name:
                            if c.get("active_profile") != profile_name:
                                self._run_pactl(
                                    ["set-card-profile", card_name, profile_name],
                                    prefer_host=True,
                                )
                                profile_changed = True
                            break

                target_sink_name = None
                max_attempts = 8 if profile_changed else 1
                for attempt in range(max_attempts):
                    if attempt > 0:
                        time.sleep(0.05)
                    sinks = self._run_pactl_json("sinks")
                    if isinstance(sinks, list):
                        for s in sinks:
                            s_props = s.get("properties", {}) or {}
                            if s_props.get("device.name") == card_name:
                                target_sink_name = s.get("name")
                                if s.get("active_port") != port_name:
                                    self._run_pactl(
                                        ["set-sink-port", target_sink_name, port_name],
                                        prefer_host=True,
                                    )
                                break
                    if target_sink_name:
                        break

                if target_sink_name:
                    try:
                        pulse = Gst.ElementFactory.make("pulsesink", None)
                        if pulse:
                            pulse.set_property("device", target_sink_name)
                            self.playbin.set_property("audio-sink", pulse)
                            return
                    except Exception:
                        pass
            self.playbin.set_property("audio-sink", None)
            return

        if target_id.startswith("sink:"):
            sink_name = target_id[len("sink:"):]
            try:
                pulse = Gst.ElementFactory.make("pulsesink", None)
                if pulse:
                    pulse.set_property("device", sink_name)
                    self.playbin.set_property("audio-sink", pulse)
                    return
            except Exception:
                pass
            self.playbin.set_property("audio-sink", None)
            return

        if not self._cached_devices:
            self.list_output_devices()

        sink_elem = None
        for item in self._cached_devices:
            if item.get("id") == target_id and item.get("gst_device") is not None:
                try:
                    sink_elem = item["gst_device"].create_element(None)
                except Exception:
                    sink_elem = None
                break

        if sink_elem is None:
            try:
                pulse = Gst.ElementFactory.make("pulsesink", None)
                if pulse:
                    pulse.set_property("device", target_id)
                    sink_elem = pulse
            except Exception:
                sink_elem = None

        self.playbin.set_property("audio-sink", sink_elem)

    def _on_bus_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            self.playbin.set_state(Gst.State.NULL)
            self._play_next()
        elif t == Gst.MessageType.ERROR:
            err, _ = message.parse_error()
            self.playbin.set_state(Gst.State.NULL)
            if self.on_error:
                self.on_error(str(err))
            self._play_next()

    def play_queue(self, title: str, segments: List[AudioSegment], channel: str = "inside"):
        if not segments:
            return
        self.stop()
        self.current_title = title
        self.current_channel = channel
        self._apply_channel_sink(channel)
        self.queue = list(segments)
        self.current_index = -1
        self._play_next()

    def _play_next(self):
        self.current_index += 1
        if self.current_index < len(self.queue):
            segment = self.queue[self.current_index]
            self.is_playing = True
            self.is_paused = False

            if self.playbin:
                uri = GLib.filename_to_uri(os.path.abspath(segment.path))
                self.playbin.set_property("uri", uri)
                self.playbin.set_property("mute", self.is_muted)
                self.playbin.set_state(Gst.State.PLAYING)

            if self.on_segment_start:
                self.on_segment_start(
                    self.current_title,
                    self.current_index,
                    len(self.queue),
                    segment.name
                )
        else:
            self.stop()

    def skip_next(self):
        """跳过当前正在播放的片段，立即进入下一段"""
        if not self.is_playing:
            return
        if self.playbin:
            self.playbin.set_state(Gst.State.NULL)
        self._play_next()

    def stop(self):
        self.is_playing = False
        self.is_paused = False
        self.queue = []
        self.current_index = -1
        if self.playbin:
            self.playbin.set_state(Gst.State.NULL)
        if self.on_finished:
            self.on_finished()

    def toggle_pause(self):
        if not self.is_playing or not self.playbin:
            return
        if self.is_paused:
            self.playbin.set_state(Gst.State.PLAYING)
            self.is_paused = False
        else:
            self.playbin.set_state(Gst.State.PAUSED)
            self.is_paused = True
        if self.on_pause_changed:
            self.on_pause_changed(self.is_paused)

    def toggle_mute(self) -> bool:
        """切换静音状态"""
        self.is_muted = not self.is_muted
        if self.playbin and HAS_GST:
            self.playbin.set_property("mute", self.is_muted)
        return self.is_muted
